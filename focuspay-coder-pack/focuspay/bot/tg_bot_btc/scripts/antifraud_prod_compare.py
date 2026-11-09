#!/usr/bin/env python3
"""Prod antifraud comparison: PAID PDF vs non-PAID PDF, last 30 days."""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

BANKISH = (
    "jasperreports",
    "openpdf",
    "jaspersoft",
    "itext",
    "openhtmltopdf",
    "1t3xt",
    "apryse",
)
WATCH = ("oracle bi publisher", "oracle bipublisher", "ios version")
CONSUMER = (
    "microsoft",
    "word",
    "photoshop",
    "canva",
    "jspdf",
    "reportlab",
    "cairo",
    "print to pdf",
    "acrobat distiller",
    "quartz pdfcontext",
)
CHROME = ("skia/pdf", "chrome", "chromium")


def producer_of(raw: bytes) -> str | None:
    i = raw.find(b"/Producer")
    if i < 0:
        return None
    chunk = raw[i : i + 140].decode("latin1", "replace")
    m = re.search(r"/Producer\s*\(([^)]{0,100})", chunk)
    return m.group(1)[:100] if m else None


def creation_of(raw: bytes) -> str | None:
    i = raw.find(b"/CreationDate")
    if i < 0:
        return None
    chunk = raw[i : i + 80].decode("latin1", "replace")
    m = re.search(r"/CreationDate\s*\(([^)]{0,40})", chunk)
    return m.group(1) if m else None


def mediabox(raw: bytes):
    m = re.search(
        br"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        raw,
    )
    if not m:
        return None
    return tuple(float(x) for x in m.groups())


def page_kind(box) -> str | None:
    if not box:
        return None
    w = abs(box[2] - box[0])
    h = abs(box[3] - box[1])
    if w > 500 and h > 750:
        return "A4"
    if w < 350:
        return "narrow"
    return "other"


def classify_producer(p: str | None) -> str:
    if not p:
        return "unknown"
    b = p.lower()
    if any(s in b for s in BANKISH):
        return "bankish"
    if any(s in b for s in WATCH):
        return "watch"
    if any(s in b for s in CONSUMER):
        return "consumer"
    if any(s in b for s in CHROME):
        return "chrome"
    return "other"


def weak_name(n) -> bool:
    raw = (n or "").strip()
    if not raw or len(raw) <= 1:
        return True
    return all(not ch.isalpha() for ch in raw)


def parse_pdf_date(value: str | None):
    if not value:
        return None
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    try:
        return datetime(
            int(y),
            int(mo),
            int(d),
            int(hh or 0),
            int(mm or 0),
            int(ss or 0),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def as_naive_utc(dt):
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def main():
    import asyncpg

    from services.tg_account_age import estimate_age_days

    conn = await asyncpg.connect(os.environ["DATABASE_DSN"])
    # asyncpg TIMESTAMP WITHOUT TIME ZONE on some columns → naive UTC
    since = datetime.utcnow() - timedelta(days=30)

    vol = await conn.fetchrow(
        """
      SELECT
        COUNT(*) FILTER (WHERE direction='buy') AS buy_n,
        COUNT(*) FILTER (WHERE direction='buy' AND status='PAID') AS paid_n,
        COUNT(*) FILTER (WHERE direction='buy' AND status IN ('CANCELED','EXPIRED')) AS failed_n,
        COUNT(*) FILTER (WHERE direction='buy' AND receipt_file LIKE '%.pdf') AS pdf_n,
        COUNT(*) FILTER (WHERE direction='buy' AND status='PAID' AND receipt_file LIKE '%.pdf') AS paid_pdf_n
      FROM orders WHERE created_at >= $1
    """,
        since,
    )
    print("VOL30", json.dumps({k: int(v or 0) for k, v in dict(vol).items()}))

    ar = await conn.fetch(
        """
      SELECT coalesce(account_review_status,'none') AS st, COUNT(*)::int AS n
      FROM bot_users GROUP BY 1 ORDER BY n DESC
    """
    )
    print("ACCOUNT_REVIEW", json.dumps([dict(r) for r in ar]))

    reuse = await conn.fetchrow(
        """
      WITH w AS (
        SELECT wallet_address, COUNT(DISTINCT user_id)::int AS users, COUNT(*)::int AS orders,
               COUNT(*) FILTER (WHERE status='PAID')::int AS paid
        FROM orders
        WHERE direction='buy' AND wallet_address IS NOT NULL AND length(wallet_address)>10
          AND created_at >= $1
        GROUP BY 1
        HAVING COUNT(DISTINCT user_id) > 1
      )
      SELECT COUNT(*)::int AS wallets, COALESCE(SUM(orders),0)::int AS orders,
             COALESCE(SUM(paid),0)::int AS paid, COALESCE(SUM(users),0)::int AS users
      FROM w
    """,
        since,
    )
    print("WALLET_REUSE_CLUSTERS", json.dumps({k: int(v or 0) for k, v in dict(reuse).items()}))

    try:
        ip = await conn.fetchrow(
            """
          WITH i AS (
            SELECT host(client_ip)::text AS ip, COUNT(DISTINCT user_id)::int AS users,
                   COUNT(*)::int AS orders
            FROM orders
            WHERE client_ip IS NOT NULL AND created_at >= $1 AND user_id IS NOT NULL
            GROUP BY 1 HAVING COUNT(DISTINCT user_id) > 1
          )
          SELECT COUNT(*)::int AS ips, COALESCE(SUM(orders),0)::int AS orders,
                 COALESCE(SUM(users),0)::int AS users FROM i
        """,
            since,
        )
        print("IP_REUSE", json.dumps({k: int(v or 0) for k, v in dict(ip).items()}))
        cov = await conn.fetchrow(
            """
          SELECT COUNT(*) FILTER (WHERE client_ip IS NOT NULL)::int AS with_ip,
                 COUNT(*)::int AS total
          FROM orders WHERE direction='buy' AND created_at >= $1
        """,
            since,
        )
        print("IP_COVERAGE", json.dumps({k: int(v or 0) for k, v in dict(cov).items()}))
    except Exception as e:
        print("IP_ERR", type(e).__name__, str(e))

    rows = await conn.fetch(
        """
      SELECT o.order_id, o.user_id, o.status, o.fiat_amount, o.created_at, o.receipt_file,
             o.wallet_address, o.client_ip,
             o.payment_snapshot->>'amount_currency' AS amount_currency,
             o.payment_snapshot->>'requisites_issued_at' AS issued_at,
             b.username, b.first_name, b.first_seen_at, b.previous_username
      FROM orders o
      LEFT JOIN bot_users b ON b.user_id=o.user_id
      WHERE o.direction='buy' AND o.created_at >= $1
        AND o.receipt_file LIKE '%.pdf'
      ORDER BY o.created_at DESC
      LIMIT 800
    """,
        since,
    )

    multi_wallets = {
        r["wallet_address"]
        for r in await conn.fetch(
            """
          SELECT wallet_address FROM orders
          WHERE direction='buy' AND wallet_address IS NOT NULL AND length(wallet_address)>10
          GROUP BY 1 HAVING COUNT(DISTINCT user_id)>1
        """
        )
    }

    paid = collections.Counter()
    fail = collections.Counter()
    producers_paid = collections.Counter()
    producers_fail = collections.Counter()
    age_paid = collections.Counter()
    age_fail = collections.Counter()
    paid_n = fail_n = missing_files = 0

    for r in rows:
        path = Path("receipts") / str(r["receipt_file"])
        if not path.is_file():
            missing_files += 1
            continue
        raw = path.read_bytes()
        if not raw.startswith(b"%PDF"):
            continue

        prod = producer_of(raw)
        kind = page_kind(mediabox(raw))
        cls = classify_producer(prod)
        creat = creation_of(raw)
        creat_dt = parse_pdf_date(creat)
        issued = None
        if r["issued_at"]:
            try:
                issued = datetime.fromisoformat(str(r["issued_at"]).replace("Z", "+00:00"))
                issued = as_naive_utc(issued)
            except Exception:
                issued = None
        if issued is None and r["created_at"]:
            issued = as_naive_utc(r["created_at"])

        stale = False
        if creat_dt and issued:
            creat_n = as_naive_utc(creat_dt)
            stale = (issued - creat_n).total_seconds() > 300
        text = raw.decode("latin1", "ignore")
        fiat = float(r["fiat_amount"] or 0)
        whole = int(fiat) if fiat else 0
        amount_ok = None
        if whole > 0:
            patterns = [str(whole), f"{whole:,}".replace(",", " "), f"{whole:,}"]
            amount_ok = any(p in text for p in patterns)

        uname = (r["username"] or "").strip()
        fname = r["first_name"]
        fs = as_naive_utc(r["first_seen_at"])
        created = as_naive_utc(r["created_at"])
        fresh = False
        if fs and created:
            fresh = (created - fs).total_seconds() < 24 * 3600

        age = estimate_age_days(int(r["user_id"]))
        age_bucket = None
        if age is not None:
            if age < 7:
                age_bucket = "lt7"
            elif age < 30:
                age_bucket = "lt30"
            elif age < 365:
                age_bucket = "lt365"
            else:
                age_bucket = "ge365"

        is_paid = r["status"] == "PAID"
        c = paid if is_paid else fail
        if is_paid:
            paid_n += 1
            producers_paid[prod or "NULL"] += 1
            if age_bucket:
                age_paid[age_bucket] += 1
        else:
            fail_n += 1
            producers_fail[prod or "NULL"] += 1
            if age_bucket:
                age_fail[age_bucket] += 1

        c[f"cls_{cls}"] += 1
        if kind == "A4":
            c["a4"] += 1
        if kind == "narrow":
            c["narrow"] += 1
        if r["wallet_address"] in multi_wallets:
            c["wallet_shared"] += 1
        if (r["amount_currency"] or "") == "rub" and fiat >= 500 and abs(fiat % 500) < 0.01:
            c["round_rub"] += 1
        if not uname:
            c["no_username"] += 1
        if weak_name(fname):
            c["weak_name"] += 1
        if fresh:
            c["fresh24"] += 1
        if creat:
            c["creation_present"] += 1
        if stale:
            c["stale"] += 1
        if amount_ok is False:
            c["amount_miss"] += 1
        if amount_ok is True:
            c["amount_ok"] += 1

    def summarize(c, n):
        return {
            "n": n,
            "bankish_pct": pct(c["cls_bankish"], n),
            "watch_pct": pct(c["cls_watch"], n),
            "chrome_pct": pct(c["cls_chrome"], n),
            "consumer_pct": pct(c["cls_consumer"], n),
            "other_pct": pct(c["cls_other"] + c["cls_unknown"], n),
            "a4_pct": pct(c["a4"], n),
            "narrow_pct": pct(c["narrow"], n),
            "wallet_shared_pct": pct(c["wallet_shared"], n),
            "round_rub_pct": pct(c["round_rub"], n),
            "no_username_pct": pct(c["no_username"], n),
            "weak_name_pct": pct(c["weak_name"], n),
            "fresh24_pct": pct(c["fresh24"], n),
            "creation_present_pct": pct(c["creation_present"], n),
            "stale_pct": pct(c["stale"], n),
            "amount_miss_pct": pct(c["amount_miss"], n),
            "amount_ok_pct": pct(c["amount_ok"], n),
            "counts": dict(c),
        }

    out = {
        "missing_files": missing_files,
        "paid": summarize(paid, paid_n),
        "nonpaid": summarize(fail, fail_n),
        "top_producers_paid": producers_paid.most_common(10),
        "top_producers_nonpaid": producers_fail.most_common(10),
        "tg_age_paid": dict(age_paid),
        "tg_age_nonpaid": dict(age_fail),
    }
    print("PDF_COMPARE", json.dumps(out, ensure_ascii=False))

    conv = await conn.fetchrow(
        """
      WITH buyers AS (
        SELECT DISTINCT o.user_id, coalesce(nullif(b.username,''),'') <> '' AS has_user
        FROM orders o LEFT JOIN bot_users b ON b.user_id=o.user_id
        WHERE o.direction='buy' AND o.created_at>=$1
      ), stats AS (
        SELECT o.user_id,
          COUNT(*) FILTER (WHERE o.status='PAID') AS paid,
          COUNT(*) FILTER (WHERE o.status IN ('CANCELED','EXPIRED')) AS failed
        FROM orders o WHERE o.direction='buy' AND o.created_at>=$1 GROUP BY 1
      )
      SELECT
        COUNT(*) FILTER (WHERE has_user)::int AS buyers_with_user,
        COUNT(*) FILTER (WHERE NOT has_user)::int AS buyers_no_user,
        COALESCE(SUM(s.paid) FILTER (WHERE has_user),0)::int AS paid_with_user,
        COALESCE(SUM(s.paid) FILTER (WHERE NOT has_user),0)::int AS paid_no_user,
        COALESCE(SUM(s.failed) FILTER (WHERE has_user),0)::int AS fail_with_user,
        COALESCE(SUM(s.failed) FILTER (WHERE NOT has_user),0)::int AS fail_no_user
      FROM buyers b LEFT JOIN stats s ON s.user_id=b.user_id
    """,
        since,
    )
    print("USERNAME_CONV", json.dumps({k: int(v or 0) for k, v in dict(conv).items()}))

    # combo: how often paid vs fail have 2+ profile red flags among PDF sample
    # (approx from counters already per-row would be better — quick rescan)
    combo_paid = combo_fail = 0
    for r in rows:
        path = Path("receipts") / str(r["receipt_file"])
        if not path.is_file():
            continue
        uname = (r["username"] or "").strip()
        flags = 0
        if not uname:
            flags += 1
        if weak_name(r["first_name"]):
            flags += 1
        fs = as_naive_utc(r["first_seen_at"])
        created = as_naive_utc(r["created_at"])
        if fs and created:
            if (created - fs).total_seconds() < 24 * 3600:
                flags += 1
        age = estimate_age_days(int(r["user_id"]))
        if age is not None and age < 7:
            flags += 1
        if r["wallet_address"] in multi_wallets:
            flags += 2  # wallet alone would gate
        gated = (r["wallet_address"] in multi_wallets) or flags >= 2
        if r["status"] == "PAID":
            if gated:
                combo_paid += 1
        else:
            if gated:
                combo_fail += 1
    print(
        "WOULD_GATE_PDF_SAMPLE",
        json.dumps(
            {
                "paid_would_gate": combo_paid,
                "paid_n": paid_n,
                "paid_gate_pct": pct(combo_paid, paid_n),
                "nonpaid_would_gate": combo_fail,
                "nonpaid_n": fail_n,
                "nonpaid_gate_pct": pct(combo_fail, fail_n),
            }
        ),
    )

    suspects = await conn.fetch(
        """
      SELECT o.user_id, b.username, o.order_id, o.status, o.fiat_amount,
             left(o.wallet_address,42) AS w, o.created_at::text AS created_at
      FROM orders o LEFT JOIN bot_users b ON b.user_id=o.user_id
      WHERE o.wallet_address IN (
        SELECT wallet_address FROM orders WHERE direction='buy' AND wallet_address IS NOT NULL
        GROUP BY 1 HAVING COUNT(DISTINCT user_id)>1
      ) AND o.direction='buy' AND o.created_at >= $1
      ORDER BY o.created_at DESC LIMIT 15
    """,
        since,
    )
    print("REUSE_SAMPLES", json.dumps([dict(s) for s in suspects], ensure_ascii=False, default=str))

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

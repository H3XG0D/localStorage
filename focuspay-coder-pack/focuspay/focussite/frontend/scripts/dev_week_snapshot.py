#!/usr/bin/env python3
"""Rebuild gitignored .dev-week-snapshot.json from a Postgres dump.

Local Vite only. Never commit the JSON. DSN via FOCUSPAY_DEV_DUMP_DSN, or the
script starts a throwaway Postgres, restores FOCUSPAY_DEV_DUMP_PATH, extracts,
and removes the container.

Usage:
  FOCUSPAY_DEV_DUMP_DSN='host=127.0.0.1 port=55432 dbname=exchange_bot user=postgres password=localweek' \\
    python scripts/dev_week_snapshot.py
  python scripts/dev_week_snapshot.py   # podman restore of default dump
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent
SNAP = FRONTEND / ".dev-week-snapshot.json"
DEFAULT_DUMP = Path.home() / "Desktop/focuspay_backup_20260810/exchange_bot_20260810.dump"
BOT = "focuspay1_bot"
SITE = "https://focuspay.org"
MSK = ZoneInfo("Europe/Moscow")
CONTAINER = "fp-week-restore"
LOCAL_DSN = "host=127.0.0.1 port=55432 dbname=exchange_bot user=postgres password=localweek"

STATUS_LABELS = {
    "CREATED": "Создана",
    "AWAITING_CHECK": "Ожидает чек",
    "PENDING": "На проверке",
    "COMPLETED": "Выполнена",
    "PAID": "Оплачена",
    "FAILED": "Ошибка",
    "CANCELED": "Отменена",
    "EXPIRED": "Истекла",
    "DISPUTE": "Спор",
    "OPERATOR_PENDING": "Ожидает оператора",
}
SOURCE_LABELS = {
    "bot": "Telegram-бот",
    "site": "Сайт",
    "manual_operator": "Оператор",
    "manual": "Старые заявки",
    "telegram_auto": "Telegram",
}
SUB_TOKEN_LABELS = {"CARDRUB": "Карта", "SBPRUB": "СБП"}
DEFAULT_TIER = {"base_percent": 5.0, "step_percent": 5.0, "every_n": 5, "max_percent": 20.0}
PERIOD_LABELS = {
    "today": "сегодня",
    "yesterday": "вчера",
    "week": "неделя",
    "month": "месяц",
    "year": "год",
}


def json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def fnum(v: Any, nd=2) -> float:
    return round(float(v or 0), nd)


def parse_dsn(dsn: str) -> dict[str, str]:
    if "://" in dsn:
        u = urlparse(dsn)
        return {
            "host": u.hostname or "127.0.0.1",
            "port": str(u.port or 5432),
            "dbname": (u.path or "/postgres").lstrip("/") or "postgres",
            "user": u.username or "postgres",
            "password": u.password or "",
        }
    out: dict[str, str] = {}
    for part in dsn.split():
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


# ---- settings / profit -------------------------------------------------------

def merge_business(raw: dict | None) -> dict:
    out = {
        "buy_spread_auto_pct": 20.0,
        "buy_spread_manual_pct": 20.0,
        "sell_spread_pct": 5.0,
        "card_fee_auto_pct": 6.5,
        "card_fee_manual_pct": 0.0,
        "sell_profit_factor_pct": 75.0,
        "partner_tier_base_percent": 5.0,
        "partner_tier_step_percent": 5.0,
        "partner_tier_every_n": 5,
        "partner_tier_max_percent": 20.0,
        "user_referral_pct": 5.0,
    }
    if raw:
        for k in list(out):
            if raw.get(k) is not None:
                out[k] = raw[k]
    return out


def buy_markup(settings: dict, *, manual: bool) -> float:
    pct = float(settings["buy_spread_manual_pct" if manual else "buy_spread_auto_pct"])
    return 1.0 + pct / 100.0


def card_fee_frac(settings: dict, *, manual: bool) -> float:
    pct = float(settings["card_fee_manual_pct" if manual else "card_fee_auto_pct"])
    return pct / 100.0


def is_manual_card_fee(settings: dict, fee: float | None) -> bool:
    if fee is None:
        return False
    return abs(float(fee) - card_fee_frac(settings, manual=True)) < abs(float(fee) - card_fee_frac(settings, manual=False)) + 1e-9


def order_origin(settings: dict, row: dict) -> str:
    if str(row.get("direction") or "").lower() == "sell":
        return "manual"
    fee = row.get("card_fee_pct")
    if fee is not None:
        return "manual" if is_manual_card_fee(settings, float(fee)) else "auto"
    mid = str(row.get("merchant_order_id") or "").strip()
    oid = str(row.get("order_id") or "").strip()
    if mid and mid != oid and "-" in mid:
        return "auto"
    return "manual"


def order_service_profit(settings: dict, row: dict, *, clamp: bool = False) -> float:
    fiat = float(row.get("fiat_amount") or 0)
    if fiat <= 0:
        return 0.0
    direction = str(row.get("direction") or "buy").lower()
    crypto = str(row.get("crypto") or "")
    crypto_amount = float(row.get("crypto_amount") or 0)
    rate = float(row.get("rate") or 0)
    fee = row.get("card_fee_pct")
    fee_f = float(fee) if fee is not None else None
    if direction == "buy":
        cb = max(0.0, float(row.get("cashback_applied_rub") or 0))
        total_fiat = fiat + cb
        manual = is_manual_card_fee(settings, fee_f) if fee_f is not None else False
        markup = buy_markup(settings, manual=manual)
        if crypto_amount > 0 and rate > 0 and markup > 0:
            cost = crypto_amount * (rate / markup)
            gross = total_fiat - cost
            if clamp:
                gross = max(0.0, gross)
        elif markup > 1:
            gross = total_fiat * (1.0 - 1.0 / markup)
        else:
            gross = 0.0
        merchant = fiat * (fee_f if fee_f is not None else card_fee_frac(settings, manual=False))
        net = gross - merchant - cb
        return max(0.0, net) if clamp else net
    discount = 1.0 - float(settings["sell_spread_pct"]) / 100.0
    if discount <= 0:
        return 0.0
    return fiat * (1.0 / discount - 1.0) * (float(settings["sell_profit_factor_pct"]) / 100.0)


# ---- tiers -------------------------------------------------------------------

def effective_percent(refs: int, *, base_percent, step_percent, every_n, max_percent) -> float:
    base = float(base_percent)
    cap = float(max_percent)
    if float(step_percent) <= 0:
        return min(base, cap)
    every_n = max(1, int(every_n))
    return min(base + (max(0, int(refs)) // every_n) * float(step_percent), cap)


def refs_until_next(refs: int, every_n: int) -> int:
    every_n = max(1, int(every_n))
    rem = max(0, int(refs)) % every_n
    return every_n if rem == 0 else every_n - rem


def resolve_tier(global_tier: dict, row: dict) -> dict:
    base = float(
        row["partner_tier_base_percent"]
        if row.get("partner_tier_base_percent") is not None
        else row["partner_commission_percent"]
        if row.get("partner_commission_percent") is not None
        else global_tier["base_percent"]
    )
    max_pct = float(
        row["partner_tier_max_percent"]
        if row.get("partner_tier_max_percent") is not None
        else global_tier["max_percent"]
    )
    max_pct = max(max_pct, base)
    return {
        "base_percent": base,
        "step_percent": float(
            row["partner_tier_step_percent"]
            if row.get("partner_tier_step_percent") is not None
            else global_tier["step_percent"]
        ),
        "every_n": int(
            row["partner_tier_every_n"]
            if row.get("partner_tier_every_n") is not None
            else global_tier["every_n"]
        ),
        "max_percent": max_pct,
    }


def delta_money(cur: float, prev: float) -> dict:
    abs_change = round(cur - prev, 2)
    pct = None if abs(prev) < 1e-9 else round((cur - prev) / abs(prev) * 100.0, 2)
    return {"current": round(cur, 2), "previous": round(prev, 2), "abs_change": abs_change, "pct_change": pct}


def delta_int(cur: int, prev: int) -> dict:
    abs_change = cur - prev
    pct = None if prev == 0 else round((cur - prev) / abs(prev) * 100.0, 2)
    return {"current": cur, "previous": prev, "abs_change": abs_change, "pct_change": pct}


def period_window(key: str, today: date) -> dict:
    if key == "today":
        y = today - timedelta(days=1)
        return {"from": today, "to": today, "prev_from": y, "prev_to": y}
    if key == "yesterday":
        y = today - timedelta(days=1)
        p = today - timedelta(days=2)
        return {"from": y, "to": y, "prev_from": p, "prev_to": p}
    if key == "week":
        monday = today - timedelta(days=today.weekday())
        into = (today - monday).days
        prev_monday = monday - timedelta(days=7)
        return {"from": monday, "to": today, "prev_from": prev_monday, "prev_to": prev_monday + timedelta(days=into)}
    if key == "month":
        current_from = today - timedelta(days=29)
        previous_to = current_from - timedelta(days=1)
        previous_from = previous_to - timedelta(days=29)
        return {"from": current_from, "to": today, "prev_from": previous_from, "prev_to": previous_to}
    first = date(today.year, 1, 1)
    try:
        prev_end = today.replace(year=today.year - 1)
    except ValueError:
        prev_end = date(today.year - 1, 2, 28)
    return {"from": first, "to": today, "prev_from": date(today.year - 1, 1, 1), "prev_to": prev_end}


# ---- extract -----------------------------------------------------------------

def fetch_settings(cur) -> dict:
    cur.execute("SELECT value FROM app_settings WHERE key = 'business'")
    row = cur.fetchone()
    raw = row["value"] if row else {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    return merge_business(raw if isinstance(raw, dict) else {})


def extract_orders(cur, settings: dict, week_from: datetime) -> tuple[list[dict], list[dict], dict[int, list[int]]]:
    cur.execute(
        """
        SELECT o.*,
               bu.username AS buyer_username,
               bu.first_name AS buyer_first_name,
               oa.display_name AS operator_display_name,
               oa.username AS operator_username,
               ura.referrer_user_id AS referrer_user_id,
               ru.username AS referrer_username,
               ru.first_name AS referrer_first_name
        FROM orders o
        LEFT JOIN bot_users bu ON bu.user_id = o.user_id
        LEFT JOIN operator_accounts oa ON oa.id = o.operator_id
        LEFT JOIN (
            SELECT DISTINCT ON (user_id) user_id, referrer_user_id
            FROM user_referral_attributions
            ORDER BY user_id, created_at ASC
        ) ura ON ura.user_id = o.user_id
        LEFT JOIN bot_users ru ON ru.user_id = ura.referrer_user_id
        WHERE o.created_at >= %s
        ORDER BY o.created_at DESC
        """,
        (week_from,),
    )
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT pa.user_id, pc.id AS campaign_id
        FROM promo_attributions pa
        JOIN promo_campaigns pc ON pc.code = pa.promo_code
        JOIN partner_accounts pacc ON pacc.promo_campaign_id = pc.id
        """
    )
    user_campaigns: dict[int, list[int]] = defaultdict(list)
    for r in cur.fetchall():
        user_campaigns[int(r["user_id"])].append(int(r["campaign_id"]))

    cur.execute(
        """
        SELECT pc.id,
               COALESCE(
                   NULLIF(BTRIM(pa.display_name), ''),
                   NULLIF(BTRIM(pc.name), ''),
                   NULLIF(BTRIM(pa.username), ''),
                   '#' || pc.id::text
               ) AS label
        FROM partner_accounts pa
        JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
        ORDER BY label
        """
    )
    partner_options = [{"id": int(r["id"]), "label": r["label"]} for r in cur.fetchall()]

    out = []
    for r in rows:
        uid = r.get("user_id")
        uname = r.get("buyer_username")
        if uname and not str(uname).startswith("@"):
            uname = f"@{uname}"
        cb = fnum(r.get("cashback_applied_rub"))
        disc = fnum(r.get("exchange_discount_applied_rub"))
        src = str(r.get("order_source") or "manual").strip().lower() or "manual"
        profit = round(order_service_profit(settings, r, clamp=False), 2)
        referrer_uname = r.get("referrer_username")
        if referrer_uname and not str(referrer_uname).startswith("@"):
            referrer_uname = f"@{referrer_uname}"
        campaigns = user_campaigns.get(int(uid), []) if uid else []
        sub = str(r.get("sub_token") or "").upper()
        item = {
            "id": r["id"],
            "order_id": r["order_id"],
            "user_id": uid,
            "buyer_username": uname,
            "buyer_first_name": r.get("buyer_first_name"),
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], r["status"]),
            "direction": r["direction"],
            "crypto": r["crypto"],
            "crypto_amount": float(r["crypto_amount"] or 0) if r.get("crypto_amount") is not None else None,
            "fiat_amount": float(r["fiat_amount"] or 0) if r.get("fiat_amount") is not None else None,
            "rate": float(r["rate"] or 0) if r.get("rate") is not None else None,
            "requisites": r.get("requisites"),
            "wallet_address": r.get("wallet_address"),
            "network": r.get("network"),
            "sub_token": r.get("sub_token"),
            "sub_token_label": SUB_TOKEN_LABELS.get(sub, sub or None),
            "merchant_order_id": r.get("merchant_order_id"),
            "order_source": src,
            "source_label": SOURCE_LABELS.get(src, src),
            "origin": order_origin(settings, r),
            "promo_code": r.get("promo_code"),
            "promo_bonus_percent": float(r["promo_bonus_percent"]) if r.get("promo_bonus_percent") is not None else None,
            "exchange_discount_applied_rub": disc,
            "balance_applied_rub": round(cb + disc, 2) if (cb + disc) > 0 else 0.0,
            "operator_id": r.get("operator_id"),
            "operator_name": r.get("operator_display_name") or r.get("operator_username"),
            "has_receipt": bool(r.get("receipt_file")),
            "cancel_reason": r.get("cancel_reason"),
            "canceled_by": r.get("canceled_by"),
            "created_at": iso(r.get("created_at")),
            "updated_at": iso(r.get("updated_at")),
            "expires_at": iso(r.get("expires_at")),
            "cashback_applied_rub": cb,
            "card_fee_pct": float(r["card_fee_pct"]) if r.get("card_fee_pct") is not None else None,
            "referrer_user_id": int(r["referrer_user_id"]) if r.get("referrer_user_id") is not None else None,
            "referrer_username": referrer_uname,
            "referrer_first_name": r.get("referrer_first_name"),
            "service_profit_rub": profit,
            "partner_campaign_ids": campaigns,
        }
        out.append(item)
    return out, partner_options, user_campaigns


def extract_partners(cur, settings: dict, user_campaigns: dict[int, list[int]], order_profits: dict[int, float]) -> dict:
    global_tier = {
        "base_percent": float(settings["partner_tier_base_percent"]),
        "step_percent": float(settings["partner_tier_step_percent"]),
        "every_n": int(settings["partner_tier_every_n"]),
        "max_percent": float(settings["partner_tier_max_percent"]),
    }
    cur.execute(
        """
        SELECT pc.*,
               pa.id AS partner_account_id,
               pa.username AS partner_username,
               pa.display_name AS partner_display_name,
               pa.is_active AS partner_is_active,
               pa.telegram_user_id
        FROM partner_accounts pa
        JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
        ORDER BY pc.created_at DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT pc.id AS campaign_id, o.user_id, o.direction, o.crypto, o.fiat_amount,
               o.crypto_amount, o.rate, o.cashback_applied_rub, o.card_fee_pct, o.status
        FROM orders o
        JOIN promo_attributions pa ON pa.user_id = o.user_id
        JOIN promo_campaigns pc ON pc.code = pa.promo_code
        JOIN partner_accounts pacc ON pacc.promo_campaign_id = pc.id
        WHERE o.status IN ('PAID', 'COMPLETED')
        """
    )
    gross_by: dict[int, float] = defaultdict(float)
    fiat_by: dict[int, float] = defaultdict(float)
    paid_cnt: dict[int, int] = defaultdict(int)
    for r in cur.fetchall():
        cid = int(r["campaign_id"])
        gross_by[cid] += order_service_profit(settings, dict(r), clamp=True)
        fiat_by[cid] += float(r["fiat_amount"] or 0)
        paid_cnt[cid] += 1

    partners = []
    summary = {
        "count": 0,
        "active_count": 0,
        "total_balance_rub": 0.0,
        "total_accrued_rub": 0.0,
        "total_paid_out_rub": 0.0,
        "total_turnover_rub": 0.0,
        "total_service_profit_gross_rub": 0.0,
        "total_service_profit_net_rub": 0.0,
    }
    promos_by_id = {}
    withdrawals_by_id = {}

    for r in rows:
        pid = int(r["id"])
        code = r["code"]
        token = r.get("ref_token") or code
        cur.execute("SELECT COALESCE(SUM(amount_rub), 0)::float AS v FROM partner_ledger WHERE campaign_id = %s", (pid,))
        balance = float(cur.fetchone()["v"] or 0)
        cur.execute("SELECT COUNT(*)::int AS v FROM promo_attributions WHERE promo_code = %s", (code,))
        attracted = int(cur.fetchone()["v"] or 0)
        cur.execute(
            "SELECT COALESCE(SUM(amount_rub), 0)::float AS v FROM partner_ledger WHERE campaign_id = %s AND type = 'accrual'",
            (pid,),
        )
        accrued = fnum(cur.fetchone()["v"])
        cur.execute(
            "SELECT COALESCE(SUM(amount_rub), 0)::float AS v FROM partner_ledger WHERE campaign_id = %s AND type = 'payout'",
            (pid,),
        )
        paid_out = round(abs(float(cur.fetchone()["v"] or 0)), 2)
        paid_fiat = fnum(fiat_by.get(pid, 0))
        paid_n = paid_cnt.get(pid, 0)
        gross = round(gross_by.get(pid, 0.0), 2)
        net = round(gross - accrued, 2)
        tset = resolve_tier(global_tier, r)
        eff = round(effective_percent(attracted, **tset), 2)
        nxt_raw = None
        at_max = float(tset["step_percent"]) <= 0 or eff >= tset["max_percent"]
        if not at_max:
            nxt_raw = effective_percent(attracted + refs_until_next(attracted, tset["every_n"]), **tset)
        until = 0 if at_max else refs_until_next(attracted, tset["every_n"])
        item = {
            "id": pid,
            "code": code,
            "name": r["name"],
            "partner_commission_percent": float(r.get("partner_commission_percent") or 10),
            "effective_percent": eff,
            "refs_until_next_tier": until,
            "next_tier_percent": round(nxt_raw, 2) if nxt_raw is not None else None,
            "at_max_tier": at_max,
            "tier_base_percent": tset["base_percent"],
            "tier_step_percent": tset["step_percent"],
            "tier_every_n": tset["every_n"],
            "tier_max_percent": tset["max_percent"],
            "ad_spend_rub": float(r.get("ad_spend_rub") or 0),
            "campaign_kind": "partner",
            "is_active": bool(r["is_active"]),
            "created_at": iso(r.get("created_at")),
            "partner_account_id": r.get("partner_account_id"),
            "partner_username": r.get("partner_username"),
            "partner_display_name": r.get("partner_display_name"),
            "partner_is_active": bool(r.get("partner_is_active", True)),
            "telegram_user_id": r.get("telegram_user_id"),
            "balance_rub": round(balance, 2),
            "attracted_users": attracted,
            "status": "active" if r["is_active"] else "disabled",
            "referral_link": f"https://t.me/{BOT}?start=ref_{token}",
            "referral_web_link": f"{SITE}/ref/{token}",
            "ref_token": token,
            "paid_orders_count": paid_n,
            "paid_fiat_sum": paid_fiat,
            "total_accrued": accrued,
            "total_paid_out": paid_out,
            "service_profit_gross_rub": gross,
            "service_profit_net_rub": net,
            "partner_tier_base_percent": tset["base_percent"],
            "partner_tier_step_percent": tset["step_percent"],
            "partner_tier_every_n": tset["every_n"],
            "partner_tier_max_percent": tset["max_percent"],
        }
        partners.append(item)
        summary["count"] += 1
        if item["is_active"] and item["partner_is_active"]:
            summary["active_count"] += 1
        summary["total_balance_rub"] += item["balance_rub"]
        summary["total_accrued_rub"] += item["total_accrued"]
        summary["total_paid_out_rub"] += item["total_paid_out"]
        summary["total_turnover_rub"] += item["paid_fiat_sum"]
        summary["total_service_profit_gross_rub"] += gross
        summary["total_service_profit_net_rub"] += net

        cur.execute(
            """
            SELECT pa.user_id, pa.assigned_at, bu.username, bu.first_name
            FROM promo_attributions pa
            LEFT JOIN bot_users bu ON bu.user_id = pa.user_id
            WHERE pa.promo_code = %s
            ORDER BY pa.assigned_at DESC LIMIT 40
            """,
            (code,),
        )
        users = []
        for u in cur.fetchall():
            assigned = iso(u["assigned_at"])
            users.append(
                {
                    "user_id": u["user_id"],
                    "username": u["username"],
                    "first_name": u["first_name"],
                    "assigned_at": assigned,
                    "entered_at": assigned,
                }
            )
        cur.execute(
            """
            SELECT o.order_id, o.status, o.direction, o.fiat_amount, o.created_at
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = %s
            ORDER BY o.created_at DESC LIMIT 40
            """,
            (code,),
        )
        orders = [
            {
                "order_id": o["order_id"],
                "status": o["status"],
                "direction": o["direction"],
                "fiat_amount": float(o["fiat_amount"] or 0),
                "created_at": iso(o["created_at"]),
            }
            for o in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM partner_ledger WHERE campaign_id = %s
            ORDER BY created_at DESC LIMIT 40
            """,
            (pid,),
        )
        ledger = [
            {
                "id": e["id"],
                "type": e["type"],
                "amount_rub": float(e["amount_rub"] or 0),
                "order_id": e["order_id"],
                "note": e["note"],
                "created_at": iso(e["created_at"]),
            }
            for e in cur.fetchall()
        ]
        ad_spend = float(r.get("ad_spend_rub") or 0)
        promos_by_id[str(pid)] = {
            "promo": {
                "id": pid,
                "code": code,
                "name": r["name"],
                "bonus_percent": float(r["bonus_percent"] or 0),
                "ad_spend_rub": ad_spend,
                "partner_commission_percent": float(r.get("partner_commission_percent") or 10),
                "campaign_kind": r.get("campaign_kind") or "partner",
                "is_active": bool(r["is_active"]),
                "created_at": iso(r.get("created_at")),
                "referral_link": item["referral_link"],
                "referral_web_link": item["referral_web_link"],
                "partner_balance_rub": round(balance, 2),
                "partner_username": r.get("partner_username"),
                "activations_used": attracted,
                "status": item["status"],
            },
            "partner": {
                "account_id": r.get("partner_account_id"),
                "username": r.get("partner_username"),
                "display_name": r.get("partner_display_name"),
                "is_active": r.get("partner_is_active"),
            },
            "metrics": {
                "attracted_users": attracted,
                "activations_used": attracted,
                "paid_orders_count": paid_n,
                "paid_fiat_sum": paid_fiat,
                "partner_balance_rub": round(balance, 2),
                "total_accrued": accrued,
                "total_paid_out": paid_out,
                "ad_spend_rub": ad_spend,
                "net_after_ad_spend": round(balance - ad_spend, 2),
                "service_profit_gross_rub": gross,
                "service_profit_net_rub": net,
            },
            "users": users,
            "gift_entries": [],
            "orders": orders,
            "ledger": ledger,
        }
        withdrawals_by_id[str(pid)] = {"withdrawals": []}

    for k in list(summary):
        if k not in ("count", "active_count"):
            summary[k] = round(summary[k], 2)

    every_n = int(global_tier["every_n"])
    preview = [
        {"refs": r, "effective_percent": round(effective_percent(r, **global_tier), 2)}
        for r in (0, every_n, every_n * 2, every_n * 3)
    ]
    return {
        "referral_partners": {"partners": partners, "summary": summary},
        "tier_settings": {
            "settings": {
                "partner_tier_base_percent": global_tier["base_percent"],
                "partner_tier_step_percent": global_tier["step_percent"],
                "partner_tier_every_n": global_tier["every_n"],
                "partner_tier_max_percent": global_tier["max_percent"],
                "user_referral_pct": float(settings.get("user_referral_pct", 5)),
            },
            "preview": preview,
        },
        "promos_by_id": promos_by_id,
        "partner_withdrawals_by_id": withdrawals_by_id,
    }


def extract_users(cur, settings: dict, week_from: datetime) -> tuple[list[dict], dict[str, dict]]:
    cur.execute(
        """
        SELECT
            u.user_id, u.username, u.first_name, u.first_seen_at, u.last_seen_at,
            wu.email AS web_email,
            CASE
                WHEN wu.id IS NULL THEN 'bot'
                WHEN wu.telegram_user_id IS NOT NULL THEN 'web+bot'
                ELSE 'web'
            END AS channel,
            COUNT(o.id)::int AS total_orders,
            COUNT(CASE WHEN o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS paid_orders,
            COALESCE(SUM(CASE WHEN o.status IN ('PAID','COMPLETED') THEN o.fiat_amount END), 0)::float AS total_fiat,
            MAX(o.created_at) AS last_order_at,
            COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL THEN 1 END)::int AS payfast_taken,
            COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status = 'PAID' THEN 1 END)::int AS payfast_paid,
            COUNT(CASE WHEN o.direction = 'buy' AND o.merchant_order_id IS NOT NULL AND o.status IN ('CANCELED','EXPIRED') THEN 1 END)::int AS payfast_failed,
            COUNT(CASE WHEN o.status IN ('CANCELED','EXPIRED') THEN 1 END)::int AS canceled_orders,
            COUNT(CASE WHEN o.status = 'COMPLETED' THEN 1 END)::int AS completed_orders,
            COUNT(CASE WHEN o.direction = 'buy' AND o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS buy_paid,
            COUNT(CASE WHEN o.direction = 'sell' AND o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS sell_paid
        FROM bot_users u
        LEFT JOIN web_users wu ON wu.telegram_user_id = u.user_id OR wu.client_user_id = u.user_id
        LEFT JOIN orders o ON o.user_id = u.user_id
        WHERE u.user_id IN (
            SELECT DISTINCT user_id FROM orders WHERE created_at >= %s AND user_id IS NOT NULL
        )
        GROUP BY u.user_id, wu.id, wu.email, wu.telegram_user_id
        ORDER BY last_order_at DESC NULLS LAST
        LIMIT 250
        """,
        (week_from,),
    )
    users = []
    for r in cur.fetchall():
        taken = int(r["payfast_taken"] or 0)
        paid = int(r["payfast_paid"] or 0)
        failed = int(r["payfast_failed"] or 0)
        denom = paid + failed
        conv = round(100.0 * paid / denom, 1) if denom else None
        users.append(
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "channel": r["channel"],
                "web_email": r["web_email"],
                "first_seen_at": iso(r["first_seen_at"]),
                "last_seen_at": iso(r["last_seen_at"]),
                "total_orders": int(r["total_orders"] or 0),
                "paid_orders": int(r["paid_orders"] or 0),
                "total_fiat": fnum(r["total_fiat"]),
                "last_order_at": iso(r["last_order_at"]),
                "payfast_taken": taken,
                "payfast_paid": paid,
                "payfast_failed": failed,
                "conversion_pct": conv,
                "canceled_orders": int(r["canceled_orders"] or 0),
                "completed_orders": int(r["completed_orders"] or 0),
                "buy_paid": int(r["buy_paid"] or 0),
                "sell_paid": int(r["sell_paid"] or 0),
            }
        )

    ids = [u["user_id"] for u in users]
    by_id: dict[str, dict] = {}
    if not ids:
        return users, by_id

    cur.execute(
        """
        SELECT DISTINCT ON (user_id) user_id, referrer_user_id
        FROM user_referral_attributions
        WHERE user_id = ANY(%s)
        ORDER BY user_id, created_at ASC
        """,
        (ids,),
    )
    ref_map = {int(r["user_id"]): int(r["referrer_user_id"]) for r in cur.fetchall() if r.get("referrer_user_id")}
    ref_ids = list(set(ref_map.values()))
    ref_users = {}
    if ref_ids:
        cur.execute("SELECT user_id, username, first_name FROM bot_users WHERE user_id = ANY(%s)", (ref_ids,))
        ref_users = {int(r["user_id"]): dict(r) for r in cur.fetchall()}

    bal = {}
    try:
        cur.execute(
            """
            SELECT user_id,
                   COALESCE(SUM(CASE WHEN type = 'accrual' THEN amount_rub ELSE 0 END), 0)::float AS cashback_accrued,
                   COALESCE(SUM(amount_rub), 0)::float AS cashback_rub
            FROM user_cashback_ledger WHERE user_id = ANY(%s) GROUP BY user_id
            """,
            (ids,),
        )
        for r in cur.fetchall():
            bal[int(r["user_id"])] = {"cashback_rub": fnum(r["cashback_rub"]), "cashback_accrued": fnum(r["cashback_accrued"])}
    except Exception:
        pass

    ref_bal = {}
    try:
        cur.execute(
            """
            SELECT referrer_user_id AS user_id,
                   COUNT(*)::int AS referred_count
            FROM user_referral_attributions WHERE referrer_user_id = ANY(%s)
            GROUP BY referrer_user_id
            """,
            (ids,),
        )
        for r in cur.fetchall():
            ref_bal[int(r["user_id"])] = {"referred_count": int(r["referred_count"] or 0)}
        cur.execute(
            """
            SELECT referrer_user_id AS user_id,
                   COALESCE(SUM(CASE WHEN type = 'accrual' THEN amount_rub ELSE 0 END), 0)::float AS total_accrual_rub,
                   COALESCE(SUM(amount_rub), 0)::float AS balance_rub
            FROM user_referral_ledger WHERE referrer_user_id = ANY(%s) GROUP BY referrer_user_id
            """,
            (ids,),
        )
        for r in cur.fetchall():
            ref_bal.setdefault(int(r["user_id"]), {})
            ref_bal[int(r["user_id"])]["total_accrual_rub"] = fnum(r["total_accrual_rub"])
            ref_bal[int(r["user_id"])]["referral_balance_rub"] = fnum(r["balance_rub"])
    except Exception:
        pass

    cur.execute(
        """
        SELECT order_id, user_id, status, direction, crypto, crypto_amount, fiat_amount, rate, created_at
        FROM orders WHERE user_id = ANY(%s)
        ORDER BY created_at DESC
        """,
        (ids,),
    )
    recent: dict[int, list] = defaultdict(list)
    paid_rows: dict[int, list] = defaultdict(list)
    for r in cur.fetchall():
        uid = int(r["user_id"])
        rec = {
            "order_id": r["order_id"],
            "user_id": uid,
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], r["status"]),
            "direction": r["direction"],
            "crypto": r["crypto"],
            "crypto_amount": float(r["crypto_amount"] or 0) if r.get("crypto_amount") is not None else None,
            "fiat_amount": float(r["fiat_amount"] or 0) if r.get("fiat_amount") is not None else None,
            "rate": float(r["rate"] or 0) if r.get("rate") is not None else None,
            "created_at": iso(r["created_at"]),
        }
        if len(recent[uid]) < 15:
            recent[uid].append(rec)
        if r["status"] == "PAID":
            paid_rows[uid].append(dict(r))

    promo = {}
    try:
        cur.execute(
            """
            SELECT DISTINCT ON (user_id) user_id, promo_code, assigned_at
            FROM promo_attributions WHERE user_id = ANY(%s)
            ORDER BY user_id, assigned_at DESC
            """,
            (ids,),
        )
        for r in cur.fetchall():
            promo[int(r["user_id"])] = {"promo_code": r["promo_code"], "assigned_at": iso(r["assigned_at"])}
    except Exception:
        pass

    for u in users:
        uid = int(u["user_id"])
        inv = None
        rid = ref_map.get(uid)
        if rid:
            ru = ref_users.get(rid) or {}
            inv = {"user_id": rid, "username": ru.get("username"), "first_name": ru.get("first_name")}
        b = bal.get(uid, {})
        rb = ref_bal.get(uid, {})
        paid = paid_rows.get(uid, [])
        gross = round(sum(order_service_profit(settings, p, clamp=True) for p in paid), 2)
        cb_acc = float(b.get("cashback_accrued") or 0)
        ref_acc = float(rb.get("total_accrual_rub") or 0)
        by_id[str(uid)] = {
            "identity": {
                "user_id": uid,
                "username": u["username"],
                "first_name": u["first_name"],
                "first_seen_at": u["first_seen_at"],
                "last_seen_at": u["last_seen_at"],
                "avatar_url": None,
                "invited_by": inv,
                "is_banned": False,
                "has_username": bool(u.get("username")),
                "account_review_status": "none",
            },
            "summary": {
                "total_orders": u["total_orders"],
                "paid_orders": u["paid_orders"],
                "completed_orders": u.get("completed_orders") or 0,
                "canceled_orders": u.get("canceled_orders") or 0,
                "buy_paid": u.get("buy_paid") or 0,
                "sell_paid": u.get("sell_paid") or 0,
                "turnover_rub": u["total_fiat"],
                "payfast_taken": u["payfast_taken"],
                "payfast_paid": u["payfast_paid"],
                "payfast_failed": u["payfast_failed"],
                "conversion_pct": u["conversion_pct"],
            },
            "last_deal": recent.get(uid, [None])[0] if recent.get(uid) else None,
            "active_order": None,
            "balances": {
                "cashback_rub": b.get("cashback_rub", 0),
                "referral_rub": rb.get("referral_balance_rub", 0),
                "balance_rub": fnum((b.get("cashback_rub") or 0) + (rb.get("referral_balance_rub") or 0)),
                "available_rub": fnum((b.get("cashback_rub") or 0) + (rb.get("referral_balance_rub") or 0)),
            },
            "referral": {
                "referred_count": rb.get("referred_count", 0),
                "paid_orders_count": 0,
                "referral_balance_rub": rb.get("referral_balance_rub", 0),
                "total_accrual_rub": rb.get("total_accrual_rub", 0),
                "referrer": inv,
            },
            "promo": promo.get(uid),
            "recent_orders": recent.get(uid, []),
            "finance": {
                "gross_profit_rub": gross,
                "cashback_accrued_rub": round(cb_acc, 2),
                "referral_accrued_rub": round(ref_acc, 2),
                "review_bonus_rub": 0.0,
                "net_profit_rub": round(gross - cb_acc - ref_acc, 2),
            },
            "ledgers": {"cashback": [], "referral": []},
            "reviews": [],
        }
    return users, by_id


def extract_dashboard(cur, settings: dict, today: date) -> dict:
    cur.execute(
        """
        SELECT o.created_at, o.status, o.fiat_amount, o.direction, o.crypto,
               o.crypto_amount, o.rate, o.cashback_applied_rub, o.card_fee_pct
        FROM orders o
        """
    )
    all_orders = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT first_seen_at FROM bot_users WHERE first_seen_at IS NOT NULL")
    user_seen = [r["first_seen_at"].date() if isinstance(r["first_seen_at"], datetime) else r["first_seen_at"] for r in cur.fetchall()]
    cur.execute("SELECT created_at FROM partner_accounts")
    partner_created = [
        (r["created_at"].date() if isinstance(r["created_at"], datetime) else r["created_at"])
        for r in cur.fetchall()
        if r.get("created_at")
    ]

    def in_range(d: date | None, a: date, b: date) -> bool:
        return d is not None and a <= d <= b

    def metrics_for(a: date, b: date) -> dict:
        paid = []
        for o in all_orders:
            dt = o["created_at"]
            day = dt.date() if isinstance(dt, datetime) else dt
            if not in_range(day, a, b):
                continue
            if o["status"] in ("PAID", "COMPLETED"):
                paid.append(o)
        profit = sum(order_service_profit(settings, o, clamp=True) for o in paid)
        turnover = sum(float(o.get("fiat_amount") or 0) for o in paid)
        return {
            "orders": len(paid),
            "net_income_rub": profit,
            "gross_commissions_rub": profit,
            "turnover_rub": turnover,
            "costs_total_rub": 0.0,
        }

    def audience(a: date, b: date) -> dict:
        bot_new = sum(1 for d in user_seen if in_range(d, a, b))
        partners = sum(1 for d in partner_created if in_range(d, a, b))
        return {"new_users": bot_new, "bot_new": bot_new, "web_new": 0, "new_partners": partners}

    owner: dict[str, Any] = {}
    for key in PERIOD_LABELS:
        w = period_window(key, today)
        cur_m = metrics_for(w["from"], w["to"])
        prev_m = metrics_for(w["prev_from"], w["prev_to"])
        cur_a = audience(w["from"], w["to"])
        prev_a = audience(w["prev_from"], w["prev_to"])
        days = (w["to"] - w["from"]).days + 1
        points = []
        if days <= 7:
            day = w["from"]
            while day <= w["to"]:
                m = metrics_for(day, day)
                points.append(
                    {
                        "date": day.isoformat(),
                        "net_income_rub": round(m["net_income_rub"], 2),
                        "gross_commissions_rub": round(m["gross_commissions_rub"], 2),
                        "orders": m["orders"],
                        "expenses_total_rub": 0.0,
                        "expense_lines": [],
                    }
                )
                day += timedelta(days=1)
        income = (
            {"data_status": "available", "reason": None, "metric": "net_income", "currency": "RUB", "source": "compute_pnl", "points": points}
            if points
            else {"data_status": "unavailable", "reason": "period_too_long_for_daily_pnl", "metric": "net_income", "points": []}
        )
        owner[key] = {
            "timezone": "Europe/Moscow",
            "week_starts_on": "monday",
            "currency": "RUB",
            "definitions": {
                "net_income": "dump snapshot: service profit of PAID+COMPLETED",
                "gross_commissions": "same as net_income in snapshot",
                "orders": "PAID+COMPLETED count",
                "turnover_note": "turnover_rub is fiat volume, not income",
            },
            "period": {
                "key": key,
                "label": PERIOD_LABELS[key],
                "current": {"from": w["from"].isoformat(), "to": w["to"].isoformat()},
                "previous": {"from": w["prev_from"].isoformat(), "to": w["prev_to"].isoformat()},
            },
            "data_source": {"finance": "compute_pnl", "status": "available", "fetched_at": datetime.now(MSK).isoformat()},
            "metrics": {
                "net_income": {**delta_money(cur_m["net_income_rub"], prev_m["net_income_rub"]), "currency": "RUB", "unit": "money"},
                "gross_commissions": {**delta_money(cur_m["gross_commissions_rub"], prev_m["gross_commissions_rub"]), "currency": "RUB", "unit": "money"},
                "orders": {**delta_int(cur_m["orders"], prev_m["orders"]), "unit": "count"},
                "new_users": {
                    **delta_int(cur_a["new_users"], prev_a["new_users"]),
                    "unit": "count",
                    "breakdown": {
                        "bot_new": cur_a["bot_new"],
                        "web_new": 0,
                        "previous_bot_new": prev_a["bot_new"],
                        "previous_web_new": 0,
                    },
                },
                "new_partners": {**delta_int(cur_a["new_partners"], prev_a["new_partners"]), "unit": "count"},
                "turnover_rub": {**delta_money(cur_m["turnover_rub"], prev_m["turnover_rub"]), "currency": "RUB", "unit": "money", "is_income": False},
            },
            "refunds": {"data_status": "unavailable", "reason": "no_confirmed_refund_source", "amount_rub": None},
            "ledger": {"data_status": "unavailable", "reason": "no_confirmed_entries", "entries": [], "by_type": []},
            "income_by_day": income,
            "pnl_by_day": income,
            "raw_costs_current": {
                "costs_total_rub": 0,
                "manual_expenses_rub": 0,
                "operators_payroll_rub": 0,
                "admin_salary_rub": 0,
                "profit_after_costs_rub": round(cur_m["net_income_rub"], 2),
            },
        }

    operators = []
    try:
        cur.execute(
            """
            SELECT id, username, display_name, is_active
            FROM operator_accounts
            ORDER BY id
            LIMIT 20
            """
        )
        for r in cur.fetchall():
            operators.append(
                {
                    "id": r["id"],
                    "name": r.get("display_name") or r.get("username"),
                    "on_shift": False,
                    "orders_in_work": 0,
                    "in_work_rub": 0,
                    "in_work_usd": 0,
                    "wallet_rub": 0,
                    "wallet_usd": 0,
                    "shift_id": None,
                    "turnover": 0,
                    "fiat_total": 0,
                    "orders_count": 0,
                    "earnings": 0,
                    "earnings_rub": 0,
                }
            )
    except Exception:
        pass

    live = {
        "can_view_finance": True,
        "wallet": {
            "total_rub": 0,
            "total_usd": 0,
            "reported_by": 0,
            "discrepancies": [],
            "active_shifts": [],
        },
        "operators": operators,
        "payroll": {"pool_total_rub": 0, "pool_available_rub": 0, "pending_requests_count": 0, "operators": []},
    }
    liab = {
        "total_rub": 0,
        "usdt_rub_rate": 80,
        "sections": [
            {"id": "operators", "label": "Операторы", "amount_rub": 0},
            {"id": "buyers", "label": "Клиенты", "amount_rub": 0},
            {"id": "referrers", "label": "Рефереры", "amount_rub": 0},
            {"id": "partners", "label": "Партнёры", "amount_rub": 0},
            {"id": "admins", "label": "Админы", "amount_rub": 0},
            {"id": "external", "label": "Внешние", "amount_rub": 0, "amount_usd": 0},
        ],
    }
    return {"dashboard_live": live, "dashboard_liabilities": liab, "dashboard_owner": owner}


def _table_cols(cur, name: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (name,),
    )
    return {str(r["column_name"]) for r in cur.fetchall()}


def extract_analytics_extras(cur, settings: dict, orders: list[dict]) -> dict:
    misses: dict[str, Any] = {
        "data_status": "unavailable",
        "reason": "table_missing",
        "rows": [],
        "definitions": {
            "miss": "Клиент не получил реквизиты: на смене не было обеих ролей. Те же пропуски, что в /dash.",
        },
    }
    try:
        cols = _table_cols(cur, "no_shift_requisites_blocks")
        if {"id", "user_id", "direction", "created_at"}.issubset(cols):
            select = ["id", "user_id", "direction", "created_at"]
            if "reason" in cols:
                select.append("reason")
            if "fiat_amount" in cols:
                select.append("fiat_amount")
            cur.execute(f"SELECT {', '.join(select)} FROM no_shift_requisites_blocks ORDER BY created_at ASC")
            rows = []
            for r in cur.fetchall():
                item = {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "direction": r.get("direction") or "buy",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "reason": r.get("reason") or "no_shift" if "reason" in cols else "no_shift",
                    "fiat_amount": float(r["fiat_amount"]) if r.get("fiat_amount") is not None else None,
                }
                rows.append(item)
            misses = {
                "data_status": "available" if rows else "empty",
                "reason": None if rows else "no_rows",
                "rows": rows,
                "definitions": misses["definitions"],
            }
    except Exception:
        pass

    external = {
        "active_count": 0,
        "total_count": 0,
        "total_balance_usd": 0.0,
        "total_turnover_base_rub": 0.0,
        "total_turnover_client_rub": 0.0,
        "house_profit_usd": 0.0,
        "deal_profit_usd": 0.0,
        "payout_fee_usd": 0.0,
        "total_deals": 0,
        "total_payouts": 0,
        "source": "snapshot_approx",
    }
    try:
        if _table_cols(cur, "external_exchangers"):
            cur.execute("SELECT COUNT(*)::int AS n, COUNT(*) FILTER (WHERE is_active) ::int AS a FROM external_exchangers")
            row = cur.fetchone() or {}
            external["total_count"] = int(row.get("n") or 0)
            external["active_count"] = int(row.get("a") or 0)
        if _table_cols(cur, "external_deals"):
            cur.execute(
                """
                SELECT COUNT(*)::int AS n,
                       COALESCE(SUM(amount_rub), 0)::float AS turnover,
                       COALESCE(SUM(house_profit_usd), 0)::float AS profit
                FROM external_deals
                """
            )
            row = cur.fetchone() or {}
            external["total_deals"] = int(row.get("n") or 0)
            external["total_turnover_base_rub"] = round(float(row.get("turnover") or 0), 2)
            external["deal_profit_usd"] = round(float(row.get("profit") or 0), 6)
        if _table_cols(cur, "external_payouts"):
            cur.execute("SELECT COUNT(*)::int AS n, COALESCE(SUM(fee_usd), 0)::float AS fee FROM external_payouts")
            row = cur.fetchone() or {}
            external["total_payouts"] = int(row.get("n") or 0)
            external["payout_fee_usd"] = round(float(row.get("fee") or 0), 6)
        external["house_profit_usd"] = round(external["deal_profit_usd"] + external["payout_fee_usd"], 6)
    except Exception:
        pass

    campaigns = []
    try:
        cur.execute(
            """
            SELECT id, code, name, bonus_percent, ad_spend_rub, partner_commission_percent, is_active
            FROM promo_campaigns
            ORDER BY id
            """
        )
        for r in cur.fetchall():
            campaigns.append(
                {
                    "id": r["id"],
                    "code": r["code"],
                    "name": r["name"],
                    "bonus_percent": float(r["bonus_percent"] or 0),
                    "partner_commission_percent": float(r.get("partner_commission_percent") or 10),
                    "ad_spend_rub": float(r.get("ad_spend_rub") or 0),
                    "is_active": bool(r.get("is_active")),
                    "attracted_users": 0,
                    "paid_orders_count": 0,
                    "paid_fiat_sum": 0.0,
                    "roi_percent": None,
                    "estimated_profit": 0.0,
                }
            )
    except Exception:
        pass

    return {
        "misses": misses,
        "external_summary": external,
        "promo_campaigns": campaigns,
        "analytics_source": "snapshot_approx",
    }


def extract_admin(conn) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    settings = fetch_settings(cur)
    cur.execute("SELECT MAX(created_at) AS v FROM orders")
    max_created = cur.fetchone()["v"]
    if max_created is None:
        raise SystemExit("dump has no orders")
    if max_created.tzinfo is None:
        max_created = max_created.replace(tzinfo=MSK)
    week_from = max_created - timedelta(days=7)
    today = max_created.astimezone(MSK).date()

    orders, partner_options, user_campaigns = extract_orders(cur, settings, week_from)
    order_profits = {}
    partner_blob = extract_partners(cur, settings, user_campaigns, order_profits)
    users, users_by_id = extract_users(cur, settings, week_from)
    dash = extract_dashboard(cur, settings, today)
    extra = extract_analytics_extras(cur, settings, orders)

    admin = {
        "orders": {
            "orders": orders,
            "total": len(orders),
            "limit": 50,
            "offset": 0,
            "partner_options": partner_options,
        },
        "users": users,
        "users_by_id": users_by_id,
        **partner_blob,
        **dash,
        **extra,
    }
    return {
        "source": "dump-week",
        "pulled_at": datetime.now(MSK).isoformat(),
        "dump_week_from": week_from.isoformat(),
        "dump_week_to": max_created.isoformat(),
        "admin": admin,
    }


# ---- postgres bootstrap ------------------------------------------------------

def wait_pg(dsn: str, seconds: int = 40) -> None:
    parts = parse_dsn(dsn)
    for _ in range(seconds):
        try:
            conn = psycopg2.connect(**parts)
            conn.close()
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("postgres did not become ready")


def start_restore(dump: Path) -> str:
    subprocess.run(["podman", "rm", "-f", CONTAINER], check=False, capture_output=True)
    subprocess.run(
        [
            "podman", "run", "-d", "--name", CONTAINER,
            "-e", "POSTGRES_PASSWORD=localweek",
            "-e", "POSTGRES_DB=exchange_bot",
            "-e", "POSTGRES_USER=postgres",
            "-p", "127.0.0.1:55432:5432",
            "docker.io/library/postgres:16-alpine",
        ],
        check=True,
    )
    wait_pg(LOCAL_DSN)
    env = os.environ.copy()
    env["PGPASSWORD"] = "localweek"
    r = subprocess.run(
        [
            "pg_restore", "-h", "127.0.0.1", "-p", "55432", "-U", "postgres",
            "-d", "exchange_bot", "--no-owner", "--no-privileges", str(dump),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode not in (0, 1):
        sys.stderr.write(r.stderr[-4000:])
        raise SystemExit(f"pg_restore failed: {r.returncode}")
    return LOCAL_DSN


def stop_restore() -> None:
    subprocess.run(["podman", "rm", "-f", CONTAINER], check=False, capture_output=True)


def main() -> None:
    dsn = os.environ.get("FOCUSPAY_DEV_DUMP_DSN", "").strip()
    dump = Path(os.environ.get("FOCUSPAY_DEV_DUMP_PATH", str(DEFAULT_DUMP)))
    started = False
    if not dsn:
        if not dump.is_file():
            raise SystemExit(f"dump not found: {dump} (set FOCUSPAY_DEV_DUMP_PATH or FOCUSPAY_DEV_DUMP_DSN)")
        print(f"starting postgres + restore {dump}", flush=True)
        dsn = start_restore(dump)
        started = True
    try:
        parts = parse_dsn(dsn)
        conn = psycopg2.connect(**parts)
        conn.set_session(readonly=True, autocommit=True)
        blob = extract_admin(conn)
        conn.close()
        snap: dict[str, Any] = {}
        if SNAP.exists():
            try:
                snap = json.loads(SNAP.read_text())
            except json.JSONDecodeError:
                snap = {}
        snap["source"] = blob["source"]
        snap["pulled_at"] = blob["pulled_at"]
        snap["dump_week_from"] = blob["dump_week_from"]
        snap["dump_week_to"] = blob["dump_week_to"]
        admin = snap.setdefault("admin", {})
        admin.update(blob["admin"])
        SNAP.write_text(json.dumps(snap, ensure_ascii=False, default=json_default))
        os.chmod(SNAP, 0o600)
        orders = blob["admin"]["orders"]["orders"]
        users = blob["admin"]["users"]
        partners = blob["admin"]["referral_partners"]["partners"]
        print(
            f"wrote {SNAP}  orders={len(orders)} users={len(users)} partners={len(partners)} "
            f"size={SNAP.stat().st_size}",
            flush=True,
        )
    finally:
        if started:
            stop_restore()


if __name__ == "__main__":
    main()

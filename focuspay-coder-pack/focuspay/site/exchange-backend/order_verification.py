"""Read-only order verification payload for the admin order card.

Does not write payment_snapshot or call bot review helpers that persist.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("order_verification")

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
PDF_EXTS = {".pdf"}

LEVEL_OK = "OK"
LEVEL_WATCH = "СМОТРЕТЬ"
LEVEL_STRICT = "ДОСКОНАЛЬНО"

DANGER_KEYS = frozenset(
    {
        "wallet_reuse",
        "pdf_hash_reuse",
        "ip_reuse",
        "fingerprint_reuse",
        "pdf_stale_creation",
        "pdf_amount_mismatch",
    }
)
OK_KEYS = frozenset(
    {
        "paid_history",
        "has_referral",
        "crypto_input",
        "pdf_bankish",
    }
)

RISK_LABELS: dict[str, dict[str, str]] = {
    "wallet_reuse": {"label": "Кошелёк уже использовался другим клиентом", "severity": "danger"},
    "ip_reuse": {"label": "IP совпал с другим аккаунтом", "severity": "danger"},
    "fingerprint_reuse": {"label": "Отпечаток устройства уже встречался", "severity": "danger"},
    "fingerprint_common": {"label": "Общий отпечаток модели (типично для iPhone в Telegram)", "severity": "warn"},
    "pdf_hash_reuse": {"label": "Тот же файл чека уже был у другого клиента", "severity": "danger"},
    "pdf_stale_creation": {"label": "PDF создан раньше выдачи реквизитов", "severity": "danger"},
    "pdf_amount_missing": {"label": "Сумма заявки не найдена в тексте PDF", "severity": "warn"},
    "pdf_amount_mismatch": {"label": "Сумма в PDF не совпадает с заявкой", "severity": "danger"},
    "pdf_watch_producer": {"label": "Необычный генератор PDF — сверьте вручную", "severity": "warn"},
    "pdf_consumer_producer": {"label": "PDF похож на редактор/печать, не на выгрузку банка", "severity": "warn"},
    "pdf_a4_combo": {"label": "Формат A4 и необычный генератор — чаще макет", "severity": "warn"},
    "pdf_bankish": {"label": "PDF похож на банковскую выгрузку", "severity": "ok"},
    "pdf_date_skew": {"label": "Дата создания PDF далеко от заявки", "severity": "warn"},
    "fast_pdf_upload": {"label": "Чек прислали слишком быстро для живой оплаты", "severity": "warn"},
    "no_username": {"label": "Нет @username", "severity": "warn"},
    "no_avatar": {"label": "Нет аватарки", "severity": "warn"},
    "weak_name": {"label": "Слабое имя профиля", "severity": "warn"},
    "fresh_in_bot": {"label": "Свежий аккаунт в боте (<24ч)", "severity": "warn"},
    "username_changed": {"label": "Менял @username", "severity": "warn"},
    "no_premium": {"label": "Нет Telegram Premium", "severity": "warn"},
    "tg_account_new_7d": {"label": "TG-аккаунт похож на новый (до 7 дней)", "severity": "warn"},
    "tg_account_new_30d": {"label": "TG-аккаунт относительно новый (до 30 дней)", "severity": "warn"},
    "no_referral": {"label": "Нет реферала/промо", "severity": "warn"},
    "has_referral": {"label": "Есть реферал/промо", "severity": "ok"},
    "round_rub": {"label": "Круглая сумма в рублях", "severity": "warn"},
    "crypto_input": {"label": "Сумма введена в крипте", "severity": "ok"},
    "paid_history": {"label": "Уже были оплаченные сделки", "severity": "ok"},
}

PDF_FLAG_LABELS: dict[str, dict[str, str]] = {
    "pdf_a4_page": {"label": "Страница PDF формата A4", "severity": "warn"},
    "pdf_chrome_skia": {"label": "PDF из браузера/печати", "severity": "warn"},
    "pdf_bankish_producer": {"label": "Генератор PDF похож на банковский", "severity": "ok"},
}


def parse_snapshot(raw: Any) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    s = str(raw).strip()
    if not s:
        return None
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    s = s.replace("Z", "+00:00")
    if re.search(r"[+-]\d{2}$", s):
        s = f"{s}:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def as_iso(raw: Any) -> str | None:
    dt = parse_dt(raw)
    if dt is not None:
        return dt.isoformat()
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def receipt_required_type(row: dict) -> int | None:
    raw = row.get("required_receipt_type")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def receipt_kind(row: dict) -> str | None:
    filename = Path(str(row.get("receipt_file") or "")).name
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix in PDF_EXTS:
        return "pdf"
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix:
        return "other"
    rtype = receipt_required_type(row)
    if rtype == 2:
        return "pdf"
    if rtype == 3:
        return "video"
    return None


def _upload_sec(snap: dict) -> int | None:
    requested = parse_dt(
        snap.get("requisites_revealed_at")
        or snap.get("requisites_issued_at")
        or snap.get("receipt_requested_at")
    )
    submitted = parse_dt(
        snap.get("receipt_ops_submitted_at") or snap.get("receipt_submitted_at")
    )
    if requested is None or submitted is None:
        return None
    try:
        return max(0, int((submitted - requested).total_seconds()))
    except Exception:
        return None


def receipt_info(row: dict) -> dict:
    snap = parse_snapshot(row.get("payment_snapshot"))
    filename = Path(str(row.get("receipt_file") or "")).name or None
    meta_raw = snap.get("receipt_pdf_meta") if isinstance(snap.get("receipt_pdf_meta"), dict) else {}
    pdf_meta = None
    if meta_raw:
        flags = meta_raw.get("flags")
        pdf_meta = {
            "producer": meta_raw.get("producer"),
            "creator": meta_raw.get("creator"),
            "creation_date": meta_raw.get("creation_date_iso") or meta_raw.get("creation_date"),
            "page_kind": meta_raw.get("page_kind"),
            "size": meta_raw.get("size"),
            "amount_present": meta_raw.get("amount_present"),
            "flags": list(flags) if isinstance(flags, (list, tuple)) else [],
        }
    sha = snap.get("receipt_sha256") or meta_raw.get("sha256")
    requested = snap.get("receipt_requested_at")
    submitted = snap.get("receipt_ops_submitted_at") or snap.get("receipt_submitted_at")
    return {
        "has": bool(filename),
        "kind": receipt_kind(row),
        "filename": filename,
        "requested_at": as_iso(requested),
        "submitted_at": as_iso(submitted),
        "upload_sec": _upload_sec(snap),
        "sha256": str(sha).strip().lower() if sha else None,
        "pdf_meta": pdf_meta,
        "ops_pending": bool(snap.get("receipt_ops_pending")),
    }


def risk_level_from_score(score: int) -> str:
    _ensure_bot_path()
    try:
        from services.buyer_risk import risk_level_from_score as bot_level

        return str(bot_level(int(score)))
    except Exception:
        if score >= 5:
            return LEVEL_STRICT
        if score >= 2:
            return LEVEL_WATCH
        return LEVEL_OK


def severity_for(key: str, points: int) -> str:
    preset = (RISK_LABELS.get(key) or PDF_FLAG_LABELS.get(key) or {}).get("severity")
    if key in OK_KEYS or points < 0:
        return "ok"
    if key in DANGER_KEYS or points >= 3:
        return "danger"
    if points > 0:
        return "warn"
    return preset or "ok"


def risk_item(key: str, points: int) -> dict:
    meta = RISK_LABELS.get(key) or PDF_FLAG_LABELS.get(key) or {}
    return {
        "key": key,
        "label": meta.get("label") or key,
        "severity": severity_for(key, int(points)),
        "points": int(points),
    }


def risk_from_snapshot(snap: dict | None) -> dict:
    data = snap if isinstance(snap, dict) else {}
    raw = data.get("risk_breakdown") or {}
    breakdown: dict[str, int] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            try:
                breakdown[str(key)] = int(val)
            except (TypeError, ValueError):
                continue
    score = int(sum(breakdown.values())) if breakdown else 0
    items = [risk_item(k, v) for k, v in breakdown.items()]
    items.sort(key=lambda x: ({"danger": 0, "warn": 1, "ok": 2}.get(x["severity"], 9), -abs(int(x["points"]))))
    return {
        "score": score,
        "level": risk_level_from_score(score) if breakdown else None,
        "items": items,
        "breakdown": breakdown,
    }


def client_checks(bot_user: dict | None) -> dict:
    u = bot_user or {}
    return {
        "account_review_status": u.get("account_review_status") or "none",
        "account_review_reason": u.get("account_review_reason"),
        "device_review_status": u.get("device_review_status") or "none",
        "device_review_reason": u.get("device_review_reason"),
        "is_banned": bool(u.get("is_banned")),
        "ban_type": u.get("ban_type"),
        "ban_reason": u.get("ban_reason"),
        "paid_count": int(u["paid_count"]) if u.get("paid_count") is not None else None,
    }


def _short_fp(value: Any) -> str | None:
    s = str(value or "").strip()
    if not s:
        return None
    return s[:12]


def device_info(snap: dict | None, signal: dict | None = None) -> dict:
    data = snap if isinstance(snap, dict) else {}
    sig = signal if isinstance(signal, dict) else {}
    nested = data.get("device_signal") if isinstance(data.get("device_signal"), dict) else {}
    ip = sig.get("ip") or nested.get("ip") or data.get("device_ip")
    if ip is not None:
        ip = str(ip).strip()
        if "/" in ip:
            ip = ip.split("/", 1)[0]
        ip = ip or None
    fp = sig.get("fingerprint") or nested.get("fingerprint")
    return {
        "ip": ip,
        "fingerprint_short": _short_fp(fp),
        "platform": sig.get("platform") or nested.get("platform"),
        "screen": sig.get("screen") or nested.get("screen"),
        "timezone": sig.get("timezone") or nested.get("timezone"),
        "fp_reuse": bool(data.get("device_fp_reuse")),
        "fp_common": bool(data.get("device_fp_common")),
        "fp_user_count": data.get("device_fp_user_count") or data.get("device_reuse_count"),
        "ip_reuse": bool(data.get("device_ip_reuse")),
    }


def timeline(row: dict, snap: dict | None = None) -> list[dict]:
    data = snap if isinstance(snap, dict) else parse_snapshot(row.get("payment_snapshot"))
    events = [
        ("created_at", "Создана", row.get("created_at")),
        (
            "requisites_issued_at",
            "Реквизиты выданы",
            data.get("requisites_issued_at") or data.get("requisites_revealed_at"),
        ),
        ("receipt_requested_at", "Чек запрошен", data.get("receipt_requested_at")),
        (
            "receipt_submitted_at",
            "Чек получен",
            data.get("receipt_ops_submitted_at") or data.get("receipt_submitted_at"),
        ),
        ("payout_confirmed_at", "Выплата подтверждена", row.get("payout_confirmed_at")),
        ("expires_at", "Истекает", row.get("expires_at")),
    ]
    out: list[dict] = []
    for key, label, raw in events:
        at = as_iso(raw)
        if not at:
            continue
        out.append({"key": key, "label": label, "at": at})
    return out


def normalize_reuse(rows: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(rows, list):
        return out
    for raw in rows[:8]:
        if not isinstance(raw, dict):
            continue
        uname = str(raw.get("username") or "").strip().lstrip("@")
        uid = raw.get("user_id")
        try:
            uid = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            uid = None
        out.append(
            {
                "user_id": uid,
                "username": f"@{uname}" if uname else None,
                "order_id": str(raw.get("order_id") or "") or None,
                "status": str(raw.get("status") or "") or None,
            }
        )
    return out


def empty_reuse(*, available: bool = False) -> dict:
    return {
        "wallet": [],
        "ip": [],
        "fingerprint": [],
        "receipt_hash": [],
        "available": available,
    }


def reuse_from_snapshot(snap: dict | None) -> dict:
    data = snap if isinstance(snap, dict) else {}
    out = empty_reuse(available=False)
    out["ip"] = normalize_reuse(data.get("device_ip_matches"))
    out["fingerprint"] = normalize_reuse(data.get("device_fp_matches"))
    return out


def build_checks(
    *,
    risk: dict,
    client: dict,
    receipt: dict,
    reuse: dict | None = None,
) -> list[dict]:
    items: list[dict] = list(risk.get("items") or [])
    seen = {str(i.get("key")) for i in items}
    flags = list(((receipt.get("pdf_meta") or {}).get("flags")) or [])
    for flag in flags:
        key = str(flag)
        if key in seen:
            continue
        seen.add(key)
        meta = RISK_LABELS.get(key) or PDF_FLAG_LABELS.get(key)
        items.append(
            {
                "key": key,
                "label": (meta or {}).get("label") or key,
                "severity": (meta or {}).get("severity") or "warn",
                "points": 0,
            }
        )
    if client.get("is_banned"):
        items.append(
            {
                "key": "banned",
                "label": f"Клиент заблокирован ({client.get('ban_type') or 'hard'})",
                "severity": "danger",
                "detail": client.get("ban_reason"),
            }
        )
    acc = str(client.get("account_review_status") or "none")
    if acc not in ("", "none"):
        sev = "danger" if acc == "rejected" else ("ok" if acc == "approved" else "warn")
        items.append(
            {
                "key": "account_review",
                "label": f"Проверка профиля: {acc}",
                "severity": sev,
                "detail": client.get("account_review_reason"),
            }
        )
    dev = str(client.get("device_review_status") or "none")
    if dev not in ("", "none"):
        sev = "danger" if dev == "rejected" else ("ok" if dev == "approved" else "warn")
        items.append(
            {
                "key": "device_review",
                "label": f"Проверка устройства: {dev}",
                "severity": sev,
                "detail": client.get("device_review_reason"),
            }
        )
    if receipt.get("ops_pending"):
        items.append(
            {
                "key": "receipt_ops_pending",
                "label": "Чек на ручной проверке ops",
                "severity": "warn",
            }
        )
    reuse = reuse or empty_reuse()
    reuse_map = (
        ("wallet_reuse_hits", "Кошелёк совпал с другими заявками", reuse.get("wallet"), "danger"),
        ("ip_reuse_hits", "IP совпал с другими аккаунтами", reuse.get("ip"), "danger"),
        ("fp_reuse_hits", "Отпечаток совпал с другими аккаунтами", reuse.get("fingerprint"), "warn"),
        ("receipt_hash_hits", "Тот же файл чека уже был", reuse.get("receipt_hash"), "danger"),
    )
    for key, label, hits, sev in reuse_map:
        if not hits:
            continue
        detail = ", ".join(
            filter(
                None,
                [
                    (h.get("username") or (f"id {h.get('user_id')}" if h.get("user_id") else None) or "")
                    + (f" / {h.get('order_id')}" if h.get("order_id") else "")
                    for h in hits[:5]
                ],
            )
        )
        items.append({"key": key, "label": label, "severity": sev, "detail": detail or None})
    order = {"danger": 0, "warn": 1, "ok": 2}
    items.sort(key=lambda x: (order.get(str(x.get("severity")), 9), str(x.get("key"))))
    return items


def _ensure_bot_path() -> str:
    root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    if root not in sys.path:
        sys.path.append(root)
    return root


def _bot_db():
    _ensure_bot_path()
    from services import db as bot_db

    return bot_db


def _client_ip(row: dict, signal: dict | None) -> str | None:
    if signal and signal.get("ip"):
        ip = str(signal.get("ip")).strip()
        return ip.split("/", 1)[0] if ip else None
    raw = row.get("client_ip")
    if raw is None:
        return None
    ip = str(raw).strip()
    if "/" in ip:
        ip = ip.split("/", 1)[0]
    return ip or None


async def fetch_device_signal(order_id: str) -> dict | None:
    oid = (order_id or "").strip()
    if not oid:
        return None
    try:
        db = _bot_db()
        return await db.get_latest_device_signal_for_order(oid)
    except Exception as e:
        logger.debug("device signal unavailable: %s", e)
        return None


async def fetch_paid_count(user_id: int | None) -> int | None:
    if not user_id:
        return None
    try:
        db = _bot_db()
        stats = await db.get_buyer_ops_stats(int(user_id))
        return int((stats or {}).get("paid_count") or 0)
    except Exception as e:
        logger.debug("paid_count unavailable: %s", e)
        return None


async def _safe_reuse(coro, default):
    try:
        return await coro
    except Exception as e:
        logger.debug("reuse lookup failed: %s", e)
        return default


async def fetch_live_reuse(row: dict, snap: dict, signal: dict | None) -> dict:
    out = reuse_from_snapshot(snap)
    try:
        db = _bot_db()
    except Exception as e:
        logger.debug("bot reuse helpers unavailable: %s", e)
        return out

    uid = int(row.get("user_id") or 0)
    oid = str(row.get("order_id") or "")
    wallet = (row.get("wallet_address") or "").strip() or (row.get("requisites") or "").strip()
    ip = _client_ip(row, signal)
    fp = ""
    if signal and signal.get("fingerprint"):
        fp = str(signal.get("fingerprint") or "").strip().lower()
    sha = str((snap or {}).get("receipt_sha256") or "").strip().lower()
    if not sha:
        meta = snap.get("receipt_pdf_meta") if isinstance(snap.get("receipt_pdf_meta"), dict) else {}
        sha = str(meta.get("sha256") or "").strip().lower()

    wallet_rows = []
    ip_rows = []
    fp_rows = []
    hash_rows = []
    if wallet and uid:
        wallet_rows = await _safe_reuse(db.find_wallet_reuse(wallet, uid), [])
    if ip and uid:
        ip_rows = await _safe_reuse(db.find_ip_reuse(ip, uid), [])
    if fp and uid:
        fp_rows = await _safe_reuse(db.find_fingerprint_reuse(fp, uid), [])
    if sha:
        hash_rows = await _safe_reuse(
            db.find_receipt_sha256_reuse(sha, exclude_order_id=oid or None),
            [],
        )

    out["available"] = True
    if wallet_rows:
        out["wallet"] = normalize_reuse(wallet_rows)
    if ip_rows:
        out["ip"] = normalize_reuse(ip_rows)
    if fp_rows:
        out["fingerprint"] = normalize_reuse(fp_rows)
    if hash_rows:
        out["receipt_hash"] = normalize_reuse(hash_rows)
    return out


async def fetch_bot_user_reviews(conn, user_id: int | None) -> dict:
    if not user_id:
        return {}
    sql_full = """
        SELECT account_review_status, account_review_reason,
               device_review_status, device_review_reason,
               is_banned, ban_type, ban_reason
        FROM bot_users WHERE user_id = $1
    """
    sql_min = """
        SELECT account_review_status, account_review_reason,
               is_banned, ban_type, ban_reason
        FROM bot_users WHERE user_id = $1
    """
    try:
        async with conn.transaction():
            row = await conn.fetchrow(sql_full, int(user_id))
        return dict(row) if row else {}
    except Exception:
        logger.debug("bot_users full review columns unavailable", exc_info=True)
    try:
        async with conn.transaction():
            row = await conn.fetchrow(sql_min, int(user_id))
        return dict(row) if row else {}
    except Exception as e:
        logger.debug("bot_users review columns unavailable: %s", e)
        return {}


async def assemble_order_verification(
    row: dict,
    *,
    bot_user: dict | None = None,
    payout_audit: dict | None = None,
) -> dict:
    snap = parse_snapshot(row.get("payment_snapshot"))
    signal = await fetch_device_signal(str(row.get("order_id") or ""))
    reuse = await fetch_live_reuse(row, snap, signal)
    receipt = receipt_info(row)
    risk = risk_from_snapshot(snap)
    client = client_checks(bot_user)
    paid = await fetch_paid_count(row.get("user_id"))
    if paid is not None:
        client["paid_count"] = paid
    nested_signal = signal or (snap.get("device_signal") if isinstance(snap.get("device_signal"), dict) else None)
    device = device_info(snap, nested_signal)
    if device.get("fp_user_count") in (None, 0) and nested_signal and nested_signal.get("fingerprint"):
        try:
            n = await _bot_db().count_fingerprint_users(str(nested_signal["fingerprint"]))
            if n:
                device["fp_user_count"] = n
        except Exception:
            logger.debug("fingerprint user count skipped", exc_info=True)
    checks = build_checks(risk=risk, client=client, receipt=receipt, reuse=reuse)
    return {
        "receipt": receipt,
        "risk": risk,
        "checks": checks,
        "client": client,
        "device": device,
        "reuse": reuse,
        "timeline": timeline(row, snap),
        "payout_audit": payout_audit,
    }

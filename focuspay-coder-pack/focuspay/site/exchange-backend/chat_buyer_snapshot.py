"""Краткий срез покупателя для списка чатов оператора."""
from __future__ import annotations

from bot_user_avatars import bot_user_avatar_public_url

ACTIVE_EXCLUDE = ("PAID", "FAILED", "CANCELED", "EXPIRED")


def _display_name(username: str | None, first_name: str | None, user_id: int | None) -> str:
    if first_name and str(first_name).strip():
        return str(first_name).strip()
    if username and str(username).strip():
        u = str(username).strip().lstrip("@")
        return f"@{u}"
    if user_id:
        return f"ID {user_id}"
    return "Клиент"


async def buyer_snapshot(conn, telegram_user_id: int | None) -> dict | None:
    if not telegram_user_id:
        return None
    row = await conn.fetchrow(
        """
        SELECT
            bu.user_id,
            bu.username,
            bu.first_name,
            bu.first_seen_at,
            bu.last_seen_at,
            (SELECT COUNT(*)::int FROM orders o
             WHERE o.user_id = bu.user_id) AS total_orders,
            (SELECT COUNT(*)::int FROM orders o
             WHERE o.user_id = bu.user_id
               AND o.status IN ('PAID', 'COMPLETED')) AS paid_orders,
            (SELECT COALESCE(SUM(o.fiat_amount), 0)::float FROM orders o
             WHERE o.user_id = bu.user_id
               AND o.status IN ('PAID', 'COMPLETED')) AS turnover_rub,
            (SELECT o.order_id FROM orders o
             WHERE o.user_id = bu.user_id
               AND o.status NOT IN ('PAID', 'FAILED', 'CANCELED', 'EXPIRED')
             ORDER BY o.created_at DESC LIMIT 1) AS active_order_id,
            (SELECT o.status FROM orders o
             WHERE o.user_id = bu.user_id
               AND o.status NOT IN ('PAID', 'FAILED', 'CANCELED', 'EXPIRED')
             ORDER BY o.created_at DESC LIMIT 1) AS active_order_status
        FROM bot_users bu
        WHERE bu.user_id = $1
        """,
        telegram_user_id,
    )
    uid = int(telegram_user_id)
    if not row:
        return {
            "user_id": uid,
            "username": None,
            "first_name": None,
            "display_name": f"TG {uid}",
            "avatar_url": bot_user_avatar_public_url(uid),
            "total_orders": 0,
            "paid_orders": 0,
            "turnover_rub": 0.0,
            "active_order_id": None,
            "active_order_status": None,
            "in_bot": False,
        }
    return {
        "user_id": uid,
        "username": row.get("username"),
        "first_name": row.get("first_name"),
        "display_name": _display_name(
            row.get("username"), row.get("first_name"), uid
        ),
        "avatar_url": bot_user_avatar_public_url(uid),
        "first_seen_at": row["first_seen_at"].isoformat()
        if row.get("first_seen_at")
        else None,
        "last_seen_at": row["last_seen_at"].isoformat()
        if row.get("last_seen_at")
        else None,
        "total_orders": int(row.get("total_orders") or 0),
        "paid_orders": int(row.get("paid_orders") or 0),
        "turnover_rub": float(row.get("turnover_rub") or 0),
        "active_order_id": row.get("active_order_id"),
        "active_order_status": row.get("active_order_status"),
        "in_bot": True,
    }


def guest_snapshot(session_token) -> dict:
    hint = ""
    if session_token:
        hint = str(session_token).replace("-", "")[:8]
    return {
        "guest": True,
        "display_name": "Гость на сайте",
        "session_hint": hint or None,
        "avatar_url": None,
        "total_orders": 0,
        "paid_orders": 0,
        "turnover_rub": 0.0,
    }

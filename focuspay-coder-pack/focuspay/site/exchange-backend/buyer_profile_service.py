"""Агрегированный профиль покупателя (Telegram user_id) для админки и оператора."""
from __future__ import annotations

from typing import Any, Literal

from bot_user_avatars import bot_user_avatar_public_url
from economics_snapshot import order_economics
from user_referral_db import fetch_user_referrer, get_referral_stats
from user_unified_balance import get_unified_balance_stats

Mode = Literal["admin", "operator"]

TERMINAL_STATUSES = ("PAID", "FAILED", "CANCELED", "EXPIRED")
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


def buyer_trust_level(paid_count: int) -> str:
    """Те же пороги, что Telegram /stat: 0 новый / ≤3 начинающий / ≤9 постоянный / ≤19 доверенный / VIP."""
    n = max(0, int(paid_count or 0))
    if n == 0:
        return "Новый"
    if n <= 3:
        return "Начинающий"
    if n <= 9:
        return "Постоянный"
    if n <= 19:
        return "Доверенный"
    return "VIP"


def compute_gross_profit_from_orders(orders: list[dict]) -> float:
    """Сумма order_service_profit по списку PAID-заявок (убытки тоже учитываются)."""
    total = 0.0
    for o in orders:
        total += order_economics(o, clamp=False)["service_profit_rub"]
    return round(total, 2)


def compute_net_profit_rub(
    gross_profit_rub: float,
    cashback_accrued_rub: float,
    referral_accrued_rub: float,
    review_bonus_rub: float,
) -> float:
    """Чистая прибыль по покупателю (как owner net: gross минус начисления)."""
    return round(
        float(gross_profit_rub or 0)
        - float(cashback_accrued_rub or 0)
        - float(referral_accrued_rub or 0)
        - float(review_bonus_rub or 0),
        2,
    )


def _iso(val) -> str | None:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _deal_out(row: dict | None) -> dict | None:
    if not row:
        return None
    r = dict(row)
    return {
        "order_id": r.get("order_id"),
        "direction": r.get("direction"),
        "crypto": r.get("crypto"),
        "fiat_amount": float(r.get("fiat_amount") or 0),
        "crypto_amount": float(r.get("crypto_amount") or 0),
        "status": r.get("status"),
        "status_label": STATUS_LABELS.get(r.get("status") or "", r.get("status")),
        "created_at": _iso(r.get("created_at")),
        "operator_id": r.get("operator_id"),
        "payout_tx_hash": r.get("payout_tx_hash"),
    }


def _order_row_out(row: dict, *, admin: bool) -> dict:
    r = dict(row)
    out: dict[str, Any] = {
        "order_id": r.get("order_id"),
        "user_id": r.get("user_id"),
        "status": r.get("status"),
        "status_label": STATUS_LABELS.get(r.get("status") or "", r.get("status")),
        "direction": r.get("direction"),
        "crypto": r.get("crypto"),
        "crypto_amount": float(r.get("crypto_amount") or 0),
        "fiat_amount": float(r.get("fiat_amount") or 0),
        "rate": float(r.get("rate") or 0) if r.get("rate") is not None else None,
        "requisites": r.get("requisites"),
        "wallet_address": r.get("wallet_address"),
        "operator_id": r.get("operator_id"),
        "payout_tx_hash": r.get("payout_tx_hash"),
        "cashback_applied_rub": float(r.get("cashback_applied_rub") or 0),
        "created_at": _iso(r.get("created_at")),
        "updated_at": _iso(r.get("updated_at")),
    }
    if admin:
        fee = r.get("card_fee_pct")
        out["card_fee_pct"] = float(fee) if fee is not None else None
        out["service_profit_rub"] = round(
            order_economics(r, clamp=False)["service_profit_rub"],
            2,
        )
    return out


def _ledger_row_out(row: dict) -> dict:
    r = dict(row)
    return {
        "id": r.get("id"),
        "type": r.get("type"),
        "amount_rub": float(r.get("amount_rub") or 0),
        "order_id": r.get("order_id"),
        "note": r.get("note"),
        "created_at": _iso(r.get("created_at")),
    }


async def ensure_buyer_exists(conn, user_id: int) -> dict:
    row = await conn.fetchrow(
        """SELECT user_id, username, first_name, first_seen_at, last_seen_at,
                  is_banned, ban_type, ban_reason, banned_at,
                  COALESCE(account_review_status, 'none') AS account_review_status,
                  previous_username
           FROM bot_users WHERE user_id = $1""",
        user_id,
    )
    if not row:
        return {}
    return dict(row)


async def build_buyer_profile(
    conn,
    user_id: int,
    *,
    mode: Mode = "admin",
    include_finance: bool = False,
) -> dict | None:
    buyer = await ensure_buyer_exists(conn, user_id)
    if not buyer:
        return None

    is_admin = mode == "admin"
    recent_limit = 30 if is_admin else 15

    summary_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*)::int AS total_orders,
            COUNT(CASE WHEN status IN ('PAID','COMPLETED') THEN 1 END)::int AS paid_orders,
            COUNT(CASE WHEN status = 'PAID' THEN 1 END)::int AS completed_orders,
            COUNT(CASE WHEN status IN ('CANCELED','EXPIRED','FAILED') THEN 1 END)::int AS canceled_orders,
            COUNT(CASE WHEN status IN ('PAID','COMPLETED') AND direction = 'buy' THEN 1 END)::int AS buy_paid,
            COUNT(CASE WHEN status IN ('PAID','COMPLETED') AND direction = 'sell' THEN 1 END)::int AS sell_paid,
            COALESCE(SUM(CASE WHEN status IN ('PAID','COMPLETED') THEN fiat_amount END), 0)::float AS turnover_rub,
            COUNT(CASE WHEN direction = 'buy' AND merchant_order_id IS NOT NULL THEN 1 END)::int AS payfast_taken,
            COUNT(CASE WHEN direction = 'buy' AND merchant_order_id IS NOT NULL AND status = 'PAID' THEN 1 END)::int AS payfast_paid,
            COUNT(CASE WHEN direction = 'buy' AND merchant_order_id IS NOT NULL AND status IN ('CANCELED','EXPIRED') THEN 1 END)::int AS payfast_failed,
            COUNT(CASE WHEN direction = 'buy' AND status IN ('CANCELED','EXPIRED') THEN 1 END)::int AS buy_failed,
            MIN(created_at) AS first_order_at,
            MAX(CASE WHEN status IN ('PAID','COMPLETED') THEN created_at END) AS last_paid_at
        FROM orders WHERE user_id = $1
        """,
        user_id,
    )

    last_deal_row = await conn.fetchrow(
        "SELECT * FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
        user_id,
    )
    active_row = await conn.fetchrow(
        """
        SELECT * FROM orders
        WHERE user_id = $1 AND status NOT IN ('PAID', 'FAILED', 'CANCELED', 'EXPIRED')
        ORDER BY created_at DESC LIMIT 1
        """,
        user_id,
    )

    recent_rows = await conn.fetch(
        """
        SELECT * FROM orders WHERE user_id = $1
        ORDER BY created_at DESC LIMIT $2
        """,
        user_id,
        recent_limit,
    )

    referrer = await fetch_user_referrer(conn, user_id)

    promo_row = await conn.fetchrow(
        "SELECT promo_code, assigned_at FROM promo_attributions WHERE user_id = $1",
        user_id,
    )

    ref_stats = await get_referral_stats(user_id)
    balance_stats = await get_unified_balance_stats(user_id)

    pf_paid = int(summary_row["payfast_paid"] or 0)
    pf_failed = int(summary_row["payfast_failed"] or 0)
    pf_taken = int(summary_row["payfast_taken"] or 0)
    pf_denom = pf_paid + pf_failed
    conversion_pct = round(100.0 * pf_paid / pf_denom, 1) if pf_denom > 0 else None
    buy_paid = int(summary_row["buy_paid"] or 0)
    buy_failed = int(summary_row["buy_failed"] or 0)
    buy_denom = buy_paid + buy_failed
    buy_conversion_pct = round(100.0 * buy_paid / buy_denom, 1) if buy_denom > 0 else None
    paid_orders = int(summary_row["paid_orders"] or 0)
    uname = (buyer.get("username") or "").strip()

    profile: dict[str, Any] = {
        "identity": {
            "user_id": buyer["user_id"],
            "username": buyer.get("username"),
            "first_name": buyer.get("first_name"),
            "first_seen_at": _iso(buyer.get("first_seen_at")),
            "last_seen_at": _iso(buyer.get("last_seen_at")),
            "avatar_url": bot_user_avatar_public_url(int(user_id)),
            "invited_by": referrer,
            "is_banned": bool(buyer.get("is_banned")),
            "ban_type": buyer.get("ban_type") or "hard",
            "ban_reason": buyer.get("ban_reason"),
            "banned_at": _iso(buyer.get("banned_at")),
            "has_username": bool(uname),
            "account_review_status": buyer.get("account_review_status") or "none",
        },
        "summary": {
            "total_orders": int(summary_row["total_orders"] or 0),
            "paid_orders": paid_orders,
            "completed_orders": int(summary_row["completed_orders"] or 0),
            "canceled_orders": int(summary_row["canceled_orders"] or 0),
            "buy_paid": buy_paid,
            "buy_failed": buy_failed,
            "buy_conversion_pct": buy_conversion_pct,
            "sell_paid": int(summary_row["sell_paid"] or 0),
            "turnover_rub": round(float(summary_row["turnover_rub"] or 0), 2),
            "payfast_taken": pf_taken,
            "payfast_paid": pf_paid,
            "payfast_failed": pf_failed,
            "conversion_pct": conversion_pct,
            "trust_level": buyer_trust_level(paid_orders),
            "first_order_at": _iso(summary_row["first_order_at"]),
            "last_paid_at": _iso(summary_row["last_paid_at"]),
        },
        "last_deal": _deal_out(dict(last_deal_row) if last_deal_row else None),
        "active_order": _deal_out(dict(active_row) if active_row else None),
        "balances": {
            "cashback_percent": balance_stats.get("percent"),
            "completed_exchanges": balance_stats.get("completed_exchanges"),
            "balance_rub": balance_stats.get("balance_rub"),
            "available_rub": balance_stats.get("available_rub"),
            "saved_rub": balance_stats.get("saved_rub"),
            "cashback_rub": balance_stats.get("cashback_rub"),
            "referral_rub": balance_stats.get("referral_rub"),
            "use_cashback_on_next": balance_stats.get("use_on_next"),
        },
        "referral": {
            "referred_count": ref_stats.get("referred_count", 0),
            "paid_orders_count": ref_stats.get("paid_orders_count", 0),
            "referral_balance_rub": round(float(ref_stats.get("balance_rub") or 0), 2),
            "total_accrual_rub": round(float(ref_stats.get("total_accrual_rub") or 0), 2),
            "referrer": None,
        },
        "promo": None,
        "recent_orders": [
            _order_row_out(dict(r), admin=is_admin) for r in recent_rows
        ],
        "finance": None,
        "ledgers": None,
    }

    if referrer:
        profile["referral"]["referrer"] = referrer

    if promo_row:
        profile["promo"] = {
            "promo_code": promo_row["promo_code"],
            "assigned_at": _iso(promo_row.get("assigned_at")),
        }

    if include_finance:
        paid_rows = await conn.fetch(
            """
            SELECT direction, crypto, fiat_amount, crypto_amount, rate,
                   cashback_applied_rub, card_fee_pct, economics_snapshot
            FROM orders
            WHERE user_id = $1 AND status = 'PAID'
            """,
            user_id,
        )
        paid_list = [dict(r) for r in paid_rows]
        gross = compute_gross_profit_from_orders(paid_list)

        cashback_accrued = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM user_cashback_ledger
                WHERE user_id = $1 AND type = 'accrual'
                """,
                user_id,
            )
            or 0
        )
        referral_accrued = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(l.amount_rub), 0)::float
                FROM user_referral_ledger l
                JOIN orders o ON o.order_id = l.order_id
                WHERE o.user_id = $1 AND l.type = 'accrual'
                """,
                user_id,
            )
            or 0
        )
        review_bonus = float(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM review_bonus_claims WHERE user_id = $1
                """,
                user_id,
            )
            or 0
        )

        profile["finance"] = {
            "gross_profit_rub": gross,
            "cashback_accrued_rub": round(cashback_accrued, 2),
            "referral_accrued_rub": round(referral_accrued, 2),
            "review_bonus_rub": round(review_bonus, 2),
            "net_profit_rub": compute_net_profit_rub(
                gross, cashback_accrued, referral_accrued, review_bonus
            ),
        }

        cb_ledger = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM user_cashback_ledger
            WHERE user_id = $1
            ORDER BY created_at DESC LIMIT 30
            """,
            user_id,
        )
        ref_ledger = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM user_referral_ledger
            WHERE order_id IN (SELECT order_id FROM orders WHERE user_id = $1)
            ORDER BY created_at DESC LIMIT 20
            """,
            user_id,
        )
        profile["ledgers"] = {
            "cashback": [_ledger_row_out(dict(r)) for r in cb_ledger],
            "referral": [_ledger_row_out(dict(r)) for r in ref_ledger],
        }
    elif is_admin:
        cb_ledger = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM user_cashback_ledger
            WHERE user_id = $1
            ORDER BY created_at DESC LIMIT 30
            """,
            user_id,
        )
        ref_ledger = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM user_referral_ledger
            WHERE order_id IN (SELECT order_id FROM orders WHERE user_id = $1)
            ORDER BY created_at DESC LIMIT 20
            """,
            user_id,
        )
        profile["ledgers"] = {
            "cashback": [_ledger_row_out(dict(r)) for r in cb_ledger],
            "referral": [_ledger_row_out(dict(r)) for r in ref_ledger],
        }

    review_rows = await conn.fetch(
        """
        SELECT id, order_id, tier, status, bonus_rub, bonus_credited,
               review_text, created_at, moderated_at, channel_text_message_id
        FROM review_submissions
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 20
        """,
        user_id,
    )
    profile["reviews"] = [
        {
            "id": int(r["id"]),
            "order_id": r.get("order_id"),
            "tier": r.get("tier"),
            "status": r.get("status"),
            "bonus_rub": float(r["bonus_rub"]) if r.get("bonus_rub") is not None else None,
            "bonus_credited": bool(r.get("bonus_credited")),
            "review_text": (r.get("review_text") or "")[:300],
            "created_at": _iso(r.get("created_at")),
            "moderated_at": _iso(r.get("moderated_at")),
            "channel_text_message_id": r.get("channel_text_message_id"),
        }
        for r in review_rows
    ]

    return profile

"""Купон автора контента: скидка на обмен, один код на первое видео.

Цифры фиксированы на сервере. Партнёрский бот не может их ослабить.
"""
from __future__ import annotations

import re

from referral_links import generate_ref_token

AUTHOR_DISCOUNT_RUB = 200.0
AUTHOR_MAX_ACTIVATIONS = 100
AUTHOR_MIN_ORDER_RUB = 3000.0
_CODE_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_ISSUED = frozenset({"first_video", "extra"})


class AuthorPromoError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_author_code(raw: str) -> str:
    code = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    if not _CODE_RE.match(code):
        raise AuthorPromoError("Некорректный промокод")
    return code


def author_coupon_block_reason(
    author_telegram_id,
    user_id: int,
    *,
    has_completed_order: bool,
) -> str | None:
    """Почему этот пользователь не может активировать купон автора. None — можно."""
    if author_telegram_id is None:
        return None
    if int(author_telegram_id) == int(user_id):
        return "Нельзя использовать свой промокод"
    if has_completed_order:
        return "Промокод только для первого обмена"
    return None


def plan_issue(
    code: str,
    author_telegram_id: int,
    issued_for: str,
    existing_by_code: dict | None,
    existing_first: dict | None,
) -> dict:
    """create | return | error. Чистая логика, без БД."""
    if existing_by_code:
        owner = existing_by_code.get("author_telegram_id")
        if owner is None or int(owner) != int(author_telegram_id):
            return {"action": "error", "message": "Код уже занят"}
        return {"action": "return", "row": existing_by_code}
    if (
        issued_for == "first_video"
        and existing_first
        and str(existing_first.get("code") or "").upper() != code
    ):
        return {"action": "return", "row": existing_first}
    return {
        "action": "create",
        "code": code,
        "author_telegram_id": int(author_telegram_id),
        "issued_for": issued_for,
        "discount_rub": AUTHOR_DISCOUNT_RUB,
        "max_activations": AUTHOR_MAX_ACTIVATIONS,
        "min_order_rub": AUTHOR_MIN_ORDER_RUB,
    }


def _campaign_name(author_name: str | None, author_telegram_id: int, issued_for: str) -> str:
    title = (author_name or "").strip()[:80] or f"Автор {int(author_telegram_id)}"
    if issued_for == "first_video":
        title = f"{title} · первое видео"
    return title[:120]


def _public(row: dict, *, created: bool) -> dict:
    return {
        "ok": True,
        "created": created,
        "code": row["code"],
        "discount_rub": float(row.get("client_fixed_bonus_rub") or AUTHOR_DISCOUNT_RUB),
        "max_activations": int(row.get("max_activations") or AUTHOR_MAX_ACTIVATIONS),
        "min_order_rub": float(row.get("exchange_discount_min_order_rub") or AUTHOR_MIN_ORDER_RUB),
        "author_telegram_id": int(row["author_telegram_id"]) if row.get("author_telegram_id") else None,
        "author_video_id": row.get("author_video_id"),
        "issued_for": row.get("issued_for"),
        "is_active": bool(row.get("is_active", True)),
    }


_SELECT = """
    SELECT code, name, author_telegram_id, author_video_id, issued_for,
           client_fixed_bonus_rub, max_activations, exchange_discount_min_order_rub, is_active
    FROM promo_campaigns
"""


async def issue_author_promo(
    conn,
    *,
    code: str,
    author_telegram_id: int,
    video_id: int | None = None,
    issued_for: str = "first_video",
    author_name: str | None = None,
) -> dict:
    code = normalize_author_code(code)
    if int(author_telegram_id) <= 0:
        raise AuthorPromoError("Нужен Telegram автора")
    issued_for = issued_for if issued_for in _ISSUED else "first_video"
    existing = await conn.fetchrow(f"{_SELECT} WHERE UPPER(code) = $1", code)
    existing_first = None
    if issued_for == "first_video":
        existing_first = await conn.fetchrow(
            f"{_SELECT} WHERE author_telegram_id = $1 AND issued_for = 'first_video' LIMIT 1",
            int(author_telegram_id),
        )
    plan = plan_issue(
        code,
        int(author_telegram_id),
        issued_for,
        dict(existing) if existing else None,
        dict(existing_first) if existing_first else None,
    )
    if plan["action"] == "error":
        raise AuthorPromoError(plan["message"], status=409)
    if plan["action"] == "return":
        return _public(plan["row"], created=False)

    import asyncpg

    name = _campaign_name(author_name, int(author_telegram_id), issued_for)
    for _ in range(4):
        ref_token = generate_ref_token()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO promo_campaigns (
                    code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
                    ref_token, campaign_kind, client_fixed_bonus_rub, max_activations,
                    exchange_discount_min_order_rub,
                    partner_tier_base_percent, partner_tier_step_percent, partner_tier_max_percent,
                    author_telegram_id, author_video_id, issued_for,
                    is_active, created_by, created_at, updated_at
                )
                VALUES (
                    $1, $2, 0, 0, 0,
                    $3, 'exchange_discount', $4, $5,
                    $6,
                    0, 0, 0,
                    $7, $8, $9,
                    TRUE, NULL, now(), now()
                )
                RETURNING code, name, author_telegram_id, author_video_id, issued_for,
                          client_fixed_bonus_rub, max_activations, exchange_discount_min_order_rub, is_active
                """,
                code,
                name,
                ref_token,
                AUTHOR_DISCOUNT_RUB,
                AUTHOR_MAX_ACTIVATIONS,
                AUTHOR_MIN_ORDER_RUB,
                int(author_telegram_id),
                video_id,
                issued_for,
            )
            return _public(dict(row), created=True)
        except asyncpg.UniqueViolationError:
            raced_code = await conn.fetchrow(f"{_SELECT} WHERE UPPER(code) = $1", code)
            raced_first = None
            if issued_for == "first_video":
                raced_first = await conn.fetchrow(
                    f"{_SELECT} WHERE author_telegram_id = $1 AND issued_for = 'first_video' LIMIT 1",
                    int(author_telegram_id),
                )
            again = plan_issue(
                code,
                int(author_telegram_id),
                issued_for,
                dict(raced_code) if raced_code else None,
                dict(raced_first) if raced_first else None,
            )
            if again["action"] == "return":
                return _public(again["row"], created=False)
            if again["action"] == "error":
                raise AuthorPromoError(again["message"], status=409) from None
            continue
    raise AuthorPromoError("Не удалось выдать промокод", status=500)


async def author_discount_order_stats(conn, promo_code: str) -> dict:
    row = await conn.fetchrow(
        """
        SELECT COUNT(o.id)::int AS cnt,
               COALESCE(SUM(o.fiat_amount), 0)::float AS fiat
        FROM orders o
        JOIN user_exchange_discounts d ON d.id = o.exchange_discount_id
        WHERE d.promo_code = $1
          AND o.status IN ('PAID', 'COMPLETED')
        """,
        promo_code,
    )
    return {
        "discount_orders_count": int(row["cnt"] or 0) if row else 0,
        "discount_fiat_sum": round(float(row["fiat"] or 0) if row else 0, 2),
    }

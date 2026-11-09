"""Ваучеры «скидка на обмен»: hold / apply / confirm / release."""
from __future__ import annotations

from decimal import Decimal

from services.db import get_pool
from services.promo_bonus import apply_fixed_rub_bonus


async def get_active_discounts(
    user_id: int, *, fiat_amount: float | None = None
) -> list[dict]:
    """Активные ваучеры. Если задан fiat_amount — только подходящие по
    минимальной сумме заказа (min_order_rub <= fiat_amount)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, promo_code, amount_rub, min_order_rub, expires_at, created_at
            FROM user_exchange_discounts
            WHERE user_id = $1 AND status = 'active'
              AND (expires_at IS NULL OR expires_at > now())
              AND ($2::numeric IS NULL OR min_order_rub <= $2::numeric)
            ORDER BY amount_rub DESC, id ASC
            """,
            user_id,
            fiat_amount,
        )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "promo_code": r["promo_code"],
                "amount_rub": float(r["amount_rub"]),
                "min_order_rub": float(r["min_order_rub"] or 0),
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return out


async def get_user_discounts_overview(user_id: int, *, limit: int = 20) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetch(
            """
            SELECT id, promo_code, amount_rub, min_order_rub, expires_at, created_at,
                   issued_by_operator_id
            FROM user_exchange_discounts
            WHERE user_id = $1 AND status = 'active'
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY amount_rub DESC, id ASC
            """,
            user_id,
        )
        history = await conn.fetch(
            """
            SELECT id, promo_code, amount_rub, min_order_rub, status, order_id,
                   created_at, used_at, issued_by_operator_id
            FROM user_exchange_discounts
            WHERE user_id = $1 AND status IN ('used', 'released')
            ORDER BY COALESCE(used_at, created_at) DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    def _row(r):
        return {
            "id": r["id"],
            "promo_code": r["promo_code"],
            "amount_rub": float(r["amount_rub"]),
            "min_order_rub": float(r["min_order_rub"] or 0),
            "status": r.get("status", "active"),
            "order_id": r.get("order_id"),
            "issued_by_operator_id": r.get("issued_by_operator_id"),
            "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "used_at": r["used_at"].isoformat() if r.get("used_at") else None,
        }

    return {
        "active": [_row(r) for r in active],
        "history": [_row(r) for r in history],
    }


async def apply_discount_with_conn(
    conn,
    discount_id: int,
    user_id: int,
    fiat_amount: float,
    crypto_amount: float,
    rate: float,
    crypto: str,
) -> tuple[float, float, float, int | None]:
    """Уменьшает fiat к оплате; возвращает (fiat_pay, crypto_out, applied, discount_id)."""
    row = await conn.fetchrow(
        """
        SELECT id, amount_rub, min_order_rub
        FROM user_exchange_discounts
        WHERE id = $1 AND user_id = $2 AND status = 'active'
          AND (expires_at IS NULL OR expires_at > now())
        FOR UPDATE
        """,
        discount_id,
        user_id,
    )
    if not row:
        return fiat_amount, crypto_amount, 0.0, None

    # Минимальная сумма заказа: ваучер не применяется к мелким заказам.
    if float(fiat_amount) < float(row["min_order_rub"] or 0):
        return fiat_amount, crypto_amount, 0.0, None

    max_apply = max(0.0, float(fiat_amount) - 1.0)
    applied = min(float(row["amount_rub"]), max_apply)
    if applied <= 0:
        return fiat_amount, crypto_amount, 0.0, None

    # Скидка снижает ТОЛЬКО сумму к оплате (3600 → 3100), крипта остаётся прежней
    # (клиент получает крипту за исходную стоимость по рынку). Курс/крипту не трогаем.
    _ = (rate, crypto)
    fiat_pay = float(fiat_amount) - applied
    return fiat_pay, float(crypto_amount), applied, int(row["id"])


async def hold_discount_for_order(
    conn,
    user_id: int,
    order_id: str,
    discount_id: int,
) -> bool:
    res = await conn.execute(
        """
        UPDATE user_exchange_discounts
        SET status = 'held', order_id = $3
        WHERE id = $1 AND user_id = $2 AND status = 'active'
        """,
        discount_id,
        user_id,
        order_id,
    )
    return res.endswith("1")


async def confirm_discount_for_order(order_id: str, *, conn=None) -> None:
    async def _run(c):
        await c.execute(
            """
            UPDATE user_exchange_discounts
            SET status = 'used', used_at = now()
            WHERE order_id = $1 AND status = 'held'
            """,
            order_id,
        )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        await _run(acquired)


async def release_discount_for_order(order_id: str, *, conn=None) -> None:
    async def _run(c):
        await c.execute(
            """
            UPDATE user_exchange_discounts
            SET status = 'active', order_id = NULL
            WHERE order_id = $1 AND status = 'held'
            """,
            order_id,
        )

    if conn is not None:
        await _run(conn)
        return
    pool = await get_pool()
    async with pool.acquire() as acquired:
        await _run(acquired)


async def preview_discount_application(
    discount_id: int,
    user_id: int,
    fiat_amount: float,
    crypto_amount: float,
    rate: float,
    crypto: str,
) -> tuple[float, float, float]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        fiat_pay, crypto_out, applied, _ = await apply_discount_with_conn(
            conn,
            discount_id,
            user_id,
            fiat_amount,
            crypto_amount,
            rate,
            crypto,
        )
    return fiat_pay, crypto_out, applied

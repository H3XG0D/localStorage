"""Активация промокодов: подарок на баланс или скидка на обмен."""
from __future__ import annotations

from author_promo import author_coupon_block_reason
from db import get_pool


class PromoRedeemError(Exception):
    pass


async def _validate_redemption(conn, campaign: dict, user_id: int) -> tuple[float, int]:
    amount = float(campaign["client_fixed_bonus_rub"] or 0)
    if amount <= 0:
        raise PromoRedeemError("Промокод без начисления")

    max_act = int(campaign["max_activations"] or 5)
    used_count = int(
        await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_gift_redemptions WHERE promo_code = $1",
            campaign["code"],
        )
        or 0
    )
    if used_count >= max_act:
        raise PromoRedeemError("Лимит активаций промокода исчерпан")

    already = await conn.fetchval(
        """
        SELECT 1 FROM promo_gift_redemptions
        WHERE promo_code = $1 AND user_id = $2
        """,
        campaign["code"],
        user_id,
    )
    if already:
        raise PromoRedeemError("Вы уже активировали этот промокод")

    return amount, used_count


async def redeem_promo_code(user_id: int, raw_code: str) -> dict:
    code = (raw_code or "").strip().upper()
    if not code:
        raise PromoRedeemError("Укажите промокод")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            campaign = await conn.fetchrow(
                """
                SELECT code, name, client_fixed_bonus_rub, campaign_kind, is_active,
                       max_activations, exchange_discount_min_order_rub, author_telegram_id
                FROM promo_campaigns
                WHERE UPPER(code) = $1
                FOR UPDATE
                """,
                code,
            )
            if not campaign or not campaign["is_active"]:
                raise PromoRedeemError("Промокод не найден или неактивен")

            kind = (campaign["campaign_kind"] or "").lower()
            if kind not in ("fixed_rub", "exchange_discount"):
                raise PromoRedeemError(
                    "Этот промокод нельзя активировать так — используйте партнёрскую ссылку"
                )

            if campaign["author_telegram_id"] is not None:
                has_paid = await conn.fetchval(
                    """
                    SELECT 1 FROM orders
                    WHERE user_id = $1 AND status IN ('PAID', 'COMPLETED')
                    LIMIT 1
                    """,
                    user_id,
                )
                blocked = author_coupon_block_reason(
                    campaign["author_telegram_id"],
                    user_id,
                    has_completed_order=bool(has_paid),
                )
                if blocked:
                    raise PromoRedeemError(blocked)

            amount, used_count = await _validate_redemption(conn, campaign, user_id)

            await conn.execute(
                """
                INSERT INTO promo_gift_redemptions (promo_code, user_id, amount_rub)
                VALUES ($1, $2, $3)
                """,
                campaign["code"],
                user_id,
                amount,
            )

            if kind == "fixed_rub":
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    user_id,
                    amount,
                    f"Промокод {campaign['code']}",
                )
            else:
                await conn.fetchrow(
                    """
                    INSERT INTO user_exchange_discounts (
                        user_id, promo_code, amount_rub, min_order_rub, status
                    )
                    VALUES ($1, $2, $3, $4, 'active')
                    RETURNING id
                    """,
                    user_id,
                    campaign["code"],
                    amount,
                    float(campaign["exchange_discount_min_order_rub"] or 0),
                )

            new_used = used_count + 1
            if new_used >= int(campaign["max_activations"] or 5):
                await conn.execute(
                    """
                    UPDATE promo_campaigns
                    SET is_active = FALSE, updated_at = now()
                    WHERE code = $1
                    """,
                    campaign["code"],
                )

    return {
        "code": campaign["code"],
        "name": campaign["name"],
        "amount_rub": round(amount, 2),
        "min_order_rub": round(float(campaign["exchange_discount_min_order_rub"] or 0), 2),
        "activations_used": used_count + 1,
        "max_activations": int(campaign["max_activations"] or 5),
        "campaign_kind": kind,
    }


async def redeem_gift_promo(user_id: int, raw_code: str) -> dict:
    result = await redeem_promo_code(user_id, raw_code)
    if result.get("campaign_kind") != "fixed_rub":
        raise PromoRedeemError("Это не подарочный промокод на баланс")
    return result

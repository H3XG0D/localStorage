"""Промо и баланс для обычных пользователей в боте."""
from services.db import get_pool, get_completed_orders_count


async def get_user_promo_status(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        gift = await conn.fetchrow(
            """
            SELECT pgr.promo_code, pgr.amount_rub, pc.name
            FROM promo_gift_redemptions pgr
            JOIN promo_campaigns pc ON pc.code = pgr.promo_code
            WHERE pgr.user_id = $1
            ORDER BY pgr.redeemed_at DESC
            LIMIT 1
            """,
            user_id,
        )
        attr = await conn.fetchrow(
            """
            SELECT pa.promo_code, pc.client_fixed_bonus_rub, pc.campaign_kind, pc.name
            FROM promo_attributions pa
            JOIN promo_campaigns pc ON pc.code = pa.promo_code AND pc.is_active = TRUE
            WHERE pa.user_id = $1
            """,
            user_id,
        )
        used = await conn.fetchrow(
            "SELECT order_id, bonus_fixed_rub FROM promo_bonus_usages WHERE user_id = $1",
            user_id,
        )
    fixed = float(attr["client_fixed_bonus_rub"]) if attr and attr["client_fixed_bonus_rub"] else None
    return {
        "has_gift": gift is not None,
        "gift_code": gift["promo_code"] if gift else None,
        "gift_amount_rub": float(gift["amount_rub"]) if gift else None,
        "has_attribution": attr is not None,
        "promo_code": attr["promo_code"] if attr else None,
        "promo_name": attr["name"] if attr else None,
        "fixed_bonus_rub": fixed,
        "bonus_used": used is not None,
        "bonus_used_order_id": used["order_id"] if used else None,
    }


async def format_user_balance_message(user_id: int) -> str:
    promo = await get_user_promo_status(user_id)
    completed = await get_completed_orders_count(user_id)

    lines = ["💳 <b>Мой баланс</b>\n"]

    if promo["has_gift"]:
        lines.append(
            f"🎁 Промокод <code>{promo['gift_code']}</code>: "
            f"зачислено <b>{promo['gift_amount_rub']:,.0f} ₽</b> на клиентский баланс."
            .replace(",", " ")
        )
    elif promo["has_attribution"] and promo["fixed_bonus_rub"] and promo["fixed_bonus_rub"] > 0:
        if promo["bonus_used"]:
            lines.append(
                f"🎁 Промо <code>{promo['promo_code']}</code>: бонус "
                f"<b>{promo['fixed_bonus_rub']:,.0f} ₽</b> уже использован."
                .replace(",", " ")
            )
        else:
            lines.append(
                f"🎁 Доступен промо-бонус: <b>{promo['fixed_bonus_rub']:,.0f} ₽</b> "
                f"(код <code>{promo['promo_code']}</code>)\n"
                "Применится на первой заявке."
                .replace(",", " ")
            )
    elif promo["has_attribution"]:
        lines.append(f"🔗 Вы пришли по партнёрской ссылке <code>{promo['promo_code']}</code>.")

    lines.append(f"\n📚 Завершённых заявок: <b>{completed}</b>")
    return "\n".join(lines)

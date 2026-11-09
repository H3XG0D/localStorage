from telegram import Update
from telegram.ext import ContextTypes

from services.antispam import rate_limit_ok
from services.exchange_discount_db import get_user_discounts_overview
from services.menu import main_menu_keyboard

MY_DISCOUNTS_MENU = "🏷 Мои скидки"


async def my_discounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return

    user = update.effective_user
    overview = await get_user_discounts_overview(user.id)
    active = overview.get("active") or []
    history = overview.get("history") or []

    lines = ["🏷 <b>Мои скидки на обмен</b>\n"]
    if active:
        lines.append("<b>Активные:</b>")
        for d in active:
            amt = d["amount_rub"]
            code = d.get("promo_code") or "—"
            min_order = float(d.get("min_order_rub") or 0)
            cond = (
                f" · от {min_order:,.0f} ₽".replace(",", " ") if min_order > 0 else ""
            )
            if d.get("issued_by_operator_id"):
                source = " · выдана оператором"
            else:
                source = f" · код <code>{code}</code>"
            lines.append(
                f"• <b>{amt:,.0f} ₽</b>{source}{cond} · до первого обмена"
                .replace(",", " ")
            )
    else:
        lines.append("Активных скидок нет.")

    if history:
        lines.append("\n<b>Использованные:</b>")
        for d in history[:10]:
            amt = d["amount_rub"]
            code = d.get("promo_code") or "—"
            oid = d.get("order_id")
            used = (d.get("used_at") or d.get("created_at") or "")[:10]
            if d.get("status") == "released":
                lines.append(
                    f"• {amt:,.0f} ₽ · код {code} · отменена".replace(",", " ")
                )
            elif oid:
                lines.append(
                    f"• {amt:,.0f} ₽ · заявка <code>{oid}</code> · {used}".replace(",", " ")
                )
            else:
                lines.append(f"• {amt:,.0f} ₽ · код {code}".replace(",", " "))

    lines.append(
        "\n<i>Скидка применяется при покупке крипты — после ввода суммы.</i>"
    )
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=await main_menu_keyboard(user.id, user.username),
    )

"""Экран «Мой баланс»: общий счёт (клиент + партнёр)."""
import logging

from services.user_cashback_db import set_use_cashback_on_next
from services.user_promo_db import format_user_balance_message as _promo_message
from services.user_unified_balance import get_unified_balance_stats

logger = logging.getLogger("user_balance_db")


async def _withdraw_section_html() -> str:
    from services.crypto_network_fee import format_withdraw_terms_html

    body = await format_withdraw_terms_html(compact=False)
    return body.replace(
        "💸 <b>Вывод общего баланса</b>",
        "💸 <b>Вывод</b>\nКнопка «Вывести средства» — с общего баланса.",
        1,
    )


def _fmt_rub(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ")


async def format_full_balance_message(user_id: int) -> str:
    base = await _promo_message(user_id)
    s = await get_unified_balance_stats(user_id)

    lines = [
        base,
        "",
        "💼 <b>Общий баланс</b>",
        "Кешбэк, промокоды, реферальные и партнёрские начисления — один счёт.",
        "",
        f"💰 На счёте: <b>{_fmt_rub(s['balance_rub'])} ₽</b>",
        f"✅ Можно вывести или списать при обмене: <b>{_fmt_rub(s['available_rub'])} ₽</b>",
        "",
        "📦 <b>Из чего состоит</b>",
        f"• Кешбэк за обмены: <b>{_fmt_rub(s['exchange_cashback_rub'])} ₽</b>",
    ]
    if s.get("promo_rub", 0) > 0:
        lines.append(f"• Промокоды: <b>{_fmt_rub(s['promo_rub'])} ₽</b>")
    lines.append(f"• Реферальные начисления: <b>{_fmt_rub(s['referral_rub'])} ₽</b>")
    if s.get("partner_balance_rub", 0) > 0:
        code = s.get("partner_campaign_code") or "—"
        lines.append(
            f"• Партнёрские ({code}): <b>{_fmt_rub(s['partner_balance_rub'])} ₽</b>"
        )
    lines.extend(
        [
            f"= <b>{_fmt_rub(s['balance_rub'])} ₽</b> всего",
            "",
            f"🎁 Кешбэк с покупки: <b>{s['percent']:g}%</b> от прибыли сервиса.",
        ]
    )
    done = s.get("completed_exchanges", 0)
    until = s.get("exchanges_until_next_tier", 0)
    pct_max = s.get("percent_max", 15)
    if until > 0:
        lines.append(
            f"📈 Завершённых обменов: <b>{done}</b> · до +{s.get('tier_step_percent', 2):g}% "
            f"осталось <b>{until}</b> (макс. {pct_max:g}%)"
        )
    else:
        lines.append(f"📈 Завершённых обменов: <b>{done}</b> · максимальный кешбэк")

    if s["use_on_next"]:
        lines.append("\n✅ Баланс спишется при следующем обмене.")
    else:
        lines.append(
            "\nℹ️ Списать баланс при обмене — кнопка «Списать при следующем обмене»."
        )

    lines.extend(
        [
            "",
            await _withdraw_section_html(),
            "",
            "👥 Приглашения друзей — в «Профиль» → «Реф. программа».",
        ]
    )
    try:
        from services.buyer_access_guards import format_conversion_line
        from services.db import get_buyer_payfast_conversion

        conv = await get_buyer_payfast_conversion(user_id)
        lines.extend(["", "📈 <b>Процент успеха</b>", format_conversion_line(conv)])
        from services.buyer_access_guards import format_low_conversion_warning

        warn = format_low_conversion_warning(conv)
        if warn:
            lines.append(warn)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    if s.get("partner_balance_rub", 0) > 0:
        lines.append(
            "\n📊 Партнёрская статистика — «Партнёрский кабинет» в меню."
        )
    return "\n".join(lines)


async def toggle_cashback_use(user_id: int) -> bool:
    from services.user_cashback_db import should_use_cashback

    new_val = not await should_use_cashback(user_id)
    await set_use_cashback_on_next(user_id, new_val)
    return new_val

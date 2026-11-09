"""
Красивые пользовательские тексты FocusPay (стиль demo_bot).

Форма: RULE + <blockquote> + premium <tg-emoji>.
Числа и условия — только из прод-логики (курсы, комиссии, лимиты).
"""
from __future__ import annotations

from typing import Any, Sequence

from services.support_urls import telegram_href
from services.tg_emoji import e

RULE = "━━━━━━━━━━━━━━━━━━━━"

CARD_WITHDRAW_PROMISE = (
    "Чистейшие деньги с расчётного счёта. Блокировки не будет. "
    "Если блокировка придёт на наш платёж и это подтвердят выписки и разбор, "
    "вернём сумму вручную через оператора."
)

COIN_NAMES = {
    "btc": "Bitcoin",
    "usdt": "Tether",
    "trx": "Tron",
    "ltc": "Litecoin",
}


def fmt_rub(value: float | int, *, decimals: int = 0) -> str:
    if decimals <= 0:
        return f"{float(value):,.0f}".replace(",", " ")
    return f"{float(value):,.{decimals}f}".replace(",", " ")


def fmt_rate(value: float | int | None) -> str:
    if value is None:
        return "—"
    v = float(value)
    if v >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if v >= 10:
        return f"{v:,.2f}".replace(",", " ")
    return f"{v:.4f}".rstrip("0").rstrip(".")


def header(emoji_key: str, title: str) -> str:
    return f"{e(emoji_key)} <b>{title}</b>\n{RULE}"


def block(*lines: str) -> str:
    return "<blockquote>" + "\n".join(lines) + "</blockquote>"


# ---------------------------------------------------------------------------
# /start · О нас · отзывы
# ---------------------------------------------------------------------------

def txt_start(*, cashback_max_pct: float = 15) -> str:
    steps = block(
        f"1. {e('obmen')} Нажмите «Совершить обмен» и выберите монету",
        f"2. {e('stats')} Выберите: купить или продать",
        f"3. {e('sbp')} Укажите сумму в ₽ или в крипте",
        f"4. {e('check')} Оплатите по реквизитам — крипта у вас",
    )
    return (
        f"{e('wave')} <b>FocusPay</b> — обмен криптовалюты за рубли\n"
        f"{RULE}\n\n"
        f"Быстро, по выгодному курсу, с кешбэком до {cashback_max_pct:g}%.\n\n"
        f"<b>Как обменять за 4 шага:</b>\n"
        f"{steps}\n\n"
        f"{e('profile')} <b>Профиль</b> — баланс, кешбэк, рефералка\n"
        f"{e('stats')} <b>Курсы</b> · {e('support')} <b>О нас</b>\n\n"
        f"<i>Выберите действие на клавиатуре ниже</i> 👇"
    )


def txt_about() -> str:
    return (
        f"{e('support')} <b>О нас</b>\n"
        f"{RULE}\n\n"
        f"Возник вопрос или сложность — напишите оператору, поможем разобраться.\n\n"
        f"{e('star')} Доступны ручные обмены от 5 000 ₽ и другие услуги под запрос.\n\n"
        f"<i>Кнопки ниже: поддержка · чат · отзывы · сайт.</i>"
    )


def txt_reviews(*, extra: str | None = None) -> str:
    text = (
        f"{e('announce')} <b>Отзывы FocusPay</b>\n"
        f"{RULE}\n\n"
        f"Бонус за отзыв доступен после успешной покупки "
        f"(когда крипта уже отправлена).\n\n"
        f"{e('idea')} <b>Отзыв + скрин = бонус ₽</b> на баланс после модерации."
    )
    if extra:
        text = f"{text}\n\n{extra}"
    return text


def txt_support(*, chat_url: str, community_url: str) -> str:
    return (
        f"{e('support')} <b>Поддержка</b>\n"
        f"{RULE}\n\n"
        f"Если у вас возникли сложности или есть вопрос — напишите оператору, "
        f"мы поможем разобраться.\n\n"
        f"{e('star')} Доступны ручные обмены от <b>5 000 ₽</b> "
        f"и другие услуги под индивидуальный запрос.\n\n"
        f"{e('chat')} {telegram_href('Чат на сайте', chat_url)} или @focus_operator\n"
        f"{e('people')} Общий чат: {telegram_href('focus чат', community_url)}"
    )


def txt_site() -> str:
    return (
        f"{e('internet')} <b>Сайт FocusPay</b>\n"
        f"{RULE}\n\n"
        f"Открыть обменник: <a href=\"https://focuspay.org\">focuspay.org</a>"
    )


# ---------------------------------------------------------------------------
# Обмен
# ---------------------------------------------------------------------------

def txt_exchange_start(
    *,
    rates: dict[str, float | int | None],
    cashback_from_pct: float,
) -> str:
    rate_lines = [
        f"{e('btc')} Bitcoin (BTC) — {fmt_rate(rates.get('btc'))} ₽",
        f"{e('usdt')} Tether (USDT) — {fmt_rate(rates.get('usdt'))} ₽",
        f"{e('trx')} Tron (TRX) — {fmt_rate(rates.get('trx'))} ₽",
        f"{e('ltc')} Litecoin (LTC) — {fmt_rate(rates.get('ltc'))} ₽",
    ]
    return (
        f"{e('obmen')} <b>Обмен криптовалюты · шаг 1 из 4</b>\n"
        f"{RULE}\n\n"
        f"Выберите монету на кнопке ниже.\n"
        f"Дальше — купить/продать, затем сумма.\n\n"
        f"<b>Доступные монеты и курс:</b>\n"
        f"{block(*rate_lines)}\n\n"
        f"{e('gift')} Кешбэк с каждого обмена — от <b>{cashback_from_pct:g}%</b>\n\n"
        f"<i>Если вам потребуется помощь в оформлении обмена, "
        f"вы можете обратиться за помощью к нам — @focus_operator</i>"
    )


def txt_usdt_network() -> str:
    from services.crypto_network_fee import format_usdt_buy_send_fee_html

    nets = block(
        "TRC20 — обычно дешевле и быстрее",
        "ERC20 / BEP20 / ARBITRUM / SOLANA — по вашей сети",
    )
    return (
        f"{e('internet')} <b>Сеть USDT · шаг 2 из 4</b>\n"
        f"{RULE}\n\n"
        f"Выберите сеть получения/отправки USDT.\n\n"
        f"{nets}\n\n"
        f"{e('info')} {format_usdt_buy_send_fee_html()}"
    )


def txt_direction(
    *,
    crypto: str,
    coin_title: str,
    rate: float | int | None,
) -> str:
    coin = crypto.upper()
    explain = block(
        "🟢 Купить — платите рубли, получаете крипту",
        "🔴 Продать — отдаёте крипту, получаете рубли",
    )
    send_fee_note = ""
    if crypto.lower() == "usdt":
        from services.crypto_network_fee import format_usdt_buy_send_fee_html

        send_fee_note = f"\n\n{e('info')} {format_usdt_buy_send_fee_html()}"
    return (
        f"{e(crypto.lower())} <b>{coin_title}</b>\n"
        f"{RULE}\n\n"
        f"Курс: <b>1 {coin} = {fmt_rate(rate)} ₽</b>\n\n"
        f"Что делаем с {coin}?\n"
        f"{explain}"
        f"{send_fee_note}"
    )


def txt_unit(*, crypto: str, direction: str) -> str:
    coin = crypto.upper()
    verb = "покупки" if direction == "buy" else "продажи"
    title = "Покупка" if direction == "buy" else "Продажа"
    explain = block(
        "₽ В рублях — сколько потратить/получить рублями",
        f"{coin} В {coin} — сколько крипты купить/продать",
    )
    return (
        f"{e(crypto.lower())} <b>{title} {coin}</b>\n"
        f"{RULE}\n\n"
        f"В чём укажете сумму {verb}?\n"
        f"{explain}"
    )


def txt_amount_prompt(
    *,
    crypto: str,
    direction: str,
    unit: str,
    min_label: str,
    max_label: str | None = None,
) -> str:
    coin = crypto.upper()
    verb = "покупки" if direction == "buy" else "продажи"
    title = "Покупка" if direction == "buy" else "Продажа"
    if unit == "rub":
        unit_label = "рублях (₽)"
        example = block("Например: 5000 · 15000 · 50000")
        if direction == "buy":
            example += (
                "\nЭто оценка крипты. Итоговую сумму к оплате увидите на следующем шаге."
            )
    else:
        unit_label = coin
        example = block(f"Например: 0.5 · 1 · 2.5 {coin}")
    max_line = ""
    if max_label:
        max_line = f"\n{e('info')} Максимум: <b>{max_label}</b>"
    send_fee_note = ""
    if direction == "buy" and crypto.lower() == "usdt":
        from services.crypto_network_fee import format_usdt_buy_send_fee_html

        send_fee_note = f"\n\n{e('info')} {format_usdt_buy_send_fee_html()}"
    return (
        f"{e(crypto.lower())} <b>{title} {coin}</b>\n"
        f"{RULE}\n\n"
        f"Введите сумму {verb} в <b>{unit_label}</b> сообщением.\n"
        f"{e('info')} Минимальная сумма: <b>{min_label}</b>"
        f"{max_line}\n\n"
        f"{example}"
        f"{send_fee_note}"
    )


def txt_bad_amount() -> str:
    return (
        f"{e('info')} Введите положительное число — сумму обмена.\n"
        f"Например: <b>15000</b>"
    )


def txt_amount_below_min(*, coin: str, minimum: str) -> str:
    return (
        f"{e('info')} Сумма ниже минимальной для {coin}.\n"
        f"Минимум: <b>{minimum}</b>. Введите сумму побольше."
    )


def txt_amount_above_max(*, coin: str, maximum: str) -> str:
    return (
        f"{e('info')} Сумма выше максимальной для {coin}.\n"
        f"Максимум: <b>{maximum}</b>. Введите сумму поменьше."
    )


def txt_exchange_cancelled() -> str:
    return (
        f"{e('info')} Обмен отменён.\n\n"
        f"Нажмите «Совершить обмен», когда будете готовы."
    )


def txt_action_cancelled() -> str:
    return (
        f"{e('info')} <b>Действие отменено</b>\n"
        f"{RULE}\n\n"
        f"Вы вернулись в главное меню."
    )


# ---------------------------------------------------------------------------
# Post-amount
# ---------------------------------------------------------------------------

def txt_exchange_discount_prompt(*, amount_rub: float | None, multi: bool) -> str:
    if multi:
        return (
            f"{e('discount')} <b>Скидка на обмен</b>\n"
            f"{RULE}\n\n"
            f"У вас несколько скидок. Какую применить к этому заказу?"
        )
    amt = fmt_rub(amount_rub or 0)
    return (
        f"{e('discount')} <b>Скидка на обмен</b>\n"
        f"{RULE}\n\n"
        f"Неиспользованная скидка: <b>{amt} ₽</b>.\n"
        f"Применить к этому заказу сейчас или оставить на потом?"
    )


def txt_balance_discount_prompt(
    *,
    available: float,
    est_discount: float,
    disc_note: str = "",
) -> str:
    return (
        f"{e('wallet')} <b>Списание с баланса</b>\n"
        f"{RULE}\n\n"
        f"На балансе доступно <b>{fmt_rub(available, decimals=2)} ₽</b>\n"
        f"(кешбэк, промо, рефералка, партнёрские).\n\n"
        f"При этой сумме скидка балансом до "
        f"<b>{fmt_rub(est_discount, decimals=2)} ₽</b>."
        f"{disc_note}\n\n"
        f"Применить баланс к этой покупке?"
    )


def txt_payment_method_prompt(*, pay_hint: str = "") -> str:
    return (
        f"{e('card')} <b>Способ оплаты</b>\n"
        f"{RULE}\n\n"
        f"Куда удобнее оплатить — картой или СБП?"
        f"{pay_hint}"
    )


def txt_buy_amount_preview(
    *,
    pay_label: str,
    lines_extra: Sequence[str],
    fiat_pay: float,
    receive_line: str | None,
) -> str:
    body = [
        f"{e('card')} Оплата: <b>{pay_label}</b>",
        *lines_extra,
        f"{e('ruble')} К оплате: <b>{fmt_rub(fiat_pay, decimals=2)} ₽</b>",
    ]
    if receive_line:
        body.append(receive_line)
    return (
        f"{e('check')} <b>Проверьте условия</b>\n"
        f"{RULE}\n\n"
        f"{block(*body)}\n\n"
        f"Устраивает? Нажмите «✅ Да, устраивает» — "
        f"после этого попросим адрес кошелька."
    )


def txt_ask_wallet(*, crypto_upper: str) -> str:
    return (
        f"{e('wallet')} <b>Адрес получения</b>\n"
        f"{RULE}\n\n"
        f"Укажите адрес <b>{crypto_upper}</b>-кошелька сообщением."
    )


def txt_ask_sell_requisites() -> str:
    examples = block(
        "7777444466668888 T-банк",
        "+79999999999 Сбербанк",
    )
    return (
        f"{e('card')} <b>Реквизиты для вывода</b>\n"
        f"{RULE}\n\n"
        f"Укажите реквизиты: <code>карта + банк</code> / <code>СБП + банк</code>\n\n"
        f"{examples}"
    )


def txt_order_created(
    *,
    display_id: str,
    fiat: float,
    receive_line: str | None,
    requisites_block: str,
    rules_block: str,
    title: str | None = None,
    extra_lines: Sequence[str] | None = None,
) -> str:
    if title and ("tg-emoji" in title or title.startswith("<")):
        head = title
    elif title:
        head = f"{e('check')} <b>{title.rstrip('!')}</b>"
    else:
        head = f"{e('check')} <b>Заявка создана</b>"
    summary = [
        f"{e('link')} ID: <code>{display_id}</code>",
        f"{e('info')} Статус: ожидает оплаты",
        f"{e('ruble')} К оплате: <b>{fmt_rub(fiat)} ₽</b>",
    ]
    if receive_line:
        summary.append(receive_line)
    if extra_lines:
        summary.extend(extra_lines)
    return (
        f"{head}\n"
        f"{RULE}\n\n"
        f"{block(*summary)}\n\n"
        f"{requisites_block}\n\n"
        f"{rules_block}"
    )


# ---------------------------------------------------------------------------
# Профиль · курсы · история · рефка · вывод
# ---------------------------------------------------------------------------

def txt_profile_caption(u: dict[str, Any]) -> str:
    bal = block(
        f"{e('gift')} из кешбэка: {fmt_rub(u['cashback'], decimals=2)} ₽",
        f"{e('people')} из рефералки: {fmt_rub(u['referral'], decimals=2)} ₽",
    )
    return (
        f"{e('profile')} <b>Профиль · {u['name']}</b>\n"
        f"{RULE}\n\n"
        f"{e('wallet')} Баланс: <b>{fmt_rub(u['balance'], decimals=2)} ₽</b>\n"
        f"{bal}\n\n"
        f"{e('fire')} Кешбэк: <b>{u['cashback_percent']:g}%</b> · "
        f"🎟 Билетов: <b>{u['tickets']}</b> · "
        f"{e('obmen')} Обменов: <b>{u['deals_done']}</b>\n\n"
        f"<i>Управление — кнопки ниже</i> 👇"
    )


def txt_rates(
    *,
    rate_lines: Sequence[str],
    limits_line: str,
    site: str,
    withdraw_block: str | None = None,
) -> str:
    parts = [
        f"{e('stats')} <b>Курсы и условия</b>\n{RULE}",
        f"{e('chart_up')} <b>Цена за 1 монету:</b>\n{block(*rate_lines)}",
        f"{e('card')} {limits_line}",
        f"{e('internet')} {site} — обновление каждую минуту",
    ]
    if withdraw_block:
        parts.append(withdraw_block)
    return "\n\n".join(parts)


def txt_history(
    *,
    total: int,
    shown: int,
    active_block: str | None,
    order_blocks: Sequence[str],
) -> str:
    lines = [
        f"{e('history')} <b>История операций</b>",
        RULE,
        f"Всего завершённых: <b>{total}</b>"
        + (f" · показаны последние <b>{shown}</b>" if shown else ""),
        "",
    ]
    if active_block:
        lines.append(active_block)
        lines.append("")
    if order_blocks:
        lines.extend(order_blocks)
    elif total == 0:
        lines.append("У вас пока нет завершённых обменов.")
    return "\n".join(lines)


def txt_referral_cabinet(
    *,
    pct: float,
    tier_step: float,
    tier_every: int,
    tier_max: float,
    referred: int,
    paid_orders: int,
    today_rub: float,
    total_rub: float,
    balance_rub: float,
    cashback_rub: float,
    referral_rub: float,
    partner_rub: float,
    available_rub: float,
    pending_withdraw: float,
    link: str,
    withdraw_footer: str,
) -> str:
    stats_lines = [
        f"{e('profile')} Приглашено: {referred}",
        f"{e('check')} Оплаченных сделок друзей: {paid_orders}",
        f"{e('chart_up')} Начислено сегодня: {fmt_rub(today_rub, decimals=2)} ₽",
        f"{e('sport')} Всего заработано: {fmt_rub(total_rub, decimals=2)} ₽",
    ]
    bal_lines = [
        f"Всего на счёте: {fmt_rub(balance_rub, decimals=2)} ₽",
        f"{e('gift')} из кешбэка: {fmt_rub(cashback_rub, decimals=2)} ₽",
        f"{e('people')} из рефералки: {fmt_rub(referral_rub, decimals=2)} ₽",
    ]
    if partner_rub > 0:
        bal_lines.append(f"партнёрские: {fmt_rub(partner_rub, decimals=2)} ₽")
    bal_lines.append(f"Можно вывести: {fmt_rub(available_rub, decimals=2)} ₽")
    bal_lines.append(f"В заявках на вывод: {fmt_rub(pending_withdraw, decimals=2)} ₽")
    return (
        f"{e('people')} <b>Реферальная программа</b>\n"
        f"{RULE}\n\n"
        f"Приглашайте друзей — получайте <b>{pct:g}%</b> от прибыли по их обменам.\n"
        f"С оплаты VPN другом — лесенка: +{tier_step:g}% за каждых {tier_every} приглашённых "
        f"(макс. {tier_max:g}%).\n"
        f"{e('fire')} Партнёрский уровень: +{tier_step:g}% за каждых {tier_every} реф. "
        f"(макс. {tier_max:g}%).\n\n"
        f"<b>Ваша статистика:</b>\n"
        f"{block(*stats_lines)}\n\n"
        f"<b>Общий баланс:</b>\n"
        f"{block(*bal_lines)}\n\n"
        f"{e('link')} <b>Ваша ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        f"{withdraw_footer}"
    )


def txt_withdraw_terms(
    *,
    card_min: int | float,
    min_btc_line: str,
    min_usdt_line: str,
    fee_card: str,
    fee_crypto: str,
    fee_usdt: str,
    compact: bool = False,
) -> str:
    if compact:
        return (
            f"{e('dollar')} <b>Вывод</b> (кешбэк, промо, рефералка, партнёрские):\n"
            f"Карта / СБП от <b>{fmt_rub(card_min)} ₽</b>; {min_btc_line}; {min_usdt_line}.\n"
            f"Комиссия: карта {fee_card} · BTC/LTC/TRX {fee_crypto} · USDT {fee_usdt}.\n"
            f"{CARD_WITHDRAW_PROMISE}"
        )
    mins = block(
        f"{e('card')} Карта / СБП — от {fmt_rub(card_min)} ₽",
        f"{e('btc')} BTC, {e('ltc')} LTC, {e('trx')} TRX — {min_btc_line}",
        f"{e('usdt')} USDT — {min_usdt_line}",
    )
    return (
        f"{e('dollar')} <b>Вывод средств</b>\n"
        f"{RULE}\n\n"
        f"С общего баланса: кешбэк, промокоды, рефералка, партнёрские.\n\n"
        f"<b>Минимумы:</b>\n"
        f"{mins}\n\n"
        f"<b>Комиссия</b> (с суммы):\n"
        f"Карта / СБП — {fee_card}\n"
        f"BTC / LTC / TRX — {fee_crypto}\n"
        f"USDT — {fee_usdt}\n\n"
        f"{CARD_WITHDRAW_PROMISE}"
    )


def txt_promo_enter() -> str:
    return (
        f"{e('promo')} <b>Промокод</b>\n"
        f"{RULE}\n\n"
        f"Отправьте код одним сообщением.\n"
        f"Код может зачислить сумму на баланс или выдать скидку на обмен — "
        f"зависит от типа промо."
    )


def txt_focus_lucky(
    *,
    month: str,
    tickets_total: int,
    ticket_numbers: str,
    win_chance: str | None,
    prizes_html: str,
    draw_line: str | None,
    info_text: str,
) -> str:
    if tickets_total > 0:
        ticket_block = (
            f"🎟 У вас: <b>{tickets_total}</b> билетиков\n"
            f"{e('fire')} Шанс: <b>{win_chance}</b>\n"
            f"Номера: {ticket_numbers}"
        )
    else:
        ticket_block = "🎟 У вас пока нет билетиков — совершите обмен!"
    parts = [
        f"{e('sport')} <b>FocusLucky — {month}</b>\n{RULE}",
        ticket_block,
        f"{e('gift')} <b>Призовой фонд:</b>\n{prizes_html}",
    ]
    if draw_line:
        parts.append(f"{e('calendar')} {draw_line}")
    if info_text:
        parts.append(info_text)
    return "\n\n".join(parts)

"""Topic help for FocusCasino. Each page is one Telegram message (< 4096)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import config
from finance import setting_decimal
from wagering import help_wagering_line

HELP_TOPICS = (
    "roulette",
    "jackpot",
    "rooms",
    "cub",
    "2cub",
    "baccara",
    "blackjack",
    "tables",
    "duels",
    "deposit",
    "fairness",
    "team",
    "rules",
)

TOPIC_ALIASES: dict[str, str] = {
    "рулетка": "roulette",
    "джекпот": "jackpot",
    "комната": "rooms",
    "комнаты": "rooms",
    "куб": "cub",
    "кубик": "cub",
    "кубики": "cub",
    "двакуба": "2cub",
    "баккара": "baccara",
    "блекджек": "blackjack",
    "blackjack": "blackjack",
    "стол": "tables",
    "столы": "tables",
    "дуэль": "duels",
    "дуэли": "duels",
    "пополнение": "deposit",
    "депозит": "deposit",
    "честность": "fairness",
    "клан": "team",
    "кланы": "team",
    "команда": "team",
    "правила": "rules",
}


def parse_help_topic(text: str) -> str:
    parts = (text or "").split()
    if len(parts) < 2:
        return ""
    raw = parts[1].lstrip("/").split("@", 1)[0].lower().replace("ё", "е")
    if raw in HELP_TOPICS:
        return raw
    return TOPIC_ALIASES.get(raw, raw)


def _money_text(value: object, fallback: str) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    if number == number.to_integral_value():
        return str(int(number))
    return format(number.quantize(Decimal("0.01")), "f")


def _setting_money(settings: Mapping[str, Any], key: str, fallback: str) -> str:
    raw = settings.get(key, fallback)
    if isinstance(raw, Mapping):
        raw = raw.get("amount", raw.get("percent", raw.get("value", fallback)))
    return _money_text(raw, fallback)


def _deposits_enabled() -> bool:
    return bool(getattr(config, "DEPOSITS_ENABLED", False))


def _limits(settings: Mapping[str, Any]) -> dict[str, Any]:
    symbol = config.CURRENCY_SYMBOL
    min_bet = _setting_money(settings, "min_bet_rub", str(getattr(config, "MIN_BET", 10)))
    max_bet = _setting_money(settings, "max_bet_rub", str(getattr(config, "MAX_BET", 100000)))
    commission_active = _setting_money(
        settings,
        "commission_rate_wagering_active",
        str(getattr(config, "COMMISSION_RATE_WAGERING_ACTIVE", 15)),
    )
    commission_complete = _setting_money(
        settings,
        "commission_rate_wagering_complete",
        str(getattr(config, "COMMISSION_RATE_WAGERING_COMPLETE", 5)),
    )
    wagering = _setting_money(
        settings, "wagering_percent", str(getattr(config, "WAGERING_PERCENT", 100))
    )
    collect = _setting_money(settings, "roulette_table_collect_seconds", "25")
    jackpot_collect = _setting_money(settings, "jackpot_collect_seconds", "300")
    dep_min = _money_text(getattr(config, "DEPOSIT_MIN_RUB", 500), "500")
    dep_max = _money_text(getattr(config, "DEPOSIT_MAX_RUB", 100000), "100000")
    try:
        wagering_line = help_wagering_line(
            wagering_percent=float(setting_decimal(settings, key="wagering_percent", nested_key="percent", default=wagering)),
            commission_percent=float(
                setting_decimal(
                    settings,
                    key="commission_rate_wagering_active",
                    nested_key="percent",
                    default=commission_active,
                )
            ),
            currency_symbol=symbol,
        )
    except (InvalidOperation, TypeError, ValueError):
        wagering_line = f"• Отыгрыш пополнения: {wagering}%"
    return {
        "symbol": symbol,
        "min_bet": min_bet,
        "max_bet": max_bet,
        "commission_active": commission_active,
        "commission_complete": commission_complete,
        "wagering": wagering,
        "collect": collect,
        "jackpot_collect": jackpot_collect,
        "dep_min": dep_min,
        "dep_max": dep_max,
        "wagering_line": wagering_line,
        "deposits_enabled": _deposits_enabled(),
    }


def help_index(limits: Mapping[str, Any] | None = None) -> str:
    info = limits or {}
    min_bet = info.get("min_bet", "10")
    max_bet = info.get("max_bet", "100000")
    symbol = info.get("symbol", "₽")
    active = info.get("commission_active", "15")
    complete = info.get("commission_complete", "5")
    if info.get("deposits_enabled"):
        commission_line = f"Комиссия игр: {active}% до отыгрыша, {complete}% после"
        deposit_line = "Пополнение: кнопка «Пополнить» или /deposit — СБП или карта."
    else:
        commission_line = f"Комиссия игр: {complete}%"
        deposit_line = (
            "Пополнение: скоро. Сейчас на баланс — призы FocusLucky, кешбэк и рефералка."
        )
    return (
        "🎰 <b>FocusCasino — справка</b>\n\n"
        "Играть на сайте или кнопками меню.\n\n"
        "Живые игры: кубики, баккара, блэкджек, рулетка 0–36, джекпот, комнаты. "
        "FocusLucky — билеты за обмены FocusPay, не рулетка.\n\n"
        f"Ставка: {min_bet}–{max_bet} {symbol}\n"
        f"{commission_line}\n"
        f"{deposit_line}\n\n"
        "Темы:\n"
        "/help roulette — европейская рулетка 0–36\n"
        "/help jackpot — джекпот, банк и шансы\n"
        "/help rooms — комнаты, равная ставка, колесо\n"
        "/help cub — кубик 1×1 и стол в чате\n"
        "/help 2cub — два броска\n"
        "/help baccara — баккара\n"
        "/help blackjack — блэкджек\n"
        "/help tables — стол 2–6, мастер, боты\n"
        "/help duels — дуэли /newgame /allgames /del\n"
        "/help deposit — пополнение\n"
        "/help fairness — commit и сиды\n"
        "/help rules — лимиты, комиссия, игровой чат\n\n"
        "Розыгрыши /fast выключены."
    )


def help_roulette(limits: Mapping[str, Any]) -> str:
    return (
        "🎡 <b>Европейская рулетка 0–36</b>\n\n"
        "Общий стол на сайте, не FocusLucky. Одна команда без <code>multi</code> — "
        "одна фишка на одну клетку.\n\n"
        "<b>Синтаксис</b>\n"
        "<code>/roulette red 50</code> — цвет, суффикс не нужен\n"
        "<code>/roulette 17 10р</code> — число. Сумма 0–36 только с <code>р</code> / <code>₽</code>\n"
        "<code>/roulette 10 10</code> — отказ: напишите 10р, иначе это число 10\n"
        "<code>/roulette 1rd 50</code> — ряд 1–12, выплата 2:1\n"
        "<code>/roulette multi 1 4 6 10р</code> — три фишки по 10 ₽, не пачка 36/N\n\n"
        "<b>Клетки</b>\n"
        "• цвет: red / black, красное / чёрное — 1:1\n"
        "• число 0–36, зеро — 35:1\n"
        "• чёт / нечет, even / odd — 1:1\n"
        "• 1–18 / 19–36, low / high — 1:1\n"
        "• ряд 1rd 2rd 3rd (1–12 / 13–24 / 25–36) — 2:1\n"
        "• колонка 1col 2col 3col — 2:1\n\n"
        f"Общее колесо ~{limits['collect']} с после первой ставки. "
        "Ставка в личке с ботом или в игровом чате. Чужая группа — отказ.\n"
        "Чужие фишки видны на сайте, ник ведёт в профиль.\n"
        "Стол: /casino/play/roulette?mode=players"
    )


def help_jackpot(limits: Mapping[str, Any]) -> str:
    return (
        "🎡 <b>Джекпот</b>\n\n"
        "Один общий банк с сайтом. Шанс = доля ставки. Докид можно, выйти нельзя. "
        "Дом не играет.\n\n"
        "<b>Синтаксис</b>\n"
        "<code>/jackpot</code> — банк, таймер, кто в игре и проценты\n"
        "<code>/jackpot 100</code> — поставить 100 ₽ в текущий раунд\n"
        "<code>/jackpot 50р</code> — то же, суффикс необязателен\n\n"
        f"Окно сбора ~{limits['jackpot_collect']} с после первой ставки, "
        "или сразу при полном наборе игроков. Один игрок к дедлайну — возврат. "
        f"Рейк с банка, лимит ставки {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}.\n"
        "Личка с ботом или игровой чат. Чужая группа — отказ.\n"
        "Стол: /casino/play/jackpot"
    )


def help_rooms(limits: Mapping[str, Any]) -> str:
    return (
        "🎯 <b>Комнаты</b>\n\n"
        "Равная ставка на всех, 2–6 мест, колесо выбирает одного. "
        "Пустое место можно заполнить ботом. Рейк с банка.\n\n"
        "<b>Старт</b>\n"
        "<code>/rooms</code> или «Создать игру» → Комнаты. "
        "Ставка, затем число мест, затем создать.\n"
        "Из «Активные игры» — сесть / выйти / отменить / добавить бота.\n\n"
        f"Лимит ставки {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}. "
        "Личка с ботом или игровой чат. Чужая группа — отказ.\n"
        "Карточка на сайте: /casino/rooms/…"
    )


def help_cub(limits: Mapping[str, Any]) -> str:
    return (
        "🎲 <b>Кубик</b>\n\n"
        f"Личка и игровой чат: <code>/cub {limits['min_bet']}</code> — стол с людьми. "
        "Выберите число мест и ставку. Пустое место — кнопка ➕ бот.\n\n"
        "Равные ставки, больше сумма граней забирает банк после комиссии. Ничья — переброс или раздел.\n"
        f"Лимит ставки: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}."
    )


def help_2cub(limits: Mapping[str, Any]) -> str:
    return (
        "🎲 <b>Два кубика</b>\n\n"
        f"<code>/2cub {limits['min_bet']}</code> — два броска 🎲. В чате это стол с людьми, "
        "как /cub, только два куба.\n"
        f"Лимит: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}."
    )


def help_baccara(limits: Mapping[str, Any]) -> str:
    return (
        "🃏 <b>Баккара</b>\n\n"
        "Старт: /baccara в личке или игровом чате — стол с людьми. "
        "Выберите число мест и ставку. Пустое место — кнопка ➕ бот.\n"
        "Равные ставки, ближе к девяти. Тасовка на сервере, стол виден на сайте.\n"
        f"Лимит: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}."
    )


def help_blackjack(limits: Mapping[str, Any]) -> str:
    return (
        "🂡 <b>Блэкджек</b>\n\n"
        "Старт: /blackjack в личке или игровом чате — стол с людьми. "
        "Выберите число мест и ставку. Пустое место — кнопка ➕ бот.\n"
        "Равные ставки, руки до 17. Выше без перебора забирает банк. Стол на сайте.\n"
        f"Лимит: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}."
    )


def help_tables(limits: Mapping[str, Any]) -> str:
    return (
        "🪑 <b>Стол 2–6</b>\n\n"
        "Мастер: /cub, /2cub, /baccara, /blackjack или кнопка «Создать игру».\n"
        "Места 2–6, равные ставки. После создания на карточке ➕ сажает бота. "
        "Игра идёт в игровом чате и на сайте.\n"
        f"Лимит: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}."
    )


def help_duels() -> str:
    return (
        "⚔️ <b>Дуэли</b>\n\n"
        "/newgame — создать игру в личке (ставка резервируется после подтверждения).\n"
        "/allgames — в личке лобби, в игровом чате ожидающие столы.\n"
        "/del — удалить свою ожидающую игру ответом на карточку.\n"
        "Бросок куба — в игровом чате, не в чужой группе."
    )


def help_deposit(limits: Mapping[str, Any]) -> str:
    if not limits.get("deposits_enabled"):
        return (
            "💳 <b>Пополнение</b>\n\n"
            "Пополнение скоро. Сейчас на баланс попадают призы FocusLucky, кешбэк и рефералка. "
            "Вывести уже можно."
        )
    return (
        "💳 <b>Пополнение</b>\n\n"
        f"Лимиты: {limits['dep_min']}–{limits['dep_max']} {limits['symbol']}.\n"
        "Зачисляем ровно сумму пополнения, без комиссии.\n"
        "Способы: СБП или карта. Кнопка «Пополнить» или /deposit.\n"
        f"{limits['wagering_line']}"
    )


def help_fairness() -> str:
    return (
        "🔐 <b>Честность</b>\n\n"
        "/fairness — хеш пары сидов (commit), клиентский сид, nonce.\n"
        "/fairness rotate — новая пара, раскрывается предыдущий серверный сид.\n"
        "/fairness seed имя — свой клиентский сид.\n"
        "Страница проверки: /casino/fairness"
    )


def help_team() -> str:
    return (
        "👥 <b>Команда</b>\n\n"
        "Страница кланов на сайте скрыта, команды бота работают.\n"
        "/team — моя команда\n"
        "/teamcreate TAG Имя — создать\n"
        "/teamjoin КОД — вступить\n"
        "/teamleave /teamkick ID /teaminvite /teamtop\n"
        "/teamtransfer ID /teamdisband\n"
        "Только в личке с ботом."
    )


def help_rules(limits: Mapping[str, Any]) -> str:
    if limits.get("deposits_enabled"):
        commission_line = (
            f"• Комиссия игр: {limits['commission_active']}% до отыгрыша, "
            f"{limits['commission_complete']}% после"
        )
        wagering_line = f"{limits['wagering_line']}\n"
    else:
        commission_line = f"• Комиссия игр: {limits['commission_complete']}%"
        wagering_line = ""
    return (
        "📜 <b>Правила</b>\n\n"
        f"• Ставка: {limits['min_bet']}–{limits['max_bet']} {limits['symbol']}\n"
        f"{commission_line}\n"
        f"{wagering_line}"
        "• Игры — в личке с ботом или в подтверждённом игровом чате. Чужая группа — отказ.\n"
        "/balance — баланс\n"
        "Розыгрыши /fast выключены."
    )


_PAGES = {
    "roulette": help_roulette,
    "jackpot": help_jackpot,
    "rooms": help_rooms,
    "cub": help_cub,
    "2cub": help_2cub,
    "baccara": help_baccara,
    "blackjack": help_blackjack,
    "tables": help_tables,
    "duels": lambda limits: help_duels(),
    "deposit": help_deposit,
    "fairness": lambda limits: help_fairness(),
    "team": lambda limits: help_team(),
    "rules": help_rules,
}


def render_help(settings: Mapping[str, Any] | None, text: str) -> str:
    topic = parse_help_topic(text)
    limits = _limits(settings or {})
    if not topic:
        return help_index(limits)
    page = _PAGES.get(topic)
    if page is None:
        return (
            f"Нет темы «{topic}».\n\n{help_index(limits)}"
        )
    body = page(limits)
    if len(body) > 4096:
        return body[:4090] + "…"
    return body

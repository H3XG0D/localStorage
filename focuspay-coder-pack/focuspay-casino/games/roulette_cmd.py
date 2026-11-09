"""Parse /roulette from Telegram: one named cell, or multi as separate chips."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from finance import money

ROULETTE_TABLE_CHIPS_MAX = 80
POCKET_MAX = 36

CELL_TITLES: dict[str, str] = {
    "red": "красное",
    "black": "чёрное",
    "zero": "зеро",
    "even": "чёт",
    "odd": "нечет",
    "low": "1–18",
    "high": "19–36",
    "dozen1": "1–12",
    "dozen2": "13–24",
    "dozen3": "25–36",
    "col1": "колонка 1",
    "col2": "колонка 2",
    "col3": "колонка 3",
}

CELL_ODDS: dict[str, str] = {
    "red": "1:1",
    "black": "1:1",
    "zero": "35:1",
    "even": "1:1",
    "odd": "1:1",
    "low": "1:1",
    "high": "1:1",
    "dozen1": "2:1",
    "dozen2": "2:1",
    "dozen3": "2:1",
    "col1": "2:1",
    "col2": "2:1",
    "col3": "2:1",
}

NAMED_CELLS = frozenset(CELL_TITLES)
CELL_ALIASES: dict[str, str] = {
    "красное": "red",
    "красн": "red",
    "red": "red",
    "черное": "black",
    "чёрное": "black",
    "black": "black",
    "зеро": "zero",
    "zero": "zero",
    "чет": "even",
    "четное": "even",
    "чётное": "even",
    "even": "even",
    "нечет": "odd",
    "нечетное": "odd",
    "нечётное": "odd",
    "odd": "odd",
    "1-18": "low",
    "мало": "low",
    "low": "low",
    "19-36": "high",
    "много": "high",
    "high": "high",
    "1rd": "dozen1",
    "1-12": "dozen1",
    "dozen1": "dozen1",
    "2rd": "dozen2",
    "13-24": "dozen2",
    "dozen2": "dozen2",
    "3rd": "dozen3",
    "25-36": "dozen3",
    "dozen3": "dozen3",
    "1col": "col1",
    "col1": "col1",
    "2col": "col2",
    "col2": "col2",
    "3col": "col3",
    "col3": "col3",
}

MULTI_WORDS = frozenset({"multi", "мульти"})
_AMOUNT = re.compile(
    r"^(?P<body>\d+(?:[.,]\d{1,2})?)(?P<suf>р|₽|руб|rub)?$",
    re.IGNORECASE,
)

COMMA_PACK_MESSAGE = (
    "Несколько чисел — только через /roulette multi 1 4 6 10р, каждая фишка отдельно. "
    "Запятая вроде 1,5,8 не ставит пачку."
)
USAGE_MESSAGE = (
    "Одна фишка: <code>/roulette red 50</code>, <code>/roulette 17 10р</code>, "
    "<code>/roulette 1rd 50</code>\n"
    "Несколько клеток: <code>/roulette multi 1 4 6 10р</code>\n"
    "Сумма 0–36: суффикс <code>р</code>, иначе это лунка. /help roulette"
)


class RouletteCommandError(ValueError):
    """User-facing parse error. str(exc) is the Telegram reply."""


@dataclass(frozen=True)
class ParsedRouletteCommand:
    cells: tuple[str, ...]
    amount_rub: Decimal
    multi: bool

    @property
    def chip_count(self) -> int:
        return len(self.cells)

    @property
    def debit_rub(self) -> Decimal:
        return money(self.amount_rub * self.chip_count)


def command_args(text: str) -> list[str]:
    parts = (text or "").split()
    return parts[1:] if parts else []


def cell_title(key: str) -> str:
    if key in CELL_TITLES:
        return CELL_TITLES[key]
    return key


def cell_odds(key: str) -> str:
    if key in CELL_ODDS:
        return CELL_ODDS[key]
    return "35:1"


def is_straight_cell(key: str) -> bool:
    return key == "zero" or key.isdigit()


def _has_pack_comma(token: str) -> bool:
    return "," in token or ";" in token


def resolve_cell(token: str) -> str | None:
    raw = token.strip().lower().replace("ё", "е")
    if not raw or _has_pack_comma(raw):
        return None
    if raw in CELL_ALIASES:
        return CELL_ALIASES[raw]
    if raw in NAMED_CELLS:
        return raw
    if raw.isdigit():
        number = int(raw)
        if raw != str(number):
            return None
        if 0 <= number <= POCKET_MAX:
            return "zero" if number == 0 else str(number)
    return None


def parse_amount_token(token: str) -> tuple[Decimal, bool] | None:
    raw = token.strip()
    if raw.count(",") > 1 or ";" in raw:
        return None
    match = _AMOUNT.fullmatch(raw)
    if not match:
        return None
    body = match.group("body").replace(",", ".")
    try:
        amount = money(body)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount, bool(match.group("suf"))


def amount_looks_like_pocket(token: str) -> bool:
    parsed = parse_amount_token(token)
    if parsed is None:
        return False
    amount, had_suffix = parsed
    if had_suffix:
        return False
    if amount != amount.to_integral_value():
        return False
    pocket = int(amount)
    return 0 <= pocket <= POCKET_MAX


def pocket_amount_message(token: str) -> str:
    parsed = parse_amount_token(token)
    number = int(parsed[0]) if parsed else 10
    return f"напишите {number}р, иначе это число {number}"


def parse_roulette_command(text: str) -> ParsedRouletteCommand | None:
    """None = no args (cheat sheet). Raises RouletteCommandError otherwise."""
    args = command_args(text)
    if not args:
        return None
    if any(_has_pack_comma(token) and parse_amount_token(token) is None for token in args):
        raise RouletteCommandError(COMMA_PACK_MESSAGE)
    multi = args[0].lower().replace("ё", "е") in MULTI_WORDS
    body = args[1:] if multi else args
    if len(body) < 2:
        raise RouletteCommandError(USAGE_MESSAGE)
    amount_token = body[-1]
    cell_tokens = body[:-1]
    if multi and not cell_tokens:
        raise RouletteCommandError(USAGE_MESSAGE)
    if not multi and len(cell_tokens) != 1:
        raise RouletteCommandError(USAGE_MESSAGE)
    if any(_has_pack_comma(token) for token in cell_tokens):
        raise RouletteCommandError(COMMA_PACK_MESSAGE)
    cells: list[str] = []
    for token in cell_tokens:
        key = resolve_cell(token)
        if key is None:
            raise RouletteCommandError(f"Неизвестная клетка «{token}». {USAGE_MESSAGE}")
        cells.append(key)
    if len(cells) > ROULETTE_TABLE_CHIPS_MAX:
        raise RouletteCommandError(
            f"В одном multi не больше {ROULETTE_TABLE_CHIPS_MAX} фишек."
        )
    parsed_amount = parse_amount_token(amount_token)
    if parsed_amount is None:
        if _has_pack_comma(amount_token):
            raise RouletteCommandError(COMMA_PACK_MESSAGE)
        raise RouletteCommandError(USAGE_MESSAGE)
    amount, had_suffix = parsed_amount
    numeric_context = multi or is_straight_cell(cells[0])
    if numeric_context and amount_looks_like_pocket(amount_token) and not had_suffix:
        raise RouletteCommandError(pocket_amount_message(amount_token))
    return ParsedRouletteCommand(cells=tuple(cells), amount_rub=amount, multi=multi)

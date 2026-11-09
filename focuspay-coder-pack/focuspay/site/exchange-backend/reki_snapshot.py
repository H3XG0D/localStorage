"""Снимок наличия реквизитов из /reki. Зеркало bot/tg_bot_btc/services/reki_snapshot.py.

Бот отдаёт только агрегат по коридорам сумм, без номеров карт: выдать реквизит
по этим данным нельзя, можно лишь показать наличие и подобрать сумму.
Снимок пишет бот, бэкенд только читает таблицы reki_snapshots / reki_snapshot_meta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

DEFAULT_TTL_SECONDS = 300

SUB_TOKEN_SBP = "SBPRUB"
SUB_TOKEN_CARD = "CARDRUB"

SUB_TOKEN_TITLES = {SUB_TOKEN_SBP: "СБП", SUB_TOKEN_CARD: "Карта (C2C)"}

_SECTION_METHODS = {
    "сбп": SUB_TOKEN_SBP,
    "sbp": SUB_TOKEN_SBP,
    "c2c": SUB_TOKEN_CARD,
    "карта": SUB_TOKEN_CARD,
    "card": SUB_TOKEN_CARD,
}

_SECTION_RE = re.compile(
    r"Количество\s+активных\s+([^:]+):\s*(\d+)",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(
    r"Доступно\s+всего:\s*([\d\s.,]+)\s*RUB",
    re.IGNORECASE,
)
_BAND_RE = re.compile(
    r"([\d\s.,]+)\s*RUB\s*-\s*([\d\s.,]+)\s*RUB",
    re.IGNORECASE,
)
_AVAILABLE_RE = re.compile(
    r"Доступно:\s*([\d\s.,]+)\s*RUB",
    re.IGNORECASE,
)


def _amount(raw: str) -> Decimal | None:
    text = (raw or "").replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not text:
        return None
    try:
        value = Decimal(text)
    except Exception:
        return None
    if value < 0:
        return None
    return value.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class RekiBand:
    min_rub: Decimal
    max_rub: Decimal
    available_rub: Decimal

    @property
    def slots(self) -> int:
        """Оценка числа реквизитов в коридоре: «Доступно» бывает кратно потолку."""
        if self.max_rub <= 0:
            return 0
        return max(1, int((self.available_rub / self.max_rub).to_integral_value()))

    def covers(self, quote_rub: Decimal) -> bool:
        return self.min_rub <= quote_rub <= self.max_rub and self.available_rub >= quote_rub


@dataclass(frozen=True)
class RekiSection:
    sub_token: str
    count: int
    total_rub: Decimal
    bands: tuple[RekiBand, ...] = ()


@dataclass(frozen=True)
class RekiSnapshot:
    sections: dict[str, RekiSection] = field(default_factory=dict)
    taken_at: datetime | None = None

    @property
    def empty(self) -> bool:
        return not any(section.bands for section in self.sections.values())

    def section(self, sub_token: str) -> RekiSection | None:
        return self.sections.get((sub_token or "").upper())

    def bands(self, sub_token: str) -> tuple[RekiBand, ...]:
        section = self.section(sub_token)
        return section.bands if section else ()

    def is_fresh(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: datetime | None = None) -> bool:
        if self.taken_at is None or self.empty:
            return False
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        taken = self.taken_at
        if taken.tzinfo is None:
            taken = taken.replace(tzinfo=timezone.utc)
        return current - taken <= timedelta(seconds=max(0, int(ttl_seconds)))


def _section_token(raw: str) -> str | None:
    name = (raw or "").strip().lower()
    for key, token in _SECTION_METHODS.items():
        if key in name:
            return token
    return None


def parse_reki_snapshot(text: str, *, taken_at: datetime | None = None) -> RekiSnapshot:
    """Разбирает ответ бота. Мусор и неизвестные строки просто пропускаем."""
    sections: dict[str, RekiSection] = {}
    token: str | None = None
    count = 0
    total = Decimal("0.00")
    bands: list[RekiBand] = []
    pending: tuple[Decimal, Decimal] | None = None

    def flush() -> None:
        if token is None:
            return
        sections[token] = RekiSection(
            sub_token=token,
            count=count,
            total_rub=total,
            bands=tuple(bands),
        )

    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw:
            continue

        section = _SECTION_RE.search(raw)
        if section:
            flush()
            token = _section_token(section.group(1))
            count = int(section.group(2))
            total = Decimal("0.00")
            bands = []
            pending = None
            continue

        if token is None:
            continue

        total_match = _TOTAL_RE.search(raw)
        if total_match:
            value = _amount(total_match.group(1))
            if value is not None:
                total = value
            continue

        band_match = _BAND_RE.search(raw)
        if band_match:
            low = _amount(band_match.group(1))
            high = _amount(band_match.group(2))
            pending = (low, high) if low is not None and high is not None and high >= low else None
            continue

        available_match = _AVAILABLE_RE.search(raw)
        if available_match and pending is not None:
            value = _amount(available_match.group(1))
            if value is not None and value > 0:
                bands.append(RekiBand(min_rub=pending[0], max_rub=pending[1], available_rub=value))
            pending = None

    flush()
    return RekiSnapshot(sections=sections, taken_at=taken_at)


FIT_EXACT = "exact"
FIT_TOP_UP = "top_up"
FIT_OVER_PAY = "over_pay"
FIT_NONE = "none"


@dataclass(frozen=True)
class RekiFit:
    kind: str
    quote_rub: Decimal
    pay_rub: Decimal
    diff_rub: Decimal = Decimal("0.00")
    band: RekiBand | None = None

    @property
    def found(self) -> bool:
        return self.kind != FIT_NONE


def fit_reki(
    snapshot: RekiSnapshot | None,
    sub_token: str,
    quote_rub,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> RekiFit:
    """Коридор под сумму: точный, с доплатой с баланса или с переплатой на баланс."""
    quote = Decimal(str(quote_rub or 0)).quantize(Decimal("0.01"))
    empty = RekiFit(FIT_NONE, quote, quote)
    if quote <= 0 or snapshot is None:
        return empty
    if not snapshot.is_fresh(ttl_seconds=ttl_seconds, now=now):
        return empty

    bands = [b for b in snapshot.bands(sub_token) if b.available_rub > 0]
    if not bands:
        return empty

    covering = [b for b in bands if b.covers(quote)]
    if covering:
        chosen = min(covering, key=lambda b: (b.max_rub - b.min_rub, b.max_rub))
        return RekiFit(FIT_EXACT, quote, quote, Decimal("0.00"), chosen)

    below = [b for b in bands if b.max_rub < quote]
    above = [b for b in bands if b.min_rub > quote and b.available_rub >= b.min_rub]

    best_below = max(below, key=lambda b: (b.max_rub, -b.min_rub)) if below else None
    best_above = min(above, key=lambda b: (b.min_rub, b.max_rub)) if above else None

    gap_below = quote - best_below.max_rub if best_below else None
    gap_above = best_above.min_rub - quote if best_above else None

    if best_below is not None and (gap_above is None or gap_below <= gap_above):
        return RekiFit(FIT_TOP_UP, quote, best_below.max_rub, gap_below, best_below)
    if best_above is not None:
        return RekiFit(FIT_OVER_PAY, quote, best_above.min_rub, gap_above, best_above)
    return empty


def _money(value) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("1"))
    return f"{int(amount):,}".replace(",", " ")


def describe_band(band: RekiBand) -> str:
    return f"{_money(band.min_rub)} – {_money(band.max_rub)} ₽ (свободно {_money(band.available_rub)} ₽)"


def describe_fit(fit: RekiFit) -> str | None:
    """Короткая подсказка: какая сумма сейчас проходит. None — сказать нечего."""
    if fit.band is None or fit.kind in (FIT_NONE, FIT_EXACT):
        return None
    window = f"{_money(fit.band.min_rub)} – {_money(fit.band.max_rub)} ₽"
    if fit.kind == FIT_TOP_UP:
        return (
            f"Ближайшее свободное окно {window}: пройдёт сумма до "
            f"{_money(fit.pay_rub)} ₽ — это на {_money(fit.diff_rub)} ₽ меньше запрошенной."
        )
    return (
        f"Ближайшее свободное окно {window}: пройдёт сумма от "
        f"{_money(fit.pay_rub)} ₽ — это на {_money(fit.diff_rub)} ₽ больше запрошенной."
    )


def format_snapshot(snapshot: RekiSnapshot | None, *, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: datetime | None = None) -> str:
    """Текст для бота внештатников: коридоры по методам и возраст снимка."""
    if snapshot is None or snapshot.empty:
        return "Данных по свободным реквизитам нет. Попробуйте через пару минут."
    if not snapshot.is_fresh(ttl_seconds=ttl_seconds, now=now):
        return "Снимок наличия устарел. Попробуйте через пару минут."

    lines: list[str] = []
    for token in (SUB_TOKEN_SBP, SUB_TOKEN_CARD):
        section = snapshot.section(token)
        if section is None or not section.bands:
            continue
        title = SUB_TOKEN_TITLES.get(token, token)
        lines.append(f"<b>{title}</b> · активных {section.count} · всего {_money(section.total_rub)} ₽")
        for band in section.bands:
            lines.append(f"• {describe_band(band)}")
        lines.append("")
    if not lines:
        return "Данных по свободным реквизитам нет. Попробуйте через пару минут."

    taken = snapshot.taken_at
    if taken is not None:
        stamp = taken.astimezone(timezone.utc).strftime("%H:%M UTC")
        lines.append(f"Данные на {stamp}.")
    return "\n".join(lines).strip()


def reki_public_out(
    snapshot: RekiSnapshot | None,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict:
    """JSON наличия для кабинета: агрегаты по коридорам, без номеров."""
    taken_at = snapshot.taken_at if snapshot else None
    fresh = bool(snapshot and snapshot.is_fresh(ttl_seconds=ttl_seconds, now=now))
    sections = []
    for token in (SUB_TOKEN_SBP, SUB_TOKEN_CARD):
        section = snapshot.section(token) if snapshot else None
        sections.append(
            {
                "sub_token": token,
                "title": SUB_TOKEN_TITLES.get(token, token),
                "count": int(section.count) if section else 0,
                "total_rub": float(section.total_rub) if section else 0.0,
                "bands": [
                    {
                        "min_rub": float(band.min_rub),
                        "max_rub": float(band.max_rub),
                        "available_rub": float(band.available_rub),
                    }
                    for band in (section.bands if section else ())
                ],
            }
        )
    return {
        "sections": sections,
        "snapshot_at": taken_at.isoformat() if taken_at else None,
        "stale": not fresh,
        "ttl_seconds": int(ttl_seconds),
    }


def ops_summary_line(snapshot: RekiSnapshot | None, *, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: datetime | None = None) -> str | None:
    """Строка для ops-уведомления «реки заняты» — видно расхождение с выдачей."""
    if snapshot is None or not snapshot.is_fresh(ttl_seconds=ttl_seconds, now=now):
        return None
    parts: list[str] = []
    for token in (SUB_TOKEN_SBP, SUB_TOKEN_CARD):
        section = snapshot.section(token)
        if section is None or not section.bands:
            continue
        title = SUB_TOKEN_TITLES.get(token, token)
        parts.append(f"{_money(section.total_rub)} ₽ {title}")
    if not parts:
        return None
    taken = snapshot.taken_at
    stamp = taken.astimezone(timezone.utc).strftime("%H:%M UTC") if taken else "—"
    return f"ℹ️ По /reki свободно: {' / '.join(parts)} (на {stamp})"

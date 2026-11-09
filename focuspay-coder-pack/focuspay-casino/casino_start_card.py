"""Генерация безопасной PNG-карточки профиля FocusCasino."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from io import BytesIO
from pathlib import Path
import re
from typing import Mapping
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = (1200, 675)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
_CURRENCY = "₽"
_MAX_TEXT_LENGTH = 32
_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class CasinoStartCardData:
    """Данные, уже безопасные для отображения на карточке."""

    player_name: str
    available_balance: str
    weekly_turnover: str
    eligible_loss: str
    cashback_tier: str
    estimated_cashback: str
    wagering_remaining: str
    next_tier_progress: str | None
    countdown: str


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _decimal(value: object) -> Decimal:
    """Вернуть неотрицательное конечное число или ноль."""
    if isinstance(value, bool):
        return Decimal("0")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return number if number.is_finite() and number >= 0 else Decimal("0")


def _money(value: object) -> str:
    amount = _decimal(value).quantize(Decimal("0.01"))
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {_CURRENCY}"


def _percent(value: object) -> str:
    if isinstance(value, str) and value.strip() and not _decimal(value):
        # Не подставляем произвольный текст профиля на изображение.
        return "0,00%"
    return f"{_decimal(value).quantize(Decimal('0.01')):.2f}".replace(".", ",") + "%"


def _safe_text(value: object) -> str:
    """Подготовить имя для изображения, не используя HTML-разметку."""
    if not isinstance(value, str):
        return ""
    text = _CONTROL_RE.sub(" ", _TAG_RE.sub("", unescape(value))).strip()
    return text[:_MAX_TEXT_LENGTH]


def _player_name(player: Mapping[str, object]) -> str:
    name = _safe_text(player.get("name"))
    if name and not name.isdecimal():
        return name
    username = _safe_text(player.get("username")).lstrip("@")
    if username and not username.isdecimal():
        return f"@{username}"
    return "Игрок"


def next_monday_0600(now: datetime | None = None) -> datetime:
    """Вернуть ближайший будущий понедельник 06:00 по Москве."""
    current = now or datetime.now(MOSCOW_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW_TZ)
    else:
        current = current.astimezone(MOSCOW_TZ)
    target = current.replace(hour=6, minute=0, second=0, microsecond=0)
    days_until_monday = (-current.weekday()) % 7
    target += timedelta(days=days_until_monday)
    if target <= current:
        target += timedelta(days=7)
    return target


def countdown_to_next_monday_0600(now: datetime | None = None) -> str:
    """Вернуть русскую строку с оставшимся временем до недельного расчёта."""
    current = now or datetime.now(MOSCOW_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW_TZ)
    else:
        current = current.astimezone(MOSCOW_TZ)
    seconds = max(0, int((next_monday_0600(current) - current).total_seconds()))
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes = seconds // 60
    return f"{days} дн. {hours:02d}:{minutes:02d}"


def build_card_data(
    player: Mapping[str, object] | None,
    casino_profile: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> CasinoStartCardData:
    """Собрать отображаемые данные из неполного ответа casino profile без I/O."""
    player_data = _as_mapping(player)
    profile = _as_mapping(casino_profile)
    week = _as_mapping(profile.get("current_week"))
    wagering = _as_mapping(profile.get("wagering"))
    progress = _as_mapping(week.get("progress"))

    tier_value = week.get("tier")
    if tier_value is None:
        tier_value = week.get("cashback_percent")

    next_tier_progress: str | None = None
    if progress.get("next_threshold_rub") is not None:
        remaining = progress.get("remaining_wager_rub", progress.get("next_threshold_rub"))
        next_tier_progress = (
            f"Осталось {_money(remaining)} до {_percent(progress.get('next_cashback_percent'))}"
        )

    return CasinoStartCardData(
        player_name=_player_name(player_data),
        available_balance=_money(profile.get("available_rub")),
        weekly_turnover=_money(week.get("wager_rub")),
        eligible_loss=_money(week.get("loss_rub")),
        cashback_tier=_percent(tier_value),
        estimated_cashback=_money(week.get("estimated_cashback_rub")),
        wagering_remaining=_money(wagering.get("remaining_rub")),
        next_tier_progress=next_tier_progress,
        countdown=countdown_to_next_monday_0600(now),
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for directory in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
        path = Path(directory, filename)
        if path.exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=22, fill="#171C31", outline="#303856", width=2)


def render_card(data: CasinoStartCardData) -> bytes:
    """Отрисовать карточку фиксированного размера и вернуть PNG-байты."""
    image = Image.new("RGB", CARD_SIZE, "#090B16")
    draw = ImageDraw.Draw(image)
    title_font = _font(42, bold=True)
    name_font = _font(28, bold=True)
    label_font = _font(18)
    value_font = _font(29, bold=True)
    small_font = _font(20)

    draw.rounded_rectangle((24, 22, 1176, 653), radius=30, fill="#101429", outline="#414D7C", width=2)
    draw.ellipse((1010, 42, 1140, 172), fill="#6126B8")
    draw.text((64, 58), "FOCUSCASINO", font=title_font, fill="#F7F3FF")
    draw.text((65, 115), data.player_name, font=name_font, fill="#AFBCE8")
    draw.text((64, 164), "ВАШ СТАТУС НА ЭТОЙ НЕДЕЛЕ", font=label_font, fill="#7885B5")

    fields = (
        ("ДОСТУПНЫЙ БАЛАНС", data.available_balance),
        ("ОБОРОТ ЗА НЕДЕЛЮ", data.weekly_turnover),
        ("ELIGIBLE-ПРОИГРЫШ", data.eligible_loss),
        ("КЕШБЭК / TIER", data.cashback_tier),
        ("ОЖИДАЕМЫЙ КЕШБЭК", data.estimated_cashback),
        ("НУЖНО ПОСТАВИТЬ", data.wagering_remaining),
    )
    for index, (label, value) in enumerate(fields):
        column, row = index % 3, index // 3
        left = 64 + column * 370
        top = 213 + row * 126
        _rounded_panel(draw, (left, top, left + 336, top + 104))
        draw.text((left + 18, top + 16), label, font=label_font, fill="#8F9BC5")
        draw.text((left + 18, top + 48), value, font=value_font, fill="#FFFFFF")

    progress = data.next_tier_progress or "Максимальный tier на текущую неделю"
    _rounded_panel(draw, (64, 487, 1136, 554))
    draw.text((84, 507), "СЛЕДУЮЩИЙ TIER", font=label_font, fill="#8F9BC5")
    draw.text((300, 504), progress, font=small_font, fill="#D9DFFF")
    draw.text((64, 593), "До следующего расчёта: " + data.countdown, font=small_font, fill="#AFBCE8")
    draw.text((1136, 593), "Пн 06:00 МСК", anchor="ra", font=small_font, fill="#7885B5")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate_start_card(
    player: Mapping[str, object] | None,
    casino_profile: Mapping[str, object] | None,
    *,
    now: datetime | None = None,
) -> bytes:
    """Собрать данные и сгенерировать PNG-карточку FocusCasino."""
    return render_card(build_card_data(player, casino_profile, now=now))

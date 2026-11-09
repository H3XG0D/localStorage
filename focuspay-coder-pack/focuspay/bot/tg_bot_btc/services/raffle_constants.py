"""FocusLucky raffle constants and helpers."""

from __future__ import annotations

PRIZE_PLACES_COUNT = 20

DEFAULT_PRIZE_PLACES: list[dict] = [
    {"place": 1, "prize_rub": 5000, "payout_method": "balance"},
    {"place": 2, "prize_rub": 3000, "payout_method": "balance"},
    {"place": 3, "prize_rub": 2000, "payout_method": "balance"},
    {"place": 4, "prize_rub": 1000, "payout_method": "balance"},
    {"place": 5, "prize_rub": 1000, "payout_method": "balance"},
    {"place": 6, "prize_rub": 500, "payout_method": "balance"},
    {"place": 7, "prize_rub": 500, "payout_method": "balance"},
    {"place": 8, "prize_rub": 500, "payout_method": "balance"},
    {"place": 9, "prize_rub": 500, "payout_method": "balance"},
    {"place": 10, "prize_rub": 500, "payout_method": "balance"},
]

FOCUS_LUCKY_MENU = "🍀 FocusLucky"
KIND_OWN = "own"
KIND_REFERRAL = "referral"
CAMPAIGN_DURATION_DAYS = 30
DRAW_HOUR_MSK = 20

DEFAULT_INFO_TEXT = (
    "+1 билет за каждые 1 000 ₽ вашего обмена\n"
    "+1 билет за каждые 3 000 ₽ обменов ваших друзей"
)

DEFAULT_HOW_TO_TEXT = (
    "<b>Как получить билеты FocusLucky</b>\n\n"
    "• <b>+1 билет</b> за каждые <b>1 000 ₽</b> вашего обмена\n"
    "• <b>+1 билет</b> за каждые <b>3 000 ₽</b> обменов ваших друзей "
    "по реферальной ссылке\n\n"
    "Билеты начисляются автоматически после успешного обмена.\n"
    "У каждого билета есть уникальный номер."
)


def get_default_info_text() -> str:
    return DEFAULT_INFO_TEXT


def get_default_how_to_text() -> str:
    return DEFAULT_HOW_TO_TEXT


def resolve_info_text(campaign: dict | None) -> str:
    if campaign and campaign.get("info_text"):
        return str(campaign["info_text"])
    return get_default_info_text()


def resolve_how_to_text(campaign: dict | None) -> str:
    if campaign and campaign.get("how_to_text"):
        return str(campaign["how_to_text"])
    return get_default_how_to_text()


def format_place_label(place: int) -> str:
    return f"{int(place)} место"


def format_place_range_label(from_place: int, to_place: int) -> str:
    if int(from_place) == int(to_place):
        return format_place_label(from_place)
    return f"{int(from_place)}–{int(to_place)} место"


def format_prize_rub(amount: float | int) -> str:
    return f"{int(float(amount)):,} ₽".replace(",", " ")


def format_payout_label(method: str) -> str:
    if (method or "").lower() == "ltc":
        return "LTC"
    return "баланс"


def format_prize_line(
    from_place: int,
    to_place: int,
    prize_rub: float | int,
    payout_method: str,
) -> str:
    return (
        f"<b>{format_place_range_label(from_place, to_place)}</b> — "
        f"{format_prize_rub(prize_rub)} ({format_payout_label(payout_method)})"
    )


def format_prizes_block(prize_places: list[dict] | None = None) -> str:
    places = prize_places if prize_places else DEFAULT_PRIZE_PLACES
    sorted_places = sorted(places, key=lambda p: int(p["place"]))
    lines = ["🏆 <b>Призы:</b>"]
    i = 0
    while i < len(sorted_places):
        start = sorted_places[i]
        from_place = int(start["place"])
        prize_rub = start.get("prize_rub", 0)
        payout_method = str(start.get("payout_method", "balance"))
        to_place = from_place
        j = i + 1
        while j < len(sorted_places):
            nxt = sorted_places[j]
            if (
                int(nxt["place"]) == to_place + 1
                and float(nxt.get("prize_rub", 0)) == float(prize_rub)
                and str(nxt.get("payout_method", "balance")) == payout_method
            ):
                to_place = int(nxt["place"])
                j += 1
            else:
                break
        lines.append(format_prize_line(from_place, to_place, prize_rub, payout_method))
        i = j
    return "\n".join(lines)


def format_winner_line(
    place: int,
    winning_ticket_no: int,
    prize_rub: float | int,
    payout_method: str,
) -> str:
    return (
        f"<b>{format_place_label(place)}</b> · билет #{winning_ticket_no} — "
        f"{format_prize_rub(prize_rub)} ({format_payout_label(payout_method)})"
    )


def win_chance_pct(user_tickets: int, pool_total_active: int) -> float:
    if pool_total_active <= 0 or user_tickets <= 0:
        return 0.0
    return min(100.0, round((user_tickets / pool_total_active) * 100, 1))


def format_chance_pct(pct: float) -> str:
    if pct <= 0:
        return "0%"
    if pct == int(pct):
        return f"{int(pct)}%"
    return f"{pct:g}%"


def format_ticket_numbers(ranges: list[dict], *, max_show: int = 20) -> str:
    """Format ticket ranges for display."""
    if not ranges:
        return "—"
    parts: list[str] = []
    total = 0
    for r in ranges:
        f, t, c = int(r["ticket_no_from"]), int(r["ticket_no_to"]), int(r["ticket_count"])
        total += c
        if f == t:
            parts.append(f"#{f}")
        else:
            parts.append(f"#{f}–#{t}")
    if total <= 3:
        return ", ".join(parts)
    if total <= max_show:
        return f"{', '.join(parts)} ({total} шт.)"
    first = ranges[0]
    last = ranges[-1]
    return f"#{first['ticket_no_from']}–#{last['ticket_no_to']} ({total} шт.)"

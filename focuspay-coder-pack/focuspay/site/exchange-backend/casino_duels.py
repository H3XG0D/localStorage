"""Public duel lobby helpers. No raw creator_id in client payloads; chips use actor.user_id."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from casino_cards import (
    CARD_GAME_TYPES,
    baccarat_card_value,
    baccarat_hand_score,
    blackjack_card_value,
    blackjack_hand_score,
    is_standard_card,
)
from casino_finance import CasinoSettings, calculate_equal_stake_settlement, money

PUBLIC_HAND_STATUSES = frozenset(
    {"finished", "released", "settled", "completed", "outcome_committed"}
)
DUEL_ROOM_COLUMNS = (
    "game_id, game_type, bet_rub, created_at, creator_id, opponent_id, "
    "status, game_state, outcome, game_data"
)
DUEL_ROOM_SELECT_SQL = f"SELECT {DUEL_ROOM_COLUMNS} FROM casino_games WHERE game_id = $1"
DUEL_ROOM_SELECT_TYPED_SQL = (
    f"{DUEL_ROOM_SELECT_SQL} AND game_type = ANY($2::text[])"
)

BAND_LOW = "low"
BAND_MID = "mid"
BAND_HIGH = "high"
BAND_ORDER = (BAND_LOW, BAND_MID, BAND_HIGH)
BAND_LABEL = {
    BAND_LOW: "До 500 ₽",
    BAND_MID: "500–5000 ₽",
    BAND_HIGH: "Свыше 5000 ₽",
}
# Fallback when there is no history. High stakes go stale around 15 minutes.
DEFAULT_ETA_SECONDS = {BAND_LOW: 120, BAND_MID: 300, BAND_HIGH: 900}

WAITING_DUELS_SQL = """
    SELECT game_id, game_type, bet_rub, created_at, creator_id, opponent_id, status, game_state, outcome
    FROM casino_games
    WHERE status = 'waiting' AND opponent_id IS NULL
      AND game_type = ANY($1::text[])
      AND COALESCE(game_state->>'reserved_opponent_id', '') = ''
    ORDER BY created_at ASC
    LIMIT 100
"""

async def waiting_duels(conn, viewer_id: int | None):
    """Открытые дуэли только своей области: рубли и фишки в разных лобби."""
    from casino_finance import HEAD_TO_HEAD_GAME_TYPES
    from casino_wallet import scope_or_mine_filter, viewer_scope

    # Свою заявку видно всегда, иначе после смены кошелька её не отменить.
    scope_and = await scope_or_mine_filter(
        conn,
        "casino_games",
        await viewer_scope(conn, viewer_id),
        mine_sql="creator_id = $2",
    )
    if not scope_and:
        return await conn.fetch(WAITING_DUELS_SQL, list(HEAD_TO_HEAD_GAME_TYPES))
    sql = WAITING_DUELS_SQL.replace(
        "ORDER BY created_at ASC", f"{scope_and}\n    ORDER BY created_at ASC"
    )
    return await conn.fetch(sql, list(HEAD_TO_HEAD_GAME_TYPES), int(viewer_id or 0))


FILL_SAMPLES_SQL = """
    SELECT bet_rub, EXTRACT(EPOCH FROM (started_at - created_at)) AS wait_s
    FROM casino_games
    WHERE started_at IS NOT NULL
      AND started_at >= created_at
      AND created_at > now() - interval '7 days'
      AND game_type = ANY($1::text[])
"""


def duel_stake_band(bet_rub: Decimal | int | float | str) -> str:
    stake = money(bet_rub)
    if stake < Decimal("500"):
        return BAND_LOW
    if stake <= Decimal("5000"):
        return BAND_MID
    return BAND_HIGH


def _as_map(value: object) -> dict[str, object]:
    """asyncpg returns jsonb as str unless a codec is registered."""
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")


def _str_cards(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if is_standard_card(text):
            out.append(text)
    return out


def _cards_from_maps(*sources: Mapping[str, object] | None, key: str) -> list[str]:
    for source in sources:
        if not source:
            continue
        cards = _str_cards(source.get(key))
        if cards:
            return cards
    return []


def _stored_duel_hands(row: Mapping[str, object]) -> tuple[list[str], list[str]]:
    outcome = _as_map(row.get("outcome"))
    state = _as_map(row.get("game_state"))
    rng = _as_map(_as_map(row.get("game_data")).get("card_rng"))
    creator = _cards_from_maps(outcome, rng, state, key="creator_cards") or _str_cards(
        state.get("cards_creator")
    )
    opponent = _cards_from_maps(outcome, rng, state, key="opponent_cards") or _str_cards(
        state.get("cards_opponent")
    )
    return creator, opponent


def public_duel_hands(
    row: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    """Faces only after the round is public. Waiting/active rooms stay backs."""
    status = str(row.get("status") or "").strip().lower()
    if status not in PUBLIC_HAND_STATUSES:
        return [], []
    return _stored_duel_hands(row)


def pov_duel_hands(
    row: Mapping[str, object],
    *,
    viewer_id: int | None,
) -> tuple[list[str], list[str]]:
    """Own face during an active seat; everyone else stays backs until public status."""
    public_creator, public_opponent = public_duel_hands(row)
    if public_creator or public_opponent:
        return public_creator, public_opponent
    status = str(row.get("status") or "").strip().lower()
    if status not in {"active", "outcome_committed"} or viewer_id is None:
        return [], []
    creator, opponent = _stored_duel_hands(row)
    try:
        creator_id = int(row["creator_id"])
    except (TypeError, ValueError, KeyError):
        return [], []
    if int(viewer_id) == creator_id:
        return creator, []
    opponent_id = row.get("opponent_id")
    if opponent_id is not None and int(opponent_id) == int(viewer_id):
        return [], opponent
    return [], []


def sequential_card_reveal_steps(
    creator_cards: Sequence[str],
    opponent_cards: Sequence[str],
    *,
    game_type: str,
) -> list[dict[str, object]]:
    """One seat per step. Same alternating deal as dice: creator then opponent each index."""
    score_fn = blackjack_hand_score if game_type == "blackjack" else baccarat_hand_score
    pip_fn = blackjack_card_value if game_type == "blackjack" else baccarat_card_value
    shown_creator: list[str] = []
    shown_opponent: list[str] = []
    steps: list[dict[str, object]] = []
    rounds = max(len(creator_cards), len(opponent_cards))
    for index in range(rounds):
        if index < len(creator_cards):
            shown_creator.append(creator_cards[index])
            steps.append(
                _reveal_step(
                    "creator",
                    pip_fn(creator_cards[index]),
                    index,
                    score_fn(shown_creator),
                    score_fn(shown_opponent),
                    card=creator_cards[index],
                    game_type=game_type,
                )
            )
        if index < len(opponent_cards):
            shown_opponent.append(opponent_cards[index])
            steps.append(
                _reveal_step(
                    "opponent",
                    pip_fn(opponent_cards[index]),
                    index,
                    score_fn(shown_creator),
                    score_fn(shown_opponent),
                    card=opponent_cards[index],
                    game_type=game_type,
                )
            )
    return steps


def _int_rolls(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 99:
            out.append(number)
    return out


def net_payout_for_stake(settings: CasinoSettings, bet_rub: Decimal | int | float | str) -> tuple[Decimal, Decimal, Decimal]:
    """Return (bank, commission, net payout). Payout is not the gross pot."""
    stake = money(bet_rub)
    settlement = calculate_equal_stake_settlement(
        stake,
        settings.commission_rate_wagering_complete,
        commission_cap_rub=settings.commission_cap_rub,
        commission_min_rub=settings.commission_min_rub,
    )
    return settlement.pot, settlement.commission, settlement.payout


def build_duel_card(
    row: Mapping[str, object],
    settings: CasinoSettings,
    *,
    viewer_id: int | None = None,
) -> dict[str, object]:
    stake = money(row["bet_rub"])
    bank, commission, payout = net_payout_for_stake(settings, stake)
    creator_id = int(row["creator_id"])
    opponent_id = row.get("opponent_id")
    occupied = opponent_id is not None
    card = {
        "game_id": str(row["game_id"]),
        "game_type": str(row["game_type"]),
        "bet_rub": float(stake),
        "bank_rub": float(bank),
        "commission_rub": float(commission),
        "net_payout_rub": float(payout),
        "opened_at": _iso(row.get("created_at")),
        "band": duel_stake_band(stake),
        "status": str(row.get("status") or "waiting"),
        "opponent_occupied": bool(occupied),
        "is_mine": bool(viewer_id is not None and viewer_id == creator_id),
        "is_joined": bool(
            viewer_id is not None
            and occupied
            and int(opponent_id) == viewer_id
        ),
        "creator": None,
        "opponent": None,
    }
    return card


def sequential_reveal_steps(
    game_state: Mapping[str, object] | None,
    *,
    outcome: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """One seat per step. Never emit both participants in a single step."""
    state = game_state or {}
    creator = _int_rolls(state.get("creator_rolls"))
    opponent = _int_rolls(state.get("opponent_rolls"))
    steps: list[dict[str, object]] = []
    creator_sum = 0
    opponent_sum = 0
    rounds = max(len(creator), len(opponent))
    for index in range(rounds):
        if index < len(creator):
            creator_sum += creator[index]
            steps.append(_reveal_step("creator", creator[index], index, creator_sum, opponent_sum))
        if index < len(opponent):
            opponent_sum += opponent[index]
            steps.append(_reveal_step("opponent", opponent[index], index, creator_sum, opponent_sum))
    if not steps and outcome:
        winner = outcome.get("winner_seat") or outcome.get("winner")
        if winner in {"creator", "opponent"}:
            steps.append(
                {
                    "seat": str(winner),
                    "value": None,
                    "index": 0,
                    "creator_sum": 0,
                    "opponent_sum": 0,
                    "leader": str(winner),
                }
            )
    return steps


def _card_leader(game_type: str, creator_sum: int, opponent_sum: int) -> str | None:
    if game_type == "blackjack":
        creator_ok = creator_sum <= 21
        opponent_ok = opponent_sum <= 21
        if creator_ok and opponent_ok:
            if creator_sum == opponent_sum:
                return None
            return "creator" if creator_sum > opponent_sum else "opponent"
        if creator_ok:
            return "creator"
        if opponent_ok:
            return "opponent"
        return None
    if creator_sum == opponent_sum:
        return None
    return "creator" if creator_sum > opponent_sum else "opponent"


def _reveal_step(
    seat: str,
    value: int,
    index: int,
    creator_sum: int,
    opponent_sum: int,
    *,
    card: str | None = None,
    game_type: str | None = None,
) -> dict[str, object]:
    if game_type:
        leader = _card_leader(game_type, creator_sum, opponent_sum)
    elif creator_sum == opponent_sum:
        leader = None
    elif creator_sum > opponent_sum:
        leader = "creator"
    else:
        leader = "opponent"
    step: dict[str, object] = {
        "seat": seat,
        "value": value,
        "index": index,
        "creator_sum": creator_sum,
        "opponent_sum": opponent_sum,
        "leader": leader,
    }
    if card:
        step["card"] = card
    return step


def reserved_opponent_of(row: Mapping[str, object]) -> int | None:
    state = _as_map(row.get("game_state"))
    raw = state.get("reserved_opponent_id")
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value else None


def pick_autojoin_target(
    waiting: Sequence[Mapping[str, object]],
    *,
    game_type: str,
    stake_rub: Decimal | int | float | str,
    viewer_id: int,
) -> Mapping[str, object] | None:
    """Oldest waiting duel with the same type and exact stake, not owned by the viewer."""
    want = money(stake_rub)
    matches = [
        row
        for row in waiting
        if str(row["game_type"]) == game_type
        and money(row["bet_rub"]) == want
        and int(row["creator_id"]) != viewer_id
        and row.get("opponent_id") is None
        and str(row.get("status") or "waiting") == "waiting"
        and reserved_opponent_of(row) is None
    ]
    if not matches:
        return None

    def sort_key(row: Mapping[str, object]) -> datetime:
        opened = row.get("created_at")
        if isinstance(opened, datetime):
            return opened
        return datetime.max.replace(tzinfo=timezone.utc)

    return sorted(matches, key=sort_key)[0]


def fill_eta_seconds(sample_seconds: Sequence[float], *, fallback: int) -> int:
    values = [max(0.0, float(item)) for item in sample_seconds if item is not None]
    if not values:
        return fallback
    ordered = sorted(values)
    return int(round(ordered[len(ordered) // 2]))


def fill_label(*, eta_seconds: int | None, oldest_wait_seconds: int | None, open_count: int) -> str:
    if open_count == 0:
        if eta_seconds:
            return f"обычно ~{_human_minutes(eta_seconds)}"
        return "очередь пустая — создай первую"
    if oldest_wait_seconds is not None and oldest_wait_seconds >= 15 * 60:
        return f"ждут уже {_human_minutes(oldest_wait_seconds)} — очередь стынет"
    if eta_seconds:
        return f"обычно заполняется за ~{_human_minutes(eta_seconds)}"
    return f"открыто {open_count}"


def _human_minutes(seconds: int) -> str:
    minutes = max(1, int(round(seconds / 60)))
    if minutes % 10 == 1 and minutes % 100 != 11:
        unit = "минуту"
    elif 2 <= minutes % 10 <= 4 and not (12 <= minutes % 100 <= 14):
        unit = "минуты"
    else:
        unit = "минут"
    return f"{minutes} {unit}"


def group_duel_cards(cards: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    buckets: dict[str, list[Mapping[str, object]]] = {band: [] for band in BAND_ORDER}
    for card in cards:
        band = str(card.get("band") or duel_stake_band(card.get("bet_rub") or 0))
        buckets.setdefault(band, []).append(card)
    grouped: list[dict[str, object]] = []
    for band in BAND_ORDER:
        items = list(buckets.get(band) or [])
        grouped.append(
            {
                "band": band,
                "label": BAND_LABEL[band],
                "duels": items,
            }
        )
    return grouped


def _wait_seconds(created_at: object, now: datetime | None = None) -> int | None:
    if not isinstance(created_at, datetime):
        return None
    clock = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(0, int((clock - created_at).total_seconds()))


def assemble_duels_payload(
    settings: CasinoSettings,
    waiting: Sequence[Mapping[str, object]],
    fill_samples: Sequence[Mapping[str, object]],
    *,
    viewer_id: int | None = None,
) -> dict[str, object]:
    cards = [build_duel_card(row, settings, viewer_id=viewer_id) for row in waiting]
    samples_by_band: dict[str, list[float]] = {band: [] for band in BAND_ORDER}
    for sample in fill_samples:
        try:
            band = duel_stake_band(sample["bet_rub"])
            samples_by_band[band].append(float(sample["wait_s"]))
        except (KeyError, TypeError, ValueError):
            continue
    grouped = []
    for bucket in group_duel_cards(cards):
        band = str(bucket["band"])
        items = list(bucket["duels"])
        waits = [
            seconds
            for seconds in (_wait_seconds(row.get("created_at")) for row in waiting if duel_stake_band(row["bet_rub"]) == band)
            if seconds is not None
        ]
        oldest = max(waits) if waits else None
        eta = fill_eta_seconds(samples_by_band[band], fallback=DEFAULT_ETA_SECONDS[band])
        grouped.append(
            {
                **bucket,
                "open_count": len(items),
                "eta_seconds": eta,
                "oldest_wait_seconds": oldest,
                "fill_label": fill_label(eta_seconds=eta, oldest_wait_seconds=oldest, open_count=len(items)),
            }
        )
    return {
        "commission_percent": float(settings.commission_rate_wagering_complete),
        "min_bet_rub": float(settings.min_bet_rub),
        "max_bet_rub": float(settings.max_bet_rub),
        "groups": grouped,
    }


def build_duel_room(
    row: Mapping[str, object],
    settings: CasinoSettings,
    *,
    viewer_id: int | None = None,
) -> dict[str, object]:
    card = build_duel_card(row, settings, viewer_id=viewer_id)
    state_map = _as_map(row.get("game_state"))
    outcome_map = _as_map(row.get("outcome")) or None
    game_type = str(row.get("game_type") or "")
    steps = sequential_reveal_steps(state_map, outcome=outcome_map)
    creator_name = "Вы" if card["is_mine"] else "Игрок"
    opponent_name = (
        "Вы"
        if card["is_joined"]
        else ("место свободно" if not card["opponent_occupied"] else "Соперник")
    )
    payload: dict[str, object] = {
        **card,
        "steps": steps,
        "creator_label": creator_name,
        "opponent_label": opponent_name,
    }
    if game_type == "pvp_dice":
        from casino_pvp_dice import room_roll_fields

        payload.update(room_roll_fields(row, viewer_id=viewer_id))
    if game_type in CARD_GAME_TYPES:
        creator_cards, opponent_cards = pov_duel_hands(row, viewer_id=viewer_id)
        if creator_cards or opponent_cards:
            payload["steps"] = sequential_card_reveal_steps(
                creator_cards,
                opponent_cards,
                game_type=game_type,
            )
        payload["hands"] = {"creator": creator_cards, "opponent": opponent_cards}
    return payload


def bot_chip(
    display_name: str,
    *,
    profile_id: object = None,
    profile_key: object = None,
    seat_no: object = None,
) -> dict[str, object]:
    """House/PvP robot: nick + unique picture, user_id 0 so the chip is not a profile link."""
    from casino_default_avatar import default_avatar_public_url, robot_ident_seed

    name = (display_name or "").strip() or "Бот"
    initial = name.lstrip("@")[:1].upper() or "?"
    seed = robot_ident_seed(
        profile_id=profile_id,
        profile_key=profile_key,
        display_name=name,
        seat_no=seat_no,
    )
    return {
        "user_id": 0,
        "display_name": name,
        "initial": initial,
        "avatar_url": default_avatar_public_url(seed),
    }


def _robot_chip_from_row(row: Mapping[str, object]) -> dict[str, object] | None:
    robot = _as_map(_as_map(row.get("game_data")).get("robot_profile"))
    name = str(robot.get("display_name") or "").strip()
    if not name:
        return None
    return bot_chip(
        name,
        profile_id=robot.get("id") or robot.get("profile_id"),
        profile_key=robot.get("profile_key") or robot.get("key"),
    )


async def fill_duel_actors(
    conn,
    card: dict[str, object],
    row: Mapping[str, object],
) -> dict[str, object]:
    """Attach nick/avatar chips. Empty waiting seat stays null. Robots are not profile links."""
    from casino_chat import public_actors

    creator_id = int(row["creator_id"])
    opponent_raw = row.get("opponent_id")
    occupied = opponent_raw is not None
    ids = [creator_id]
    if occupied:
        ids.append(int(opponent_raw))
    actors = await public_actors(conn, ids)
    creator = actors.get(creator_id)
    opponent = actors.get(int(opponent_raw)) if occupied else _robot_chip_from_row(row)
    if opponent and not occupied:
        card["opponent_occupied"] = True
    card["creator"] = creator
    card["opponent"] = opponent
    if creator:
        if card.get("is_mine"):
            card["creator_label"] = "Вы"
        else:
            card["creator_label"] = str(creator.get("display_name") or "Игрок")
    if opponent:
        if card.get("is_joined"):
            card["opponent_label"] = "Вы"
        else:
            card["opponent_label"] = str(opponent.get("display_name") or "Соперник")
    elif not occupied:
        card["opponent_label"] = "место свободно"
    return card


async def fill_duels_payload_actors(
    conn,
    payload: Mapping[str, object],
    waiting: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    from casino_chat import public_actors

    ids: list[int] = []
    for row in waiting:
        ids.append(int(row["creator_id"]))
        if row.get("opponent_id") is not None:
            ids.append(int(row["opponent_id"]))
    actors = await public_actors(conn, ids)
    by_id = {str(row["game_id"]): row for row in waiting}
    out = dict(payload)
    groups = []
    for group in list(payload.get("groups") or []):
        next_group = dict(group)
        duels = []
        for card in list(group.get("duels") or []):
            item = dict(card)
            row = by_id.get(str(item.get("game_id") or ""))
            if row:
                creator_id = int(row["creator_id"])
                opponent_raw = row.get("opponent_id")
                item["creator"] = actors.get(creator_id)
                item["opponent"] = actors.get(int(opponent_raw)) if opponent_raw is not None else None
            else:
                item["creator"] = None
                item["opponent"] = None
            duels.append(item)
        next_group["duels"] = duels
        groups.append(next_group)
    out["groups"] = groups
    return out


"""European roulette 1×1 vs house: one HMAC pocket 0–36 decides the round.

Single zero wheel, 37 pockets. The pocket is HMAC-SHA256(server_seed,
client_seed:nonce:game_id:pocket) reduced mod 37 — never a client roll and never
a cub-style win threshold. Colour, wheel position and payout of every pocket come
from WHEEL_ORDER / RED_POCKETS / BLACK_POCKETS in this module; nothing else may
keep its own copy.

A stake covers N pockets and pays like a real table: total return is 36/N
(straight 1 pocket → ×36, split 2 → ×18, ten numbers → ×3.6). Named red/black
are the even-money 18-pocket bets (×2); zero is the 1-pocket 35:1. Arbitrary
sets are the same 36/N rule, one stake split equally, not ×36 per number.

Money uses calculate_house_settlement only. payout_multiplier is the total return
on the stake, so 1:1 is ×2 and 35:1 is ×36; a loss is ×0. The house reserves the
full multiplier of the chosen bet before the wheel is drawn.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from casino_cards import DEFAULT_CLIENT_SEED, commits_match, game_commit
from casino_finance import (
    HouseGameSettlement,
    allocate_commission,
    calculate_house_settlement,
    casino_ledger_order_ref,
    commission_shares_for_rate,
    confirm_unified_hold,
    game_stake_bounds,
    load_casino_settings,
    lock_casino_game,
    lock_casino_users,
    money,
    reserve_unified_funds,
)
from casino_house_cards import _consume_card_commit as consume_rng_commit
from casino_wagering import commission_profile_for_player, commission_rate_for_player

ROULETTE_GAME_TYPE = "roulette"
ROULETTE_ALGORITHM = "hmac-sha256-pocket-mod37"
ROULETTE_SIDE = "pocket"
POCKET_COUNT = 37
#: European felt: 36 units come back on a 1-pocket hit (35:1 plus the stake).
STRAIGHT_RETURN = Decimal(POCKET_COUNT - 1)
MAX_COVER = POCKET_COUNT - 1
#: Longest canonical key: 36 pockets as "0,1,…,35".
ROULETTE_BET_KEY_MAX_LENGTH = 120
HOUSE_BANKROLL_INSUFFICIENT = "Дом не может покрыть выплату по этой ставке"
ROBOT_STAKE_OUTSIDE_LIMITS = "Ставка вне лимита робота"

logger = logging.getLogger("casino_roulette")

RouletteColor = Literal["green", "red", "black"]

#: Physical single-zero wheel, clockwise from the green zero. Index in this tuple
#: is the pocket's wheel position — the renderer needs it, the payout does not.
WHEEL_ORDER: tuple[int, ...] = (
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34,
    6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18,
    29, 7, 28, 12, 35, 3, 26,
)

RED_POCKETS: frozenset[int] = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)
BLACK_POCKETS: frozenset[int] = frozenset(
    {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}
)
EVEN_POCKETS: frozenset[int] = frozenset(range(2, 37, 2))
ODD_POCKETS: frozenset[int] = frozenset(range(1, 37, 2))
LOW_POCKETS: frozenset[int] = frozenset(range(1, 19))
HIGH_POCKETS: frozenset[int] = frozenset(range(19, 37))
DOZEN1_POCKETS: frozenset[int] = frozenset(range(1, 13))
DOZEN2_POCKETS: frozenset[int] = frozenset(range(13, 25))
DOZEN3_POCKETS: frozenset[int] = frozenset(range(25, 37))
COL1_POCKETS: frozenset[int] = frozenset(range(1, 37, 3))
COL2_POCKETS: frozenset[int] = frozenset(range(2, 37, 3))
COL3_POCKETS: frozenset[int] = frozenset(range(3, 37, 3))

_WHEEL_POSITION: dict[int, int] = {pocket: index for index, pocket in enumerate(WHEEL_ORDER)}


@dataclass(frozen=True)
class RouletteBet:
    """One outside/straight bet the web round accepts."""

    key: str
    title_ru: str
    #: Total return on a win, stake included: 1:1 → 2, 35:1 → 36.
    payout_multiplier: Decimal
    #: Odds shown to the player, e.g. "1:1".
    odds_ru: str
    pockets: frozenset[int]

    @property
    def profit_ratio(self) -> Decimal:
        """Classic casino notation: profit per unit staked."""
        return self.payout_multiplier - Decimal("1")

    @property
    def win_probability(self) -> Decimal:
        return Decimal(len(self.pockets)) / Decimal(POCKET_COUNT)


ROULETTE_BETS: dict[str, RouletteBet] = {
    "red": RouletteBet("red", "Красное", Decimal("2"), "1:1", RED_POCKETS),
    "black": RouletteBet("black", "Чёрное", Decimal("2"), "1:1", BLACK_POCKETS),
    "zero": RouletteBet("zero", "Зеро", Decimal("36"), "35:1", frozenset({0})),
    "even": RouletteBet("even", "Чёт", Decimal("2"), "1:1", EVEN_POCKETS),
    "odd": RouletteBet("odd", "Нечет", Decimal("2"), "1:1", ODD_POCKETS),
    "low": RouletteBet("low", "1–18", Decimal("2"), "1:1", LOW_POCKETS),
    "high": RouletteBet("high", "19–36", Decimal("2"), "1:1", HIGH_POCKETS),
    "dozen1": RouletteBet("dozen1", "1–12", Decimal("3"), "2:1", DOZEN1_POCKETS),
    "dozen2": RouletteBet("dozen2", "13–24", Decimal("3"), "2:1", DOZEN2_POCKETS),
    "dozen3": RouletteBet("dozen3", "25–36", Decimal("3"), "2:1", DOZEN3_POCKETS),
    "col1": RouletteBet("col1", "Колонка 1", Decimal("3"), "2:1", COL1_POCKETS),
    "col2": RouletteBet("col2", "Колонка 2", Decimal("3"), "2:1", COL2_POCKETS),
    "col3": RouletteBet("col3", "Колонка 3", Decimal("3"), "2:1", COL3_POCKETS),
}
ROULETTE_COLOR_KEYS: tuple[str, ...] = ("red", "black", "zero")
ROULETTE_EVEN_MONEY_KEYS: tuple[str, ...] = ("even", "odd", "low", "high")
ROULETTE_DOZEN_KEYS: tuple[str, ...] = ("dozen1", "dozen2", "dozen3")
ROULETTE_COLUMN_KEYS: tuple[str, ...] = ("col1", "col2", "col3")
ROULETTE_BET_KEYS: tuple[str, ...] = (
    ROULETTE_COLOR_KEYS + ROULETTE_EVEN_MONEY_KEYS + ROULETTE_DOZEN_KEYS + ROULETTE_COLUMN_KEYS
)
DEFAULT_ROULETTE_BET = "red"
ROULETTE_BET_ALIASES: dict[str, str] = {
    "красное": "red",
    "красн": "red",
    "черное": "black",
    "чёрное": "black",
    "зеро": "zero",
    "чет": "even",
    "чётное": "even",
    "четное": "even",
    "нечет": "odd",
    "нечётное": "odd",
    "нечетное": "odd",
    "1-18": "low",
    "мало": "low",
    "19-36": "high",
    "много": "high",
    "1rd": "dozen1",
    "1-12": "dozen1",
    "2rd": "dozen2",
    "13-24": "dozen2",
    "3rd": "dozen3",
    "25-36": "dozen3",
    "1col": "col1",
    "2col": "col2",
    "3col": "col3",
}


def normalize_roulette_bet_key(bet: object) -> str:
    raw = str(bet or "").strip().lower().replace("ё", "е")
    return ROULETTE_BET_ALIASES.get(raw, raw)


def is_valid_pocket(pocket: object) -> bool:
    try:
        number = int(pocket)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return 0 <= number < POCKET_COUNT


def pocket_color(pocket: int) -> RouletteColor:
    number = int(pocket)
    if not is_valid_pocket(number):
        raise ValueError("pocket must be 0..36")
    if number == 0:
        return "green"
    return "red" if number in RED_POCKETS else "black"


def wheel_position(pocket: int) -> int:
    """Index of the pocket on the physical wheel, 0 for the green zero."""
    try:
        return _WHEEL_POSITION[int(pocket)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("pocket must be 0..36") from exc


def _odds_ru(cover: int) -> str:
    """Classic felt notation: profit per unit staked, e.g. 35:1 or 2.6:1."""
    profit = (STRAIGHT_RETURN - Decimal(cover)) / Decimal(cover)
    if profit == profit.to_integral_value():
        return f"{int(profit)}:1"
    text = format(profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    text = text.rstrip("0").rstrip(".")
    return f"{text}:1"


def _cover_word_ru(cover: int) -> str:
    if 11 <= cover % 100 <= 14:
        return "чисел"
    last = cover % 10
    if last == 1:
        return "число"
    if last in {2, 3, 4}:
        return "числа"
    return "чисел"


def _cover_title(pockets: Sequence[int]) -> str:
    items = [int(pocket) for pocket in pockets]
    count = len(items)
    if count == 1:
        return "Зеро" if items[0] == 0 else str(items[0])
    if count <= 6:
        return ", ".join(str(pocket) for pocket in items)
    return f"{count} {_cover_word_ru(count)}"


def canonical_roulette_bet_key(pockets: Sequence[int]) -> str:
    unique = sorted({int(pocket) for pocket in pockets})
    if unique == [0]:
        return "zero"
    if len(unique) == 1:
        return str(unique[0])
    return ",".join(str(pocket) for pocket in unique)


def _parse_pockets(bet: object) -> frozenset[int] | None:
    raw = str(bet or "").strip().lower()
    if not raw:
        return None
    named = ROULETTE_BETS.get(raw)
    if named is not None:
        return named.pockets
    tokens = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    if not tokens:
        return None
    pockets: set[int] = set()
    for token in tokens:
        if not token.isdigit():
            return None
        number = int(token)
        if token != str(number):
            return None
        if not (0 <= number < POCKET_COUNT):
            return None
        pockets.add(number)
    if not pockets or len(pockets) > MAX_COVER:
        return None
    return frozenset(pockets)


def _cover_bet(pockets: frozenset[int]) -> RouletteBet:
    """One stake covering N pockets. Return is 36/N, the European table rule."""
    cover = len(pockets)
    if cover == 0 or cover > MAX_COVER:
        raise HTTPException(
            status_code=400,
            detail="Ставка рулетки: от 1 до 36 чисел, не все 37 лунок",
        )
    for spec in ROULETTE_BETS.values():
        if spec.pockets == pockets:
            return spec
    ordered = tuple(sorted(pockets))
    multiplier = STRAIGHT_RETURN / Decimal(cover)
    return RouletteBet(
        canonical_roulette_bet_key(ordered),
        _cover_title(ordered),
        multiplier,
        _odds_ru(cover),
        pockets,
    )


def bet_spec(bet: object) -> RouletteBet:
    key = normalize_roulette_bet_key(bet)
    spec = ROULETTE_BETS.get(key)
    if spec is not None:
        return spec
    pockets = _parse_pockets(key)
    if pockets is not None:
        return _cover_bet(pockets)
    raise HTTPException(
        status_code=400,
        detail="Ставка рулетки: цвет, ряд, чёт/нечет, 1–18 или число 0–36",
    )


def bet_wins(bet: str, pocket: int) -> bool:
    return int(pocket) in bet_spec(bet).pockets


def payout_multiplier_for_bet(bet: str, pocket: int) -> Decimal:
    """Total return multiplier for a settled round. Loss is ×0, there is no push."""
    spec = bet_spec(bet)
    return spec.payout_multiplier if int(pocket) in spec.pockets else Decimal("0")


def pocket_message(*, client_seed: str, nonce: int, game_id: str) -> str:
    """HMAC message. Same shape as the card shoe, with a pocket side."""
    return f"{client_seed}:{int(nonce)}:{game_id}:{ROULETTE_SIDE}"


def roulette_pocket(
    seed: str,
    game_id: str,
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> int:
    """Draw the winning pocket 0–36 from the committed server seed."""
    message = pocket_message(client_seed=client_seed, nonce=nonce, game_id=game_id)
    digest = hmac.new(seed.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest, "big") % POCKET_COUNT


def resolve_roulette_round(
    *,
    seed: str,
    game_id: str,
    client_seed: str,
    nonce: int,
    stake_rub: Decimal,
    bet: str,
    commission_rate: Decimal,
    commission_cap_rub: Decimal = Decimal("0"),
    commission_min_rub: Decimal = Decimal("0"),
) -> dict[str, object]:
    """Pure round: pocket, colour, win flag and money. No DB, no side effects."""
    spec = bet_spec(bet)
    pocket = roulette_pocket(seed, game_id, client_seed=client_seed, nonce=nonce)
    won = bet_wins(spec.key, pocket)
    multiplier = payout_multiplier_for_bet(spec.key, pocket)
    settlement = calculate_house_settlement(
        stake_rub,
        multiplier,
        commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    return {
        "pocket": pocket,
        "color": pocket_color(pocket),
        "wheel_index": wheel_position(pocket),
        "bet": spec.key,
        "won": won,
        "payout_multiplier": multiplier,
        "settlement": settlement,
    }


def clamp_held_roulette_payout(settlement: HouseGameSettlement, reserved) -> HouseGameSettlement:
    """Pay at most the house reserve already held for this seat.

    Commission can drop between chip and settle. 409 here used to wedge the
    shared table: the closer looped, GET stayed `spinning`, nobody could bet.
    """
    cover = money(reserved)
    payout = money(settlement.payout)
    if payout <= cover:
        return settlement
    logger.warning(
        "roulette held seat payout drifted payout=%s reserved=%s",
        payout,
        cover,
    )
    return HouseGameSettlement(
        stake=settlement.stake,
        payout=cover,
        house_delta=money(settlement.stake - cover),
        commission=settlement.commission,
    )


def verify_roulette_round(
    *,
    server_seed: str,
    client_seed: str,
    nonce: int,
    game_id: str,
    commit: str,
    expected_pocket: int | None = None,
) -> dict[str, object]:
    """Replay one round from the revealed seed. Used by the public verifier."""
    computed = game_commit(server_seed, game_id)
    commit_matches = commits_match(computed, commit)
    pocket = roulette_pocket(server_seed, game_id, client_seed=client_seed, nonce=nonce)
    pocket_matches = expected_pocket is None or int(pocket) == int(expected_pocket)
    return {
        "matches": bool(commit_matches and pocket_matches),
        "commit_matches": commit_matches,
        "pocket_matches": pocket_matches,
        "computed_commit": computed,
        "message": pocket_message(client_seed=client_seed, nonce=nonce, game_id=game_id),
        "pocket": pocket,
        "color": pocket_color(pocket),
        "wheel_index": wheel_position(pocket),
        "modulus": POCKET_COUNT,
        "algorithm": ROULETTE_ALGORITHM,
    }


def public_bet_table() -> list[dict[str, object]]:
    """Bet catalogue for the quote payload: one source of truth for the client."""
    return [
        {
            "key": spec.key,
            "title_ru": spec.title_ru,
            "odds_ru": spec.odds_ru,
            "payout_multiplier": float(spec.payout_multiplier),
            "profit_ratio": float(spec.profit_ratio),
            "win_probability": float(spec.win_probability),
            "pockets": sorted(spec.pockets),
        }
        for spec in (ROULETTE_BETS[key] for key in ROULETTE_BET_KEYS)
    ]


async def load_roulette_quote_profile(conn) -> Mapping[str, object] | None:
    """Active house robot that may take roulette, without locking the row."""
    return await conn.fetchrow(
        """
        SELECT rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub, ha.balance_rub, ha.reserved_rub
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND (rp.allowed_games ? $1 OR rp.allowed_games ? 'cub')
        ORDER BY CASE WHEN rp.allowed_games ? $1 THEN 0 ELSE 1 END, rp.id
        LIMIT 1
        """,
        ROULETTE_GAME_TYPE,
    )


def apply_roulette_stake_window(
    settings,
    payout_multiplier: Decimal | int | float | str,
    profile: Mapping[str, object] | None,
) -> tuple[Decimal, Decimal]:
    """min/max for one payout multiplier: global limits, robot, % of bankroll, exposure."""
    bankroll = money(profile["balance_rub"]) if profile else Decimal("0")
    min_bet, max_bet = game_stake_bounds(
        settings,
        ROULETTE_GAME_TYPE,
        payout_multiplier=payout_multiplier,
        bankroll_rub=bankroll,
    )
    if not profile:
        return min_bet, max_bet
    min_bet = max(min_bet, money(profile["min_bet_rub"]))
    max_bet = min(max_bet, money(profile["max_bet_rub"]))
    try:
        multiplier = Decimal(str(payout_multiplier))
    except (InvalidOperation, ValueError):
        return min_bet, max_bet
    if multiplier <= 0:
        return min_bet, max_bet
    reserved = money(profile["reserved_rub"] if profile.get("reserved_rub") is not None else 0)
    available = max(Decimal("0.00"), bankroll - reserved)
    if available > 0:
        max_bet = min(max_bet, money(available / multiplier))
    exposure = money(profile["max_exposure_rub"] if profile.get("max_exposure_rub") is not None else 0)
    if exposure > 0:
        max_bet = min(max_bet, money(exposure / multiplier))
    return min_bet, max_bet


def _as_map(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _round_payload(
    *,
    ic,
    game_id: str,
    stake: Decimal,
    resolved: Mapping[str, object],
    rng_audit: Mapping[str, object],
    telegram_id: int,
    house_balance_rub: object = None,
    idempotent: bool = False,
) -> dict[str, object]:
    settlement = resolved["settlement"]
    won = bool(resolved["won"])
    pocket = int(resolved["pocket"])
    outcome = {
        "kind": "win" if won else "loss",
        "winner_id": telegram_id if won else None,
        "pocket": pocket,
        "color": str(resolved["color"]),
        "bet": str(resolved["bet"]),
        "wheel_index": int(resolved["wheel_index"]),
    }
    payload: dict[str, object] = {
        "success": True,
        "idempotent": bool(idempotent),
        "game_id": game_id,
        "game_type": ROULETTE_GAME_TYPE,
        "phase": "finished",
        "outcome": outcome,
        "bet": str(resolved["bet"]),
        "pocket": pocket,
        "color": str(resolved["color"]),
        "wheel_index": int(resolved["wheel_index"]),
        "won": won,
        "payout_multiplier": ic._text_money(resolved["payout_multiplier"]),
        "stake_rub": ic._text_money(stake),
        "commission_rub": ic._text_money(settlement.commission),
        "payout_rub": ic._text_money(settlement.payout),
        "rng": dict(rng_audit),
    }
    if house_balance_rub is not None:
        payload["house_balance_rub"] = ic._text_money(house_balance_rub)
    return payload


@dataclass(frozen=True)
class RouletteHouseSeat:
    """House robot + limits for one roulette stake. Shared by 1×1 and the table."""

    policy: Mapping[str, object]
    profile: Mapping[str, object]
    settings: object
    commission_rate: Decimal
    commission_profile: object
    max_settlement: object
    stake: Decimal
    spec: RouletteBet


async def load_roulette_house_seat(
    conn,
    *,
    telegram_id: int,
    stake_rub: Decimal,
    bet: str,
    extra_available_rub: Decimal = Decimal("0"),
    require_stake_window: bool = True,
    require_bankroll: bool = True,
) -> RouletteHouseSeat:
    """Lock the house robot and refuse the stake if the bankroll cannot cover a win.

    `require_stake_window` is for a fresh bet. Table settle of an already-held
    seat must pass False: the live window can shrink after the chip was accepted,
    and re-checking it 409s the closer / snapshot GET for everyone.

    `require_bankroll` is False for chip wallets: фишки не выходят из банкролла,
    поэтому его остаток и лимит экспозиции такую ставку не ограничивают.
    """
    spec = bet_spec(bet)
    stake = money(stake_rub)
    settings_snapshot = await load_casino_settings(conn)
    if not settings_snapshot.enabled_games.get(ROULETTE_GAME_TYPE, False):
        raise HTTPException(status_code=409, detail="Рулетка против казино выключена")
    commission_rate = await commission_rate_for_player(conn, telegram_id)
    commission_profile, _ = await commission_profile_for_player(conn, telegram_id)

    from routers import internal_casino as ic

    policy = await conn.fetchrow(
        """
        SELECT id, payout_multiplier, win_probability, terms
        FROM casino_house_policies
        WHERE game_type = $1 AND is_active = TRUE
        FOR UPDATE
        """,
        ROULETTE_GAME_TYPE,
    )
    if not policy:
        policy = await conn.fetchrow(
            """
            SELECT id, payout_multiplier, win_probability, terms
            FROM casino_house_policies
            WHERE game_type = 'cub' AND is_active = TRUE
            FOR UPDATE
            """
        )
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.account_id, rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub,
               ha.account_key, ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND (rp.allowed_games ? $1 OR rp.allowed_games ? 'cub')
        ORDER BY CASE WHEN rp.allowed_games ? $1 THEN 0 ELSE 1 END, rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """,
        ROULETTE_GAME_TYPE,
    )
    if not policy or not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="House robot is unavailable")
    win_multiplier = spec.payout_multiplier
    if require_stake_window:
        if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
            raise HTTPException(status_code=409, detail=ROBOT_STAKE_OUTSIDE_LIMITS)
    if require_stake_window and require_bankroll:
        ic._assert_stake_within_limits(
            settings_snapshot,
            ROULETTE_GAME_TYPE,
            stake,
            payout_multiplier=win_multiplier,
            bankroll_rub=money(profile["balance_rub"]),
        )
    max_settlement = calculate_house_settlement(
        stake,
        win_multiplier,
        commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    exposure_limit = money(profile["max_exposure_rub"])
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"]) + money(extra_available_rub)
    if require_stake_window and require_bankroll and (
        (exposure_limit > 0 and max_settlement.payout > exposure_limit) or available < max_settlement.payout
    ):
        raise HTTPException(status_code=409, detail=HOUSE_BANKROLL_INSUFFICIENT)
    return RouletteHouseSeat(
        policy=dict(policy),
        profile=dict(profile),
        settings=settings_snapshot,
        commission_rate=commission_rate,
        commission_profile=commission_profile,
        max_settlement=max_settlement,
        stake=stake,
        spec=spec,
    )


async def play_roulette_with_conn(
    conn,
    *,
    telegram_id: int,
    stake_rub: Decimal,
    bet: str,
) -> dict[str, object]:
    """One atomic spin against the house bankroll. Settles in a single request.

    Фишковые кошельки (бонус, турнир) играют здесь наравне с рублями: ставка и
    выигрыш идут по своей области, банкролл казино в них не участвует.
    """
    from casino_wallet import active_scope, scope_insert_sql

    spec = bet_spec(bet)
    scope = await active_scope(conn, telegram_id)
    await lock_casino_users(conn, (telegram_id,))
    game_id = str(uuid4())
    await lock_casino_game(conn, game_id)
    seat = await load_roulette_house_seat(
        conn,
        telegram_id=telegram_id,
        stake_rub=stake_rub,
        bet=spec.key,
        require_bankroll=scope.is_rub,
    )
    stake = seat.stake
    settings_snapshot = seat.settings
    commission_rate = seat.commission_rate
    commission_profile = seat.commission_profile
    policy = seat.policy
    profile = seat.profile
    max_settlement = seat.max_settlement
    win_multiplier = spec.payout_multiplier

    from routers import internal_casino as ic

    rng = await ic._load_or_create_card_commit(
        conn,
        game_id=game_id,
        game_type=ROULETTE_GAME_TYPE,
        telegram_id=telegram_id,
    )
    seed = str(rng["server_seed"])
    rng_commit = str(rng["rng_commit"])
    client_seed = str(rng.get("client_seed") or DEFAULT_CLIENT_SEED)
    nonce = int(rng["nonce"])

    resolved = resolve_roulette_round(
        seed=seed,
        game_id=game_id,
        client_seed=client_seed,
        nonce=nonce,
        stake_rub=stake,
        bet=spec.key,
        commission_rate=commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    settlement = resolved["settlement"]
    pocket = int(resolved["pocket"])
    won = bool(resolved["won"])
    if settlement.payout > max_settlement.payout:
        raise HTTPException(status_code=409, detail="Roulette payout exceeds the reservation")

    hold_id = f"casino-{game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake)
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    rng_audit = {
        "algorithm": ROULETTE_ALGORITHM,
        "commit": rng_commit,
        "pair_commit": str(rng.get("pair_commit") or ""),
        "seed": seed,
        "nonce": nonce,
        "client_seed": client_seed,
        "message": pocket_message(client_seed=client_seed, nonce=nonce, game_id=game_id),
        "modulus": POCKET_COUNT,
        "pocket": pocket,
        "color": str(resolved["color"]),
        "wheel_index": int(resolved["wheel_index"]),
        "bet": spec.key,
        "won": won,
    }
    game_data = {
        "house_policy_snapshot": {
            "policy_id": int(policy["id"]),
            "payout_multiplier": ic._text_money(win_multiplier),
            "source_game_type": ROULETTE_GAME_TYPE,
            "payout_source": "european_roulette_rules",
        },
        "pricing_snapshot": ic._pricing_snapshot_payload(
            commission_profile=commission_profile,
            commission_rate=commission_rate,
            creator_cut_percent=creator_cut_percent,
            referral_l1_percent=referral_l1_percent,
            referral_l2_percent=referral_l2_percent,
            commission_cap_rub=settings_snapshot.commission_cap_rub,
            commission_min_rub=settings_snapshot.commission_min_rub,
        ),
        "roulette": {
            "bet": spec.key,
            "odds_ru": spec.odds_ru,
            "pockets": sorted(spec.pockets),
            "cover": len(spec.pockets),
            "pocket": pocket,
            "color": str(resolved["color"]),
            "wheel_index": int(resolved["wheel_index"]),
            "max_payout_rub": ic._text_money(max_settlement.payout),
        },
        "rng_audit": rng_audit,
    }
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_games", scope, next_index=14
    )
    game = await conn.fetchrow(
        f"""
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_commit, rng_seed_reveal, rng_nonce,
            game_data, started_at{scope_cols}
        ) VALUES (
            $1, $2, $3, $4, $4, $5, $6, 'active', 'house_robot', $7,
            $8, $9, $10, $11, $12, $13::jsonb, now(){scope_params}
        )
        RETURNING id
        """,
        game_id, ROULETTE_GAME_TYPE, telegram_id, stake, settlement.payout, hold_id,
        int(profile["account_id"]), int(profile["id"]), int(policy["id"]),
        rng_commit, seed, nonce, json.dumps(game_data, separators=(",", ":")),
        *scope_values,
    )
    if not game:
        raise HTTPException(status_code=409, detail="Roulette game creation conflicts")
    await consume_rng_commit(
        conn, game_id=game_id, telegram_id=telegram_id, game_type=ROULETTE_GAME_TYPE
    )
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, telegram_id, game_id, stake, order_ref,
    )
    if scope.is_rub:
        reservation = await conn.fetchrow(
            """
            UPDATE casino_house_accounts
            SET reserved_rub = reserved_rub + $2, updated_at = now()
            WHERE id = $1 AND balance_rub - reserved_rub >= $2
            RETURNING balance_rub, reserved_rub
            """,
            int(profile["account_id"]), max_settlement.payout,
        )
        if not reservation:
            raise HTTPException(status_code=409, detail=HOUSE_BANKROLL_INSUFFICIENT)
        await conn.execute(
            """
            INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
            VALUES ($1, $2, $3, $4)
            """,
            f"{ROULETTE_GAME_TYPE}-reserve-{game_id}", int(profile["account_id"]), game_id,
            max_settlement.payout,
        )
    await confirm_unified_hold(
        conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake,
        note=f"Casino roulette stake: {game_id}",
    )
    account = await _settle_roulette_money(
        conn,
        ic=ic,
        game_pk=int(game["id"]),
        game_id=game_id,
        telegram_id=telegram_id,
        stake=stake,
        settlement=settlement,
        won=won,
        game_data=game_data,
        account_id=int(profile["account_id"]),
        reserved_payout=max_settlement.payout,
        hold_id=hold_id,
        seed=seed,
        house_backed=scope.is_rub,
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    return _round_payload(
        ic=ic,
        game_id=game_id,
        stake=stake,
        resolved=resolved,
        rng_audit=rng_audit,
        telegram_id=telegram_id,
        house_balance_rub=account["balance_rub"],
    )


async def play_roulette_known_pocket_with_conn(
    conn,
    *,
    telegram_id: int,
    stake_rub: Decimal,
    bet: str,
    pocket: int,
    seed: str,
    rng_commit: str,
    hmac_game_id: str,
    hold_order_ref: str,
    reserved_payout: Decimal,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
    game_id: str | None = None,
    scope=None,
) -> dict[str, object]:
    """Settle one table seat against a pocket the round already drew.

    The player hold and the house max-payout reserve must already be in place.
    HMAC is keyed by hmac_game_id (the shared round_id), not the per-seat game_id.
    `scope` — область кошелька раунда; фишковый раунд банкролл не трогает.
    """
    from casino_wallet import RUB_SCOPE, scope_insert_sql

    round_scope = scope or RUB_SCOPE
    house_backed = round_scope.is_rub
    spec = bet_spec(bet)
    await lock_casino_users(conn, (telegram_id,))
    seat_game_id = str(game_id or uuid4())
    await lock_casino_game(conn, seat_game_id)
    reserved = money(reserved_payout)
    seat = await load_roulette_house_seat(
        conn,
        telegram_id=telegram_id,
        stake_rub=stake_rub,
        bet=spec.key,
        extra_available_rub=reserved,
        require_stake_window=False,
        require_bankroll=house_backed,
    )
    if seat.max_settlement.payout > reserved:
        logger.warning(
            "roulette held seat cover drifted max=%s reserved=%s",
            seat.max_settlement.payout,
            reserved,
        )
    drawn = roulette_pocket(seed, hmac_game_id, client_seed=client_seed, nonce=nonce)
    if int(pocket) != int(drawn):
        raise HTTPException(status_code=500, detail="Roulette table pocket does not match the commit")
    settings_snapshot = seat.settings
    resolved = resolve_roulette_round(
        seed=seed,
        game_id=hmac_game_id,
        client_seed=client_seed,
        nonce=nonce,
        stake_rub=seat.stake,
        bet=spec.key,
        commission_rate=seat.commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    if int(resolved["pocket"]) != int(pocket):
        raise HTTPException(status_code=500, detail="Roulette table pocket does not match the commit")
    settlement = clamp_held_roulette_payout(resolved["settlement"], reserved)
    won = bool(resolved["won"])
    from routers import internal_casino as ic

    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=seat.commission_profile,
        commission_rate=seat.commission_rate,
    )
    rng_audit = {
        "algorithm": ROULETTE_ALGORITHM,
        "commit": rng_commit,
        "pair_commit": "",
        "seed": seed,
        "nonce": nonce,
        "client_seed": client_seed,
        "message": pocket_message(client_seed=client_seed, nonce=nonce, game_id=hmac_game_id),
        "modulus": POCKET_COUNT,
        "pocket": int(resolved["pocket"]),
        "color": str(resolved["color"]),
        "wheel_index": int(resolved["wheel_index"]),
        "bet": spec.key,
        "won": won,
        "table_round_id": hmac_game_id,
    }
    hold_id = f"casino-{seat_game_id}-player"
    game_data = {
        "house_policy_snapshot": {
            "policy_id": int(seat.policy["id"]),
            "payout_multiplier": ic._text_money(spec.payout_multiplier),
            "source_game_type": ROULETTE_GAME_TYPE,
            "payout_source": "european_roulette_rules",
        },
        "pricing_snapshot": ic._pricing_snapshot_payload(
            commission_profile=seat.commission_profile,
            commission_rate=seat.commission_rate,
            creator_cut_percent=creator_cut_percent,
            referral_l1_percent=referral_l1_percent,
            referral_l2_percent=referral_l2_percent,
            commission_cap_rub=settings_snapshot.commission_cap_rub,
            commission_min_rub=settings_snapshot.commission_min_rub,
        ),
        "roulette": {
            "bet": spec.key,
            "odds_ru": spec.odds_ru,
            "pockets": sorted(spec.pockets),
            "cover": len(spec.pockets),
            "pocket": int(resolved["pocket"]),
            "color": str(resolved["color"]),
            "wheel_index": int(resolved["wheel_index"]),
            "max_payout_rub": ic._text_money(seat.max_settlement.payout),
            "table_round_id": hmac_game_id,
        },
        "rng_audit": rng_audit,
    }
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_games", round_scope, next_index=14
    )
    game = await conn.fetchrow(
        f"""
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_commit, rng_seed_reveal, rng_nonce,
            game_data, started_at{scope_cols}
        ) VALUES (
            $1, $2, $3, $4, $4, $5, $6, 'active', 'house_robot', $7,
            $8, $9, $10, $11, $12, $13::jsonb, now(){scope_params}
        )
        RETURNING id
        """,
        seat_game_id, ROULETTE_GAME_TYPE, telegram_id, seat.stake, settlement.payout, hold_id,
        int(seat.profile["account_id"]), int(seat.profile["id"]), int(seat.policy["id"]),
        rng_commit, seed, nonce, json.dumps(game_data, separators=(",", ":")),
        *scope_values,
    )
    if not game:
        raise HTTPException(status_code=409, detail="Roulette game creation conflicts")
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, telegram_id, seat_game_id, seat.stake, hold_order_ref,
    )
    if house_backed:
        await conn.execute(
            """
            INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
            VALUES ($1, $2, $3, $4)
            """,
            f"{ROULETTE_GAME_TYPE}-table-{seat_game_id}", int(seat.profile["account_id"]),
            seat_game_id, reserved,
        )
    await confirm_unified_hold(
        conn, user_id=telegram_id, order_ref=hold_order_ref, amount_rub=seat.stake,
        note=f"Casino roulette table stake: {seat_game_id}",
    )
    account = await _settle_roulette_money(
        conn,
        ic=ic,
        game_pk=int(game["id"]),
        game_id=seat_game_id,
        telegram_id=telegram_id,
        stake=seat.stake,
        settlement=settlement,
        won=won,
        game_data=game_data,
        account_id=int(seat.profile["account_id"]),
        reserved_payout=reserved,
        hold_id=hold_id,
        seed=seed,
        house_backed=house_backed,
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    return _round_payload(
        ic=ic,
        game_id=seat_game_id,
        stake=seat.stake,
        resolved=resolved,
        rng_audit=rng_audit,
        telegram_id=telegram_id,
        house_balance_rub=account["balance_rub"],
    )


async def _finish_chips_round(
    conn,
    *,
    ic,
    game_pk: int,
    game_id: str,
    telegram_id: int,
    settlement,
    won: bool,
    game_data: dict[str, object],
    hold_id: str,
    seed: str,
):
    """Закрыть фишковый раунд: холд, статус игры, итог. Без банкролла и комиссий."""
    roulette_data = _as_map(game_data.get("roulette"))
    outcome = {
        "kind": "win" if won else "loss",
        "winner_id": telegram_id if won else None,
        "pocket": int(roulette_data.get("pocket") or 0),
        "color": str(roulette_data.get("color") or ""),
        "bet": str(roulette_data.get("bet") or ""),
        "wheel_index": int(roulette_data.get("wheel_index") or 0),
    }
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    await conn.execute(
        """
        UPDATE casino_games
        SET status = 'finished', winner_id = $2, outcome = $3::jsonb,
            commission_rub = 0, payout_rub = $4, rng_seed_reveal = $5,
            game_data = $6::jsonb, finished_at = now(), updated_at = now()
        WHERE game_id = $1
        """,
        game_id, telegram_id if won else None,
        json.dumps(outcome, separators=(",", ":")), settlement.payout, seed,
        json.dumps(game_data, separators=(",", ":")),
    )
    return {"balance_rub": Decimal("0"), "reserved_rub": Decimal("0")}


async def _settle_roulette_money(
    conn,
    *,
    ic,
    game_pk: int,
    game_id: str,
    telegram_id: int,
    stake: Decimal,
    settlement,
    won: bool,
    game_data: dict[str, object],
    account_id: int,
    reserved_payout: Decimal,
    hold_id: str,
    seed: str,
    house_backed: bool = True,
):
    if settlement.payout > 0:
        await ic._credit_winner(
            conn, game_id=game_id, winner_id=telegram_id, payout_rub=settlement.payout
        )
    if not house_backed:
        # Фишковый раунд: банкролл не двигаем и комиссию не берём — в экономику
        # казино такая игра не попадает.
        return await _finish_chips_round(
            conn,
            ic=ic,
            game_pk=game_pk,
            game_id=game_id,
            telegram_id=telegram_id,
            settlement=settlement,
            won=won,
            game_data=game_data,
            hold_id=hold_id,
            seed=seed,
        )
    account = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $2 - $3,
            reserved_rub = reserved_rub - $4,
            updated_at = now()
        WHERE id = $1 AND reserved_rub >= $4
        RETURNING balance_rub, reserved_rub
        """,
        account_id, stake, settlement.payout, reserved_payout,
    )
    if not account:
        raise HTTPException(status_code=409, detail="House reservation conflicts")
    casino_creator_account = await ic._resolve_active_creator_account(conn)
    referral_l1_id, referral_l2_id = await ic._resolve_loser_referrals(conn, telegram_id)
    pricing_snapshot = _as_map(game_data.get("pricing_snapshot"))
    allocations = allocate_commission(
        stake,
        commission_rate=pricing_snapshot["commission_rate"],
        creator_percent=pricing_snapshot["creator_cut_percent"],
        referral_l1_percent=pricing_snapshot["referral_l1_percent"],
        referral_l2_percent=pricing_snapshot["referral_l2_percent"],
        has_creator=casino_creator_account is not None,
        has_referral_l1=referral_l1_id is not None,
        has_referral_l2=referral_l2_id is not None,
        commission_cap_rub=ic._snapshot_amount(pricing_snapshot, "commission_cap_rub"),
        commission_min_rub=ic._snapshot_amount(pricing_snapshot, "commission_min_rub"),
    )
    await ic._record_commissions(
        conn,
        game_pk=game_pk,
        game_id=game_id,
        casino_creator_account=casino_creator_account,
        referral_l1_id=referral_l1_id,
        referral_l2_id=referral_l2_id,
        allocations=allocations,
    )
    roulette_data = _as_map(game_data.get("roulette"))
    outcome = {
        "kind": "win" if won else "loss",
        "winner_id": telegram_id if won else None,
        "pocket": int(roulette_data.get("pocket") or 0),
        "color": str(roulette_data.get("color") or ""),
        "bet": str(roulette_data.get("bet") or ""),
        "wheel_index": int(roulette_data.get("wheel_index") or 0),
    }
    await conn.execute(
        """
        INSERT INTO casino_house_ledger (
            account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
        ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)
        """,
        account_id, game_id, f"{ROULETTE_GAME_TYPE}-settlement-{game_id}",
        settlement.house_delta, money(account["balance_rub"]),
        f"roulette {outcome['bet']} {outcome['pocket']} settlement",
    )
    await conn.execute(
        """
        UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    await conn.execute(
        """
        UPDATE casino_games
        SET status = 'finished', winner_id = $2, outcome = $3::jsonb,
            commission_rub = $4, payout_rub = $5, rng_seed_reveal = $6,
            game_data = $7::jsonb, finished_at = now(), updated_at = now()
        WHERE game_id = $1
        """,
        game_id, telegram_id if won else None,
        json.dumps(outcome, separators=(",", ":")), settlement.commission,
        settlement.payout, seed, json.dumps(game_data, separators=(",", ":")),
    )
    return account

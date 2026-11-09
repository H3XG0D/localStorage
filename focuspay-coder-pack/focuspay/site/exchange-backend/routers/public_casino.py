"""Public casino fairness verifier and lobby snapshot. No auth."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Mapping, Sequence

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from casino_wallet import scope_filter_for, viewer_scope
from casino_duels import (
    DUEL_ROOM_SELECT_TYPED_SQL,
    FILL_SAMPLES_SQL,
    WAITING_DUELS_SQL,
    waiting_duels,
    assemble_duels_payload,
    build_duel_room,
    fill_duel_actors,
    fill_duels_payload_actors,
)
from casino_pvp_cards import complete_site_card_duel_if_due
from casino_pvp_dice import (
    ensure_closer as pvp_dice_ensure_closer,
    house_fill_if_due as pvp_dice_house_fill_if_due,
)
from casino_v2_web import (
    WEB_V2_GAME_TYPE,
    ensure_closer as v2_web_ensure_closer,
    ensure_round_ready as v2_ensure_round_ready,
    house_fill_table as v2_house_fill_table,
    list_public_tables as list_v2_public_tables,
    load_public_table as load_v2_public_table,
)
from casino_clans import clan_snapshot, list_top as clans_list_top
from casino_finance import HEAD_TO_HEAD_GAME_TYPES, CasinoSettings, load_casino_settings
from casino_play import HOUSE_PLAY_GAME_TYPES, TAPE_TABS, filter_tape_rows, load_house_play_quote
from casino_roulette import (
    DEFAULT_ROULETTE_BET,
    POCKET_COUNT,
    ROULETTE_ALGORITHM,
    ROULETTE_BET_KEY_MAX_LENGTH,
    ROULETTE_GAME_TYPE,
    bet_spec as roulette_bet_spec,
    verify_roulette_round,
)
from db import get_pool
from casino_cards import (
    CARD_GAME_TYPES,
    FAIRNESS_GAME_TYPES,
    CARD_SHUFFLE_ALGORITHM,
    MAX_CARD_HAND_SIZE,
    SHOE_SIDES,
    is_valid_shoe_side,
    verify_card_round,
    verify_holdem_round,
)

router = APIRouter()


class FairnessVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_type: str
    game_id: str = Field(min_length=1, max_length=64)
    server_seed: str = Field(min_length=8, max_length=128)
    client_seed: str = Field(min_length=1, max_length=64)
    nonce: int = Field(ge=0, le=10_000_000)
    commit: str = Field(min_length=16, max_length=128)
    side: str | None = None
    hand_size: int | None = Field(default=None, ge=1, le=MAX_CARD_HAND_SIZE)
    expected_cards: list[str] | None = None
    total_tickets: int | None = Field(default=None, ge=1)
    expected_ticket: int | None = Field(default=None, ge=0)
    hmac_message: str | None = Field(default=None, max_length=512)
    modulus: int | None = Field(default=None, ge=2, le=100)
    expected_index: int | None = Field(default=None, ge=0)
    expected_pocket: int | None = Field(default=None, ge=0, le=POCKET_COUNT - 1)

    @field_validator("game_type", "game_id", "server_seed", "client_seed", "commit")
    @classmethod
    def strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text

    @field_validator("game_type")
    @classmethod
    def known_game(cls, value: str) -> str:
        if value not in (*FAIRNESS_GAME_TYPES, "jackpot", "fixed_room", "clan_war", ROULETTE_GAME_TYPE, "raffle"):
            raise ValueError(
                "game_type must be baccara, blackjack, holdem, jackpot, fixed_room, clan_war, roulette or raffle"
            )
        return value

    @field_validator("side")
    @classmethod
    def known_side(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not is_valid_shoe_side(value):
            raise ValueError("side must be creator, opponent, or seat1..seat6")
        return value

    @field_validator("expected_cards")
    @classmethod
    def clean_cards(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cards = [card.strip() for card in value if isinstance(card, str) and card.strip()]
        if not cards:
            return None
        return cards

    @model_validator(mode="after")
    def expected_cards_need_side(self):
        if self.game_type in {"holdem", "jackpot", "fixed_room", "clan_war", ROULETTE_GAME_TYPE, "raffle"}:
            return self
        if self.expected_cards is not None and self.side is None:
            raise ValueError("side is required when expected_cards is set")
        return self


@router.post("/casino/fairness/verify")
async def verify_fairness(body: FairnessVerifyRequest) -> dict:
    try:
        if body.game_type == "jackpot":
            from casino_jackpot import verify_jackpot_round

            if body.total_tickets is None:
                raise HTTPException(status_code=400, detail="total_tickets required")
            result = verify_jackpot_round(
                roll=body.server_seed,
                commit=body.commit,
                total_tickets=body.total_tickets,
                expected_ticket=body.expected_ticket,
            )
            algorithm = "sha256-roll-x-tickets"
        elif body.game_type == "raffle":
            from casino_raffle import HMAC_ALGORITHM, verify_raffle_place

            if body.total_tickets is None:
                raise HTTPException(status_code=400, detail="total_tickets required")
            if body.nonce < 1:
                raise HTTPException(status_code=400, detail="nonce (place) required")
            result = verify_raffle_place(
                seed=body.server_seed,
                commit=body.commit,
                place=body.nonce,
                remaining_tickets=body.total_tickets,
                expected_index=body.expected_ticket,
            )
            algorithm = HMAC_ALGORITHM
        elif body.game_type in {"fixed_room", "clan_war"}:
            from casino_fixed_rooms import HMAC_ALGORITHM, verify_hmac_round

            if not body.hmac_message or body.modulus is None:
                raise HTTPException(status_code=400, detail="hmac_message and modulus required")
            result = verify_hmac_round(
                seed=body.server_seed,
                commit=body.commit,
                message=body.hmac_message,
                modulus=body.modulus,
                expected_index=body.expected_index,
            )
            algorithm = HMAC_ALGORITHM
        elif body.game_type == ROULETTE_GAME_TYPE:
            result = verify_roulette_round(
                server_seed=body.server_seed,
                client_seed=body.client_seed,
                nonce=body.nonce,
                game_id=body.game_id,
                commit=body.commit,
                expected_pocket=body.expected_pocket,
            )
            algorithm = ROULETTE_ALGORITHM
        elif body.game_type == "holdem":
            result = verify_holdem_round(
                server_seed=body.server_seed,
                client_seed=body.client_seed,
                nonce=body.nonce,
                hand_id=body.game_id,
                commit=body.commit,
                expected_board=body.expected_cards,
            )
            result.pop("holes", None)
            result.pop("burns", None)
            algorithm = CARD_SHUFFLE_ALGORITHM
        else:
            result = verify_card_round(
                server_seed=body.server_seed,
                client_seed=body.client_seed,
                nonce=body.nonce,
                game_id=body.game_id,
                commit=body.commit,
                side=body.side,
                hand_size=body.hand_size,
                expected_cards=body.expected_cards,
            )
            algorithm = CARD_SHUFFLE_ALGORITHM
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "success": True,
        "fair": bool(result["matches"]),
        "matches": bool(result["matches"]),
        **result,
        "game_type": body.game_type,
        "algorithm": algorithm,
    }


LOBBY_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "pvp_dice", "name": "Кубики", "category": "duels", "emoji": "🎲"},
    {"id": "baccara", "name": "Баккара", "category": "cards", "emoji": "🃏"},
    {"id": "blackjack", "name": "Блэкджек", "category": "cards", "emoji": "🂡"},
    {"id": "cub", "name": "Кубик против казино", "category": "house", "emoji": "🏠"},
    {"id": "roulette", "name": "Рулетка", "category": "house", "emoji": "🎡"},
    {"id": "holdem", "name": "Техасский холдем", "category": "cards", "emoji": "🂠"},
    {"id": "jackpot", "name": "Джекпот", "category": "house", "emoji": "🎡"},
    {"id": "fixed_room", "name": "Комнаты", "category": "duels", "emoji": "🎯"},
    {"id": "raffle", "name": "FocusLucky", "category": "house", "emoji": "🎰"},
    {"id": "clan_war", "name": "Клан vs клан", "category": "duels", "emoji": "⚔️"},
    {"id": "russian_draughts", "name": "Русские шашки", "category": "duels", "emoji": "⚫"},
)


def build_public_lobby(
    settings: CasinoSettings,
    waiting: Sequence[Mapping[str, object]],
    rooms: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    enabled = settings.enabled_games
    games = [
        {
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "emoji": item["emoji"],
            "enabled": bool(enabled.get(item["id"], False)),
        }
        for item in LOBBY_CATALOG
    ]
    open_duels: list[dict[str, object]] = []
    for row in waiting:
        opened = row.get("created_at")
        open_duels.append(
            {
                "game_id": str(row["game_id"]),
                "game_type": str(row["game_type"]),
                "bet_rub": float(row["bet_rub"]),
                "opened_at": opened.isoformat() if isinstance(opened, datetime) else str(opened or ""),
            }
        )
    open_rooms: list[dict[str, object]] = []
    for row in rooms:
        opened = row.get("created_at")
        filled = row.get("filled")
        try:
            filled_n = int(filled) if filled is not None else 0
        except (TypeError, ValueError):
            filled_n = 0
        open_rooms.append(
            {
                "room_id": str(row["room_id"]),
                "stake_rub": float(row["stake_rub"]),
                "seat_count": int(row.get("seat_count") or 0),
                "filled": filled_n,
                "opened_at": opened.isoformat() if isinstance(opened, datetime) else str(opened or ""),
            }
        )
    return {
        "min_bet_rub": float(settings.min_bet_rub),
        "max_bet_rub": float(settings.max_bet_rub),
        "commission_percent": float(settings.commission_rate_wagering_complete),
        "games": games,
        "open_duels": open_duels,
        "open_rooms": open_rooms,
    }


@router.get("/casino/lobby")
async def casino_lobby(request: Request) -> dict[str, object]:
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        settings = await load_casino_settings(conn)
        # Сводка лобби тоже живёт в одной области с игроком.
        scope = await viewer_scope(conn, viewer)
        duel_and = await scope_filter_for(conn, "casino_games", scope)
        room_and = await scope_filter_for(conn, "casino_fixed_room_rounds", scope, "r")
        waiting = await conn.fetch(
            f"""
            SELECT game_id, game_type, bet_rub, created_at
            FROM casino_games
            WHERE status = 'waiting' AND opponent_id IS NULL
              AND game_type = ANY($1::text[])
              AND COALESCE(game_state->>'reserved_opponent_id', '') = ''{duel_and}
            ORDER BY created_at DESC
            LIMIT 8
            """,
            list(HEAD_TO_HEAD_GAME_TYPES),
        )
        rooms = await conn.fetch(
            f"""
            SELECT r.room_id, r.stake_rub, r.seat_count, r.created_at,
                   (SELECT count(*)::int FROM casino_fixed_room_seats s WHERE s.room_pk = r.id) AS filled
            FROM casino_fixed_room_rounds r
            WHERE r.status = 'open'{room_and}
            ORDER BY r.created_at DESC
            LIMIT 8
            """
        )
    return build_public_lobby(settings, waiting, rooms)


async def optional_web_user(request: Request) -> dict | None:
    from auth import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    auth = request.headers.get("authorization") or ""
    credentials = None
    if auth.lower().startswith("bearer ") and len(auth) > 7:
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:].strip())
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


def _viewer_id(user: dict | None) -> int | None:
    if not user:
        return None
    from auth import resolve_client_user_id

    try:
        return resolve_client_user_id(user)
    except HTTPException:
        return None


@router.get("/casino/duels")
async def casino_duels(request: Request) -> dict[str, object]:
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        settings = await load_casino_settings(conn)
        waiting = await waiting_duels(conn, viewer)
        samples = await conn.fetch(FILL_SAMPLES_SQL, list(HEAD_TO_HEAD_GAME_TYPES))
        payload = assemble_duels_payload(settings, waiting, samples, viewer_id=viewer)
        return await fill_duels_payload_actors(conn, payload, waiting)


@router.get("/casino/duels/{game_id}")
async def casino_duel_room(game_id: str, request: Request) -> dict[str, object]:
    viewer = _viewer_id(await optional_web_user(request))
    pvp_dice_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await pvp_dice_house_fill_if_due(conn, game_id.strip())
        await complete_site_card_duel_if_due(conn, game_id.strip())
        settings = await load_casino_settings(conn)
        row = await conn.fetchrow(
            DUEL_ROOM_SELECT_TYPED_SQL,
            game_id.strip(),
            list(HEAD_TO_HEAD_GAME_TYPES),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Дуэль не найдена")
        room = build_duel_room(row, settings, viewer_id=viewer)
        return await fill_duel_actors(conn, room, row)


@router.get("/casino/play/quote")
async def casino_play_quote(
    request: Request,
    stake_rub: Decimal = Decimal("100"),
    game_type: str = "cub",
    house_bot_count: int = Query(default=0, ge=0, le=6),
    bet: str = Query(default=DEFAULT_ROULETTE_BET, max_length=ROULETTE_BET_KEY_MAX_LENGTH),
) -> dict[str, object]:
    if game_type not in HOUSE_PLAY_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Котировка ставки есть у игр против казино")
    if stake_rub <= 0:
        raise HTTPException(status_code=400, detail="Ставка должна быть больше нуля")
    roulette_bet = bet
    if game_type == ROULETTE_GAME_TYPE:
        roulette_bet = roulette_bet_spec(bet).key
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_house_play_quote(
            conn,
            game_type=game_type,
            stake_rub=stake_rub,
            viewer_id=viewer,
            house_bot_count=house_bot_count if game_type == "cub" else 0,
            roulette_bet=roulette_bet,
        )


@router.get("/casino/play/tape")
async def casino_play_tape(
    request: Request,
    tab: Literal["mine", "all", "high"] = "all",
    game_type: str = "cub",
) -> dict[str, object]:
    if game_type not in HOUSE_PLAY_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Лента есть у игр против казино")
    wanted = tab if tab in TAPE_TABS else "all"
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT game_id, game_type, creator_id, winner_id, bet_rub, payout_rub, finished_at,
                   outcome
            FROM casino_games
            WHERE game_type = $1 AND status = 'finished'
              AND counterparty_kind = 'house_robot'
            ORDER BY finished_at DESC NULLS LAST
            LIMIT 40
            """,
            game_type,
        )
    return {"tab": wanted, "rows": filter_tape_rows(rows, tab=wanted, viewer_id=viewer)}


@router.get("/casino/v2/tables")
async def public_v2_tables(request: Request, game_type: str = WEB_V2_GAME_TYPE) -> dict[str, object]:
    viewer = _viewer_id(await optional_web_user(request))
    v2_web_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await list_v2_public_tables(conn, game_type=game_type, viewer_id=viewer)


@router.get("/casino/v2/tables/{table_id}")
async def public_v2_table(table_id: str, request: Request) -> dict[str, object]:
    viewer = _viewer_id(await optional_web_user(request))
    v2_web_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            tid = table_id.strip()
            await v2_ensure_round_ready(conn, tid)
            await v2_house_fill_table(conn, tid)
            return await load_v2_public_table(conn, tid, viewer)


@router.get("/casino/poker/tables")
async def public_poker_tables() -> dict[str, object]:
    from casino_poker import list_open_tables

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await list_open_tables(conn)


@router.get("/casino/house-tables")
async def public_house_tables() -> dict[str, object]:
    from casino_house_tables import list_open_tables as house_table_list

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await house_table_list(conn)


@router.get("/casino/house-tables/{table_id}")
async def public_house_table(table_id: str, request: Request) -> dict[str, object]:
    from casino_house_tables import snapshot as house_table_snapshot

    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await house_table_snapshot(conn, table_id=table_id.strip(), viewer_id=viewer)


@router.get("/casino/clans/top")
async def public_clan_top() -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await clans_list_top(conn, limit=20)


@router.get("/casino/clans/{tag}")
async def public_clan_page(tag: str) -> dict[str, object]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await clan_snapshot(conn, tag=tag)


@router.get("/casino/rooms")
async def public_fixed_rooms(request: Request) -> dict[str, object]:
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import list_open as rooms_list_open

    rooms_ensure_closer()
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await rooms_list_open(conn, viewer_id=viewer)


@router.get("/casino/rooms/{room_id}")
async def public_fixed_room(room_id: str, request: Request) -> dict[str, object]:
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import snapshot as rooms_snapshot

    rooms_ensure_closer()
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await rooms_snapshot(conn, room_id.strip(), viewer_id=viewer)


@router.get("/casino/wars")
async def public_clan_wars(request: Request) -> dict[str, object]:
    from casino_clan_wars import ensure_closer as wars_ensure_closer
    from casino_clan_wars import list_open as wars_list_open

    wars_ensure_closer()
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await wars_list_open(conn, viewer_id=viewer)


@router.get("/casino/wars/{war_id}")
async def public_clan_war(war_id: str, request: Request) -> dict[str, object]:
    from casino_clan_wars import ensure_closer as wars_ensure_closer
    from casino_clan_wars import snapshot as wars_snapshot

    wars_ensure_closer()
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await wars_snapshot(conn, war_id.strip(), viewer_id=viewer)


@router.get("/casino/roulette-table")
async def public_roulette_table(request: Request) -> dict[str, object]:
    from casino_roulette_table import ensure_closer as roulette_table_ensure_closer
    from casino_roulette_table import snapshot as roulette_table_snapshot

    roulette_table_ensure_closer()
    viewer = _viewer_id(await optional_web_user(request))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_snapshot(conn, viewer_id=viewer)
    return {"success": True, **snap}

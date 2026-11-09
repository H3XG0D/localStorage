"""Authenticated web create/join for PvP duels. Money path reuses internal holds."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import (
    bearer_scheme,
    decode_token,
    get_current_user,
    get_web_user_by_id,
    resolve_client_user_id,
)
from casino_chat import (
    create_challenge,
    ensure_dm_room,
    ensure_lobby_room,
    list_dms,
    list_messages,
    load_room,
    online_users,
    post_dm,
    post_lobby,
    subscribe_lobby,
    subscribe_user,
    touch_presence,
    unsubscribe_lobby,
    unsubscribe_user,
)
from casino_duels import (
    DUEL_ROOM_SELECT_SQL,
    WAITING_DUELS_SQL,
    waiting_duels,
    build_duel_room,
    fill_duel_actors,
    pick_autojoin_target,
)
from casino_waiting import (
    cancel_player_duel,
    ensure_closer as waiting_ensure_closer,
)
from casino_house_cards import (
    HOUSE_CARD_GAME_TYPES,
    act_house_blackjack_with_conn,
    load_pending_house_blackjack_with_conn,
    play_house_cards_with_conn,
)
from casino_pvp_dice import ensure_closer as pvp_dice_ensure_closer, record_roll as record_pvp_dice_roll
from casino_roulette import (
    DEFAULT_ROULETTE_BET,
    ROULETTE_BET_KEY_MAX_LENGTH,
    ROULETTE_GAME_TYPE,
    play_roulette_with_conn,
)
from casino_v2_web import (
    V2WebCreateBody,
    V2WebDrawChoiceBody,
    V2WebVersionBody,
    add_web_bot,
    choose_draw_web_table,
    create_web_table,
    hit_web_table,
    join_web_table,
    leave_web_table,
    roll_web_table,
    stand_web_table,
    start_web_table,
)
from casino_finance import (
    HEAD_TO_HEAD_GAME_TYPES, load_casino_settings, money
)
from casino_level_bonus import maybe_grant_reached_level_bonuses
from casino_player_profile import load_web_player_profile
from casino_clans import (
    clan_snapshot,
    create_clan,
    disband_clan,
    join_clan,
    kick_member,
    leave_clan,
    list_top as clans_list_top,
    my_clan,
    rotate_invite,
    tagged_display_name,
    transfer_owner,
)
from db import get_pool
from casino_fairness import public_fairness_session, rotate_fairness_session, set_client_seed, validate_client_seed
from casino_play import load_house_play_quote
from casino_house_tables import (
    leave as house_table_leave,
    list_open_tables as house_table_list,
    sit as house_table_sit,
    snapshot as house_table_snapshot,
    start_round as house_table_start,
    resolve_round as house_table_resolve,
)
from casino_jackpot import (
    ensure_closer as jackpot_ensure_closer,
    place_bet as jackpot_place_bet,
    snapshot as jackpot_snapshot,
    subscribe as jackpot_subscribe,
    unsubscribe as jackpot_unsubscribe,
)
from casino_raffle import (
    campaigns_for_user as raffle_campaigns_for_user,
    ensure_closer as raffle_ensure_closer,
    snapshot_for_user as raffle_snapshot_for_user,
    subscribe as raffle_subscribe,
    unsubscribe as raffle_unsubscribe,
)
from casino_roulette_table import (
    ensure_closer as roulette_table_ensure_closer,
    clear_bets as roulette_table_clear_bets,
    place_bet as roulette_table_place_bet,
    place_bets as roulette_table_place_bets,
    snapshot as roulette_table_snapshot,
    subscribe as roulette_table_subscribe,
    unsubscribe as roulette_table_unsubscribe,
)
from casino_poker import (
    act as poker_act,
    create_table as poker_create_table,
    leave as poker_leave,
    sit as poker_sit,
    snapshot as poker_snapshot,
    subscribe_table,
    unsubscribe_table,
)
from routers.internal_casino import (
    CasinoGameCreateRequest,
    CasinoGameJoinRequest,
    CubPlayRequest,
    PrepareCubRequest,
    create_or_resume_game_with_conn,
    enqueue_web_duel_invitation_with_conn,
    join_and_hold_game_with_conn,
    play_cub_with_conn,
    prepare_cub_with_conn,
)

router = APIRouter()

HeadToHead = Literal[
    "pvp_dice",
    "baccara",
    "blackjack",
]


class DuelCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_type: HeadToHead
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    autojoin: bool = True


def _display_name(user: dict, viewer_id: int) -> str:
    return str(user.get("display_name") or user.get("username") or viewer_id)


async def _chat_name(conn, user: dict, viewer_id: int) -> str:
    return await tagged_display_name(conn, viewer_id, _display_name(user, viewer_id))


@router.post("/casino/duels")
async def create_or_join_duel(
    body: DuelCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pvp_dice_ensure_closer()
    waiting_ensure_closer()
    if body.game_type not in HEAD_TO_HEAD_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Этот тип нельзя открыть как дуэль")
    stake = money(body.stake_rub)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            settings = await load_casino_settings(conn)
            if not settings.enabled_games.get(body.game_type, False):
                raise HTTPException(status_code=409, detail="Игра выключена")
            if stake < settings.min_bet_rub or stake > settings.max_bet_rub:
                raise HTTPException(status_code=400, detail="Ставка вне лимита")
            joined = False
            game_id = ""
            if body.autojoin:
                waiting = await waiting_duels(conn, viewer_id)
                target = pick_autojoin_target(
                    waiting,
                    game_type=body.game_type,
                    stake_rub=stake,
                    viewer_id=viewer_id,
                )
                if target:
                    result = await join_and_hold_game_with_conn(
                        conn,
                        CasinoGameJoinRequest(game_id=str(target["game_id"]), opponent_id=viewer_id),
                    )
                    game_id = str(result["game"]["game_id"])
                    joined = True
            if not joined:
                game_id = f"web-{uuid4().hex[:12]}"
                await create_or_resume_game_with_conn(
                    conn,
                    CasinoGameCreateRequest(
                        game_id=game_id,
                        game_type=body.game_type,
                        creator_id=viewer_id,
                        stake_rub=stake,
                    ),
                )
                from casino_open_alerts import enqueue_open_table_alerts, publishes_web_group_invitation

                if publishes_web_group_invitation(body.game_type):
                    await enqueue_web_duel_invitation_with_conn(
                        conn,
                        game_id=game_id,
                        game_type=body.game_type,
                        creator_id=viewer_id,
                        stake_rub=stake,
                    )
                await enqueue_open_table_alerts(
                    conn,
                    game_id=game_id,
                    game_type=body.game_type,
                    creator_id=viewer_id,
                    stake_rub=stake,
                    seats=2,
                    href=f"/casino/duels/{game_id}",
                )
            row = await conn.fetchrow(
                DUEL_ROOM_SELECT_SQL,
                game_id,
            )
            if not row:
                raise HTTPException(status_code=409, detail="Дуэль не сохранилась")
            duel = build_duel_room(row, settings, viewer_id=viewer_id)
            await fill_duel_actors(conn, duel, row)
    return {
        "success": True,
        "joined": joined,
        "created": not joined,
        "game_id": str(row["game_id"]),
        "duel": duel,
    }


class HousePlayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_type: Literal["cub", "baccara", "blackjack", "roulette"] = "cub"
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    #: Roulette only: red / black / zero, a pocket 0–36, or comma-separated pockets.
    bet: str = Field(default=DEFAULT_ROULETTE_BET, max_length=ROULETTE_BET_KEY_MAX_LENGTH)


class HousePlayActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str = Field(min_length=1, max_length=64)
    action: Literal["hit", "stand"]

    @field_validator("game_id")
    @classmethod
    def strip_action_game_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("game_id must not be blank")
        return text


class FairnessSeedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_seed: str

    @field_validator("client_seed")
    @classmethod
    def clean_seed(cls, value: str) -> str:
        return validate_client_seed(value)


@router.post("/casino/play")
async def play_house_round(
    body: HousePlayBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    if body.game_type in {"cub", "baccara", "blackjack"}:
        raise HTTPException(
            status_code=409,
            detail="Эта игра теперь только стол с игроками. Создайте стол на странице игры.",
        )
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            quote = await load_house_play_quote(
                conn,
                game_type=body.game_type,
                stake_rub=body.stake_rub,
                viewer_id=viewer_id,
                roulette_bet=body.bet,
            )
            if not quote["enabled"]:
                raise HTTPException(status_code=409, detail="Игра против казино выключена")
            bound = quote.get("bound_error")
            if bound:
                raise HTTPException(status_code=400, detail=str(bound))
            if body.game_type == ROULETTE_GAME_TYPE:
                result = await play_roulette_with_conn(
                    conn,
                    telegram_id=viewer_id,
                    stake_rub=body.stake_rub,
                    bet=body.bet,
                )
            elif body.game_type in HOUSE_CARD_GAME_TYPES:
                result = await play_house_cards_with_conn(
                    conn,
                    game_type=body.game_type,
                    telegram_id=viewer_id,
                    stake_rub=body.stake_rub,
                )
            else:
                prepared = await prepare_cub_with_conn(conn, PrepareCubRequest(telegram_id=viewer_id))
                result = await play_cub_with_conn(
                    conn,
                    CubPlayRequest(
                        game_id=str(prepared["game_id"]),
                        telegram_id=viewer_id,
                        stake_rub=body.stake_rub,
                    ),
                )
            if str(result.get("phase") or "finished") != "player_turn":
                await maybe_grant_reached_level_bonuses(conn, viewer_id)
    result["quote"] = quote
    return result


@router.get("/casino/play/pending")
async def house_play_pending(
    game_type: Literal["blackjack"] = "blackjack",
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            pending = await load_pending_house_blackjack_with_conn(conn, telegram_id=viewer_id)
    return {"success": True, "game_type": game_type, "pending": pending}


@router.post("/casino/play/action")
async def house_play_action(
    body: HousePlayActionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await act_house_blackjack_with_conn(
                conn,
                telegram_id=viewer_id,
                game_id=body.game_id,
                action=body.action,
            )
            if str(result.get("phase") or "finished") != "player_turn":
                await maybe_grant_reached_level_bonuses(conn, viewer_id)
    return result


class HouseTableCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    max_seats: int = Field(default=1, ge=1, le=6)
    house_bot_count: int = Field(default=2, ge=1, le=6)


class HouseTableSitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    seat_no: int | None = Field(default=None, ge=1, le=6)


@router.post("/casino/house-tables")
async def create_house_table(
    body: HouseTableCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    raise HTTPException(
        status_code=409,
        detail="Стол против казино закрыт. Создайте стол с игроками.",
    )


@router.get("/casino/house-tables")
async def list_user_house_tables(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await house_table_list(conn, viewer_id=viewer_id)


@router.get("/casino/house-tables/{table_id}")
async def get_user_house_table(
    table_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await house_table_snapshot(conn, table_id=table_id.strip(), viewer_id=viewer_id)


@router.post("/casino/house-tables/{table_id}/sit")
async def sit_house_table(
    table_id: str,
    body: HouseTableSitBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await house_table_sit(
                conn,
                table_id=table_id.strip(),
                user_id=viewer_id,
                stake_rub=body.stake_rub,
                seat_no=body.seat_no,
            )


@router.post("/casino/house-tables/{table_id}/leave")
async def leave_house_table(
    table_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await house_table_leave(conn, table_id=table_id.strip(), user_id=viewer_id)


@router.post("/casino/house-tables/{table_id}/start")
async def start_house_table(
    table_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await house_table_start(conn, table_id=table_id.strip(), user_id=viewer_id)


class HouseTableResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["take", "reroll"]


@router.post("/casino/house-tables/{table_id}/resolve")
async def resolve_house_table(
    table_id: str,
    body: HouseTableResolveBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await house_table_resolve(
                conn,
                table_id=table_id.strip(),
                user_id=viewer_id,
                action=body.action,
            )


@router.get("/casino/fairness/session")
async def user_fairness_session(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await public_fairness_session(conn, viewer_id)


@router.post("/casino/fairness/client-seed")
async def user_fairness_client_seed(
    body: FairnessSeedBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await set_client_seed(conn, viewer_id, body.client_seed)


@router.post("/casino/fairness/rotate")
async def user_fairness_rotate(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await rotate_fairness_session(conn, viewer_id)


class PokerCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_seats: int = Field(default=6, ge=2, le=6)


class PokerSitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seat_no: int = Field(ge=1, le=6)
    buy_in_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class PokerActBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["fold", "check", "call", "raise", "all_in"]
    amount_rub: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    expected_version: int = Field(ge=0)


async def _poker_user(
    request: Request,
    access_token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else access_token
    if token:
        payload = decode_token(token)
        if payload.get("scope", "user") != "user":
            raise HTTPException(status_code=403, detail="Use the correct login for this token")
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = await get_web_user_by_id(int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(user)
    return await get_current_user(request, credentials)


@router.post("/casino/poker/tables")
async def create_poker_table(
    body: PokerCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await poker_create_table(conn, creator_id=viewer_id, max_seats=body.max_seats)


@router.get("/casino/poker/tables/{table_id}")
async def get_poker_table(
    table_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await poker_snapshot(conn, table_id=table_id.strip(), viewer_id=viewer_id)


@router.post("/casino/poker/tables/{table_id}/sit")
async def sit_poker_table(
    table_id: str,
    body: PokerSitBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await poker_sit(
                conn,
                table_id=table_id.strip(),
                user_id=viewer_id,
                seat_no=body.seat_no,
                buy_in_rub=body.buy_in_rub,
            )


@router.post("/casino/poker/tables/{table_id}/leave")
async def leave_poker_table(
    table_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await poker_leave(conn, table_id=table_id.strip(), user_id=viewer_id)


@router.post("/casino/poker/tables/{table_id}/act")
async def act_poker_table(
    table_id: str,
    body: PokerActBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await poker_act(
                conn,
                table_id=table_id.strip(),
                user_id=viewer_id,
                action=body.action,
                amount_rub=body.amount_rub,
                expected_version=body.expected_version,
            )


@router.get("/casino/poker/tables/{table_id}/events")
async def poker_table_events(
    table_id: str,
    current_user: dict = Depends(_poker_user),
):
    _ = resolve_client_user_id(current_user)
    key = table_id.strip()

    async def event_stream():
        queue = subscribe_table(key)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe_table(key, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/casino/duels/{game_id}/join")
async def join_duel(
    game_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pvp_dice_ensure_closer()
    waiting_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            settings = await load_casino_settings(conn)
            result = await join_and_hold_game_with_conn(
                conn,
                CasinoGameJoinRequest(game_id=game_id.strip(), opponent_id=viewer_id),
            )
            row = await conn.fetchrow(
                DUEL_ROOM_SELECT_SQL,
                str(result["game"]["game_id"]),
            )
            if not row:
                raise HTTPException(status_code=409, detail="Дуэль не сохранилась")
            duel = build_duel_room(row, settings, viewer_id=viewer_id)
            await fill_duel_actors(conn, duel, row)
    return {
        "success": True,
        "joined": True,
        "game_id": str(row["game_id"]),
        "duel": duel,
    }


@router.post("/casino/duels/{game_id}/cancel")
async def cancel_duel(
    game_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    waiting_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cancelled = await cancel_player_duel(
                conn,
                game_id.strip(),
                actor_id=viewer_id,
            )
            settings = await load_casino_settings(conn)
            row = await conn.fetchrow(DUEL_ROOM_SELECT_SQL, str(cancelled["game_id"]))
            if not row:
                raise HTTPException(status_code=409, detail="Дуэль не сохранилась")
            duel = build_duel_room(row, settings, viewer_id=viewer_id)
            await fill_duel_actors(conn, duel, row)
    return {
        "success": True,
        "cancelled": True,
        "game_id": str(row["game_id"]),
        "duel": duel,
    }


@router.post("/casino/duels/{game_id}/roll")
async def roll_duel(
    game_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pvp_dice_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            settings = await load_casino_settings(conn)
            await record_pvp_dice_roll(conn, game_id=game_id.strip(), telegram_id=viewer_id)
            row = await conn.fetchrow(DUEL_ROOM_SELECT_SQL, game_id.strip())
            if not row:
                raise HTTPException(status_code=409, detail="Дуэль не сохранилась")
            duel = build_duel_room(row, settings, viewer_id=viewer_id)
            await fill_duel_actors(conn, duel, row)
    return {
        "success": True,
        "game_id": str(row["game_id"]),
        "duel": duel,
    }


@router.post("/casino/v2/tables")
async def create_v2_web(
    body: V2WebCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_web_table(conn, body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/join")
async def join_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/bots")
async def add_v2_web_bot(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await add_web_bot(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/start")
async def start_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await start_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/leave")
async def leave_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_web_table(conn, table_id.strip(), body, viewer_id=viewer_id, cancel=False)


@router.post("/casino/v2/tables/{table_id}/cancel")
async def cancel_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_web_table(conn, table_id.strip(), body, viewer_id=viewer_id, cancel=True)


@router.post("/casino/v2/tables/{table_id}/roll")
async def roll_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await roll_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/draw-choice")
async def draw_choice_v2_web(
    table_id: str,
    body: V2WebDrawChoiceBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await choose_draw_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/hit")
async def hit_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await hit_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


@router.post("/casino/v2/tables/{table_id}/stand")
async def stand_v2_web(
    table_id: str,
    body: V2WebVersionBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await stand_web_table(conn, table_id.strip(), body, viewer_id=viewer_id)


class PlayerLookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nickname: str = Field(min_length=2, max_length=32)
    notify_open_tables: bool | None = None


class InboxReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(default_factory=list)


@router.get("/casino/inbox")
async def get_casino_inbox(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_inbox import inbox_snapshot

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await inbox_snapshot(conn, viewer_id)


@router.post("/casino/inbox/read")
async def read_casino_inbox(
    body: InboxReadBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_inbox import inbox_snapshot, mark_read

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await mark_read(conn, viewer_id, body.ids)
            return await inbox_snapshot(conn, viewer_id)


@router.get("/casino/players/me")
async def my_casino_player_profile(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_web_player_profile(conn, viewer_id, viewer_id=viewer_id)


@router.patch("/casino/players/me")
async def patch_casino_player_look(
    body: PlayerLookBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_cosmetics import set_notify_open_tables, upsert_nickname

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await upsert_nickname(conn, viewer_id, body.nickname)
            if body.notify_open_tables is not None:
                await set_notify_open_tables(conn, viewer_id, body.notify_open_tables)
            await touch_presence(conn, viewer_id, body.nickname)
            return await load_web_player_profile(conn, viewer_id, viewer_id=viewer_id)


@router.post("/casino/players/me/avatar")
async def upload_casino_player_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_cosmetics import save_avatar_bytes

    viewer_id = resolve_client_user_id(current_user)
    data = await file.read()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await save_avatar_bytes(conn, viewer_id, data)
            return await load_web_player_profile(conn, viewer_id, viewer_id=viewer_id)


def _history_player_id(player_id: str, viewer_id: int) -> int:
    from casino_player_cosmetics import parse_signed_user_id

    if str(player_id).strip() == "me":
        return viewer_id
    return parse_signed_user_id(player_id)


@router.get("/casino/players/me/history/grouped")
async def my_casino_player_history_grouped(
    per: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_history import load_player_history_grouped

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_player_history_grouped(conn, viewer_id, viewer_id=viewer_id, per=per)


@router.get("/casino/players/me/history")
async def my_casino_player_history(
    limit: int | None = Query(default=None),
    before: str | None = Query(default=None),
    game_type: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_history import load_player_history

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_player_history(
            conn,
            viewer_id,
            viewer_id=viewer_id,
            limit=limit,
            before=before,
            game_type=game_type,
        )


@router.get("/casino/players/{player_id}/history/grouped")
async def casino_player_history_grouped(
    player_id: str,
    per: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_history import load_player_history_grouped

    viewer_id = resolve_client_user_id(current_user)
    uid = _history_player_id(player_id, viewer_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_player_history_grouped(conn, uid, viewer_id=viewer_id, per=per)


@router.get("/casino/players/{player_id}/history")
async def casino_player_history(
    player_id: str,
    limit: int | None = Query(default=None),
    before: str | None = Query(default=None),
    game_type: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_history import load_player_history

    viewer_id = resolve_client_user_id(current_user)
    uid = _history_player_id(player_id, viewer_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_player_history(
            conn,
            uid,
            viewer_id=viewer_id,
            limit=limit,
            before=before,
            game_type=game_type,
        )


@router.get("/casino/players/{player_id}")
async def casino_player_profile(
    player_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_player_cosmetics import parse_signed_user_id

    uid = parse_signed_user_id(player_id)
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_web_player_profile(conn, uid, viewer_id=viewer_id)


class ChatTextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=280)


class ChatChallengeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    peer_id: int = Field(gt=0)
    game_type: HeadToHead
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    in_lobby: bool = False


async def _chat_user(
    request: Request,
    access_token: str | None = Query(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    return await _poker_user(request, access_token=access_token, credentials=credentials)


@router.get("/casino/chat/lobby")
async def get_lobby_chat(
    before_id: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await touch_presence(conn, viewer_id, await _chat_name(conn, current_user, viewer_id))
        room_id = await ensure_lobby_room(conn)
        messages = await list_messages(conn, room_id, before_id=before_id)
        online = await online_users(conn)
    return {"success": True, "room_id": room_id, "messages": messages, "online": online}


@router.post("/casino/chat/lobby")
async def post_lobby_chat(
    body: ChatTextBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            message = await post_lobby(
                conn,
                author_id=viewer_id,
                body=body.body,
                display_name=await _chat_name(conn, current_user, viewer_id),
            )
    return {"success": True, "message": message}


@router.get("/casino/chat/dms")
async def get_chat_dms(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await touch_presence(conn, viewer_id, await _chat_name(conn, current_user, viewer_id))
        threads = await list_dms(conn, viewer_id)
    return {"success": True, "dms": threads}


@router.get("/casino/chat/dms/{peer_id}")
async def get_chat_dm(
    peer_id: int,
    before_id: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await touch_presence(conn, viewer_id, await _chat_name(conn, current_user, viewer_id))
        room_id = await ensure_dm_room(conn, viewer_id, peer_id)
        room = await load_room(conn, room_id)
        from casino_chat import assert_dm_member

        assert_dm_member(room, viewer_id)
        messages = await list_messages(conn, room_id, before_id=before_id)
    return {"success": True, "room_id": room_id, "peer_id": int(peer_id), "messages": messages}


@router.post("/casino/chat/dms/{peer_id}")
async def post_chat_dm(
    peer_id: int,
    body: ChatTextBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            message = await post_dm(
                conn,
                author_id=viewer_id,
                peer_id=int(peer_id),
                body=body.body,
                display_name=await _chat_name(conn, current_user, viewer_id),
            )
    return {"success": True, "message": message}


@router.post("/casino/chat/challenge")
async def post_chat_challenge(
    body: ChatChallengeBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)

    async def _create(conn, *, game_id: str, game_type: str, creator_id: int, stake_rub):
        await create_or_resume_game_with_conn(
            conn,
            CasinoGameCreateRequest(
                game_id=game_id,
                game_type=game_type,
                creator_id=creator_id,
                stake_rub=stake_rub,
            ),
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await create_challenge(
                conn,
                author_id=viewer_id,
                peer_id=body.peer_id,
                game_type=body.game_type,
                stake_rub=body.stake_rub,
                display_name=await _chat_name(conn, current_user, viewer_id),
                in_lobby=body.in_lobby,
                create_duel=_create,
            )
    return {"success": True, **result}


@router.get("/casino/chat/events")
async def casino_chat_events(
    current_user: dict = Depends(_chat_user),
):
    viewer_id = resolve_client_user_id(current_user)

    async def event_stream():
        lobby_q = subscribe_lobby()
        user_q = subscribe_user(viewer_id)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    get_lobby = asyncio.create_task(lobby_q.get())
                    get_user = asyncio.create_task(user_q.get())
                    done, pending = await asyncio.wait(
                        {get_lobby, get_user},
                        timeout=25.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    for task in pending:
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    if not done:
                        yield ": keepalive\n\n"
                        continue
                    for task in done:
                        payload = task.result()
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe_lobby(lobby_q)
            unsubscribe_user(viewer_id, user_q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class JackpotBetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


@router.get("/casino/jackpot")
async def get_jackpot(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    jackpot_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await jackpot_snapshot(conn, viewer_id=viewer_id)
    return {"success": True, **snap}


@router.post("/casino/jackpot/bet")
async def post_jackpot_bet(
    body: JackpotBetBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    jackpot_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await jackpot_place_bet(conn, user_id=viewer_id, amount_rub=body.amount_rub)
    return {"success": True, **snap}


@router.get("/casino/jackpot/events")
async def jackpot_events(
    current_user: dict = Depends(_poker_user),
):
    _ = resolve_client_user_id(current_user)
    jackpot_ensure_closer()

    async def event_stream():
        queue = jackpot_subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            jackpot_unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/casino/raffle")
async def get_raffle(
    campaign_id: int | None = Query(default=None, ge=1),
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    raffle_ensure_closer()
    snap = await raffle_snapshot_for_user(viewer_id, campaign_id)
    return {"success": True, **snap}


@router.get("/casino/raffle/campaigns")
async def get_raffle_campaigns(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    return {"success": True, "campaigns": await raffle_campaigns_for_user(viewer_id)}


@router.get("/casino/raffle/events")
async def raffle_events(
    current_user: dict = Depends(_poker_user),
):
    _ = resolve_client_user_id(current_user)
    raffle_ensure_closer()

    async def event_stream():
        queue = raffle_subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            raffle_unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class TournamentJoinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    promo_code: str | None = Field(default=None, max_length=64)


class TournamentWalletBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tournament_id: int | None = Field(default=None, ge=1)


class WalletSelectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rub", "bonus", "tournament"] = "rub"
    tournament_id: int | None = Field(default=None, ge=1)


@router.get("/casino/wallets")
async def get_casino_wallets(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    """Real money, bonus chips and one entry per joined tournament."""
    from casino_wallet import active_scope, my_wallets

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        scope = await active_scope(conn, viewer_id)
        return {
            "success": True,
            "wallets": await my_wallets(conn, viewer_id),
            "active": scope.public_dict(),
        }


@router.post("/casino/wallet")
async def post_casino_wallet(
    body: WalletSelectBody, current_user: dict = Depends(get_current_user)
) -> dict[str, object]:
    from casino_wallet import my_wallets, parse_scope, set_active_scope

    viewer_id = resolve_client_user_id(current_user)
    scope = parse_scope(body.kind, body.tournament_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            active = await set_active_scope(conn, user_id=viewer_id, scope=scope)
            return {
                "success": True,
                "active": active.public_dict(),
                "wallets": await my_wallets(conn, viewer_id),
            }


@router.post("/casino/wallet/bonus/refill")
async def post_bonus_refill(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    """Top an empty bonus wallet back up to the configured nominal."""
    from casino_wallet import my_wallets, self_refill_bonus_chips

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            result = await self_refill_bonus_chips(conn, user_id=viewer_id)
            return {"success": True, **result, "wallets": await my_wallets(conn, viewer_id)}


@router.get("/casino/tournaments")
async def get_tournaments(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_tournaments import ensure_closer as trn_ensure_closer, list_for_user

    viewer_id = resolve_client_user_id(current_user)
    trn_ensure_closer()
    return {"success": True, "tournaments": await list_for_user(viewer_id)}


@router.get("/casino/tournaments/wallets")
async def get_tournament_wallets(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_tournaments import my_wallets

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {"success": True, "wallets": await my_wallets(conn, viewer_id)}


@router.post("/casino/tournaments/wallet")
async def post_tournament_wallet(
    body: TournamentWalletBody, current_user: dict = Depends(get_current_user)
) -> dict[str, object]:
    from casino_tournaments import my_wallets, set_active_wallet

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            active = await set_active_wallet(
                conn, user_id=viewer_id, tournament_id=body.tournament_id
            )
            return {
                "success": True,
                "active_tournament_id": active,
                "wallets": await my_wallets(conn, viewer_id),
            }


@router.get("/casino/tournaments/{tournament_id}")
async def get_tournament(
    tournament_id: int, current_user: dict = Depends(get_current_user)
) -> dict[str, object]:
    from casino_tournaments import snapshot_for_user

    viewer_id = resolve_client_user_id(current_user)
    snap = await snapshot_for_user(viewer_id, int(tournament_id))
    return {"success": True, **snap}


@router.post("/casino/tournaments/{tournament_id}/join")
async def post_tournament_join(
    tournament_id: int,
    body: TournamentJoinBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_tournaments import ensure_closer as trn_ensure_closer, join_tournament

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await join_tournament(
                conn,
                user_id=viewer_id,
                tournament_id=int(tournament_id),
                promo_code=body.promo_code,
            )
    trn_ensure_closer()
    return {"success": True, **snap}


@router.post("/casino/tournaments/{tournament_id}/rebuy")
async def post_tournament_rebuy(
    tournament_id: int, current_user: dict = Depends(get_current_user)
) -> dict[str, object]:
    from casino_tournaments import rebuy_tournament

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rebuy_tournament(
                conn, user_id=viewer_id, tournament_id=int(tournament_id)
            )
    return {"success": True, **snap}


@router.get("/casino/tournaments/{tournament_id}/events")
async def tournament_events(tournament_id: int, current_user: dict = Depends(_poker_user)):
    from casino_tournaments import ensure_closer as trn_ensure_closer, subscribe, unsubscribe

    _ = resolve_client_user_id(current_user)
    trn_ensure_closer()

    async def event_stream():
        queue = subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    if payload.get("tournament_id") not in (None, int(tournament_id)):
                        continue
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class RouletteTableBetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bet: str = Field(min_length=1, max_length=120)

class RouletteTableChipBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    bet: str = Field(min_length=1, max_length=120)


class RouletteTableBetsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chips: list[RouletteTableChipBody] = Field(default_factory=list, max_length=80)


class RouletteTableClearBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bet: str | None = None


@router.get("/casino/roulette-table")
async def get_roulette_table(
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    roulette_table_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_snapshot(conn, viewer_id=viewer_id)
    return {"success": True, **snap}


@router.post("/casino/roulette-table/bet")
async def post_roulette_table_bet(
    body: RouletteTableBetBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    roulette_table_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_place_bet(
                conn, user_id=viewer_id, amount_rub=body.amount_rub, bet=body.bet
            )
    return {"success": True, **snap}


@router.post("/casino/roulette-table/bets")
async def post_roulette_table_bets(
    body: RouletteTableBetsBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    roulette_table_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_place_bets(conn, user_id=viewer_id, chips=body.chips)
    return {"success": True, **snap}


@router.post("/casino/roulette-table/clear")
async def post_roulette_table_clear(
    body: RouletteTableClearBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    roulette_table_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_clear_bets(conn, user_id=viewer_id, bet=body.bet)
    return {"success": True, **snap}


@router.get("/casino/roulette-table/events")
async def roulette_table_events(
    current_user: dict = Depends(_poker_user),
):
    _ = resolve_client_user_id(current_user)
    roulette_table_ensure_closer()

    async def event_stream():
        queue = roulette_table_subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            roulette_table_unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class ClanCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    name: str


class ClanJoinBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str


class ClanKickBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int


class ClanTransferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int


@router.get("/casino/clan")
async def get_my_clan(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await my_clan(conn, viewer_id)


@router.post("/casino/clan")
async def post_create_clan(body: ClanCreateBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await create_clan(conn, user_id=viewer_id, tag=body.tag, name=body.name)
    return {"success": True, "clan": clan}


@router.post("/casino/clan/join")
async def post_join_clan(body: ClanJoinBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await join_clan(conn, user_id=viewer_id, code=body.code)
    return {"success": True, "clan": clan}


@router.post("/casino/clan/leave")
async def post_leave_clan(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_clan(conn, user_id=viewer_id)


@router.post("/casino/clan/kick")
async def post_kick_clan(body: ClanKickBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await kick_member(conn, owner_id=viewer_id, target_id=body.user_id)
    return {"success": True, "clan": clan}


@router.post("/casino/clan/invite")
async def post_rotate_invite(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await rotate_invite(conn, owner_id=viewer_id)
    return {"success": True, "clan": clan}


@router.post("/casino/clan/transfer")
async def post_transfer_clan(body: ClanTransferBody, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await transfer_owner(conn, owner_id=viewer_id, target_id=body.user_id)
    return {"success": True, "clan": clan}


@router.post("/casino/clan/disband")
async def post_disband_clan(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await disband_clan(conn, actor_id=viewer_id)


class FixedRoomCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    seat_count: int = Field(ge=2, le=20)


class ClanWarCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stake_rub: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    fighters_needed: int = Field(ge=1, le=20)


@router.get("/casino/rooms")
async def get_fixed_rooms(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import list_open as rooms_list_open

    viewer_id = resolve_client_user_id(current_user)
    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            payload = await rooms_list_open(conn, viewer_id=viewer_id)
    return {"success": True, **payload}


@router.get("/casino/rooms/events")
async def fixed_room_events(current_user: dict = Depends(_poker_user)):
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import subscribe as rooms_subscribe
    from casino_fixed_rooms import unsubscribe as rooms_unsubscribe

    _ = resolve_client_user_id(current_user)
    rooms_ensure_closer()

    async def event_stream():
        queue = rooms_subscribe()
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            rooms_unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/casino/rooms/{room_id}")
async def get_fixed_room(room_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import snapshot as rooms_snapshot

    viewer_id = resolve_client_user_id(current_user)
    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_snapshot(conn, room_id.strip(), viewer_id=viewer_id)
    return {"success": True, **snap}


@router.post("/casino/rooms")
async def post_fixed_room(
    body: FixedRoomCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_fixed_rooms import create_room as rooms_create
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer

    viewer_id = resolve_client_user_id(current_user)
    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_create(
                conn, user_id=viewer_id, stake_rub=body.stake_rub, seat_count=body.seat_count
            )
    return {"success": True, **snap}


@router.post("/casino/rooms/{room_id}/join")
async def post_join_fixed_room(room_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import join_room as rooms_join

    viewer_id = resolve_client_user_id(current_user)
    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_join(conn, user_id=viewer_id, room_id=room_id.strip())
    return {"success": True, **snap}


@router.post("/casino/rooms/{room_id}/cancel")
async def post_cancel_fixed_room(room_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import cancel_room as rooms_cancel

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_cancel(conn, user_id=viewer_id, room_id=room_id.strip())
    return {"success": True, **snap}


@router.post("/casino/rooms/{room_id}/leave")
async def post_leave_fixed_room(room_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import leave_room as rooms_leave

    viewer_id = resolve_client_user_id(current_user)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_leave(conn, user_id=viewer_id, room_id=room_id.strip())
    return {"success": True, **snap}


@router.post("/casino/rooms/{room_id}/bots")
async def post_fixed_room_bot(room_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_fixed_rooms import add_bot as rooms_add_bot
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer

    viewer_id = resolve_client_user_id(current_user)
    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_add_bot(conn, user_id=viewer_id, room_id=room_id.strip())
    return {"success": True, **snap}


@router.get("/casino/wars")
async def get_clan_wars(current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_clan_wars import ensure_closer as wars_ensure_closer
    from casino_clan_wars import list_open as wars_list_open

    viewer_id = resolve_client_user_id(current_user)
    wars_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            payload = await wars_list_open(conn, viewer_id=viewer_id)
    return {"success": True, **payload}


@router.get("/casino/wars/{war_id}")
async def get_clan_war(war_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_clan_wars import ensure_closer as wars_ensure_closer
    from casino_clan_wars import snapshot as wars_snapshot

    viewer_id = resolve_client_user_id(current_user)
    wars_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await wars_snapshot(conn, war_id.strip(), viewer_id=viewer_id)
    return {"success": True, **snap}


@router.post("/casino/wars")
async def post_clan_war(
    body: ClanWarCreateBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, object]:
    from casino_clan_wars import create_war as wars_create
    from casino_clan_wars import ensure_closer as wars_ensure_closer

    viewer_id = resolve_client_user_id(current_user)
    wars_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await wars_create(
                conn, user_id=viewer_id, stake_rub=body.stake_rub, fighters_needed=body.fighters_needed
            )
    return {"success": True, **snap}


@router.post("/casino/wars/{war_id}/accept")
async def post_accept_clan_war(war_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_clan_wars import accept_war as wars_accept
    from casino_clan_wars import ensure_closer as wars_ensure_closer

    viewer_id = resolve_client_user_id(current_user)
    wars_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await wars_accept(conn, user_id=viewer_id, war_id=war_id.strip())
    return {"success": True, **snap}


@router.post("/casino/wars/{war_id}/join")
async def post_join_clan_war(war_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, object]:
    from casino_clan_wars import ensure_closer as wars_ensure_closer
    from casino_clan_wars import join_war as wars_join

    viewer_id = resolve_client_user_id(current_user)
    wars_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await wars_join(conn, user_id=viewer_id, war_id=war_id.strip())
    return {"success": True, **snap}


"""PvP dice after both seats fill: HMAC web/house rolls, 30s closer, roll prompts."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from fastapi import HTTPException

from casino_cards import pair_commit

logger = logging.getLogger("casino_pvp_dice")

PVP_DICE_GAME_TYPE = "pvp_dice"
PVP_DICE_ROLL_TIMEOUT_SECONDS = 30
EVENT_ROLL_PROMPT = "pvp_roll_prompt"
EVENT_ROLL_PROMPT_GROUP = "pvp_roll_prompt_group"
HMAC_DATA_KEY = "pvp_dice_hmac"

_ACTIVE_PVP_COLUMNS = """
game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
opponent_hold_id, counterparty_kind, game_data, status, state_version,
game_state, outcome, created_at, started_at, outcome_committed_at, finished_at,
game_chat_binding_id, game_chat_id, game_chat_binding_revision
"""

_closer_started = False
_closer_task = None


def _as_map(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def is_pvp_dice(game: Mapping[str, object]) -> bool:
    return str(game.get("game_type") or "") == PVP_DICE_GAME_TYPE


def is_player_counterparty(game: Mapping[str, object]) -> bool:
    return str(game.get("counterparty_kind") or "player") != "pvp_robot"


def rolls_needed(game: Mapping[str, object]) -> int:
    pvp = _as_map(_as_map(game.get("game_data")).get("pvp"))
    try:
        rounds = int(pvp.get("rounds"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        rounds = 1
    return 2 if rounds == 2 else 1


def dice_rolls(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 6:
            out.append(number)
    return out


def hmac_pip(seed: str, *, game_id: str, seat: str, index: int, kind: str) -> int:
    digest = hmac.new(
        seed.encode("utf-8"),
        f"{game_id}:{seat}:{index}:{kind}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (int(digest[:8], 16) % 6) + 1


def parse_deadline(state: Mapping[str, object], started_at: object) -> datetime | None:
    raw = state.get("roll_deadline_at")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return _utc(parsed)
        except ValueError:
            pass
    if isinstance(started_at, datetime):
        return _utc(started_at) + timedelta(seconds=PVP_DICE_ROLL_TIMEOUT_SECONDS)
    return None


def seat_for_player(game: Mapping[str, object], telegram_id: int) -> str | None:
    if int(game["creator_id"]) == int(telegram_id):
        return "creator"
    opponent = game.get("opponent_id")
    if opponent is not None and int(opponent) == int(telegram_id):
        return "opponent"
    return None


def merge_join_state(
    state: Mapping[str, object],
    *,
    deadline_at: datetime,
) -> dict[str, object]:
    merged = dict(state)
    if "creator_rolls" not in merged or not isinstance(merged.get("creator_rolls"), list):
        merged["creator_rolls"] = dice_rolls(merged.get("creator_rolls"))
    else:
        merged["creator_rolls"] = dice_rolls(merged.get("creator_rolls"))
    if "opponent_rolls" not in merged or not isinstance(merged.get("opponent_rolls"), list):
        merged["opponent_rolls"] = dice_rolls(merged.get("opponent_rolls"))
    else:
        merged["opponent_rolls"] = dice_rolls(merged.get("opponent_rolls"))
    if not merged.get("roll_deadline_at"):
        merged["roll_deadline_at"] = _iso(deadline_at)
    house = _as_map(merged.get("house_rolled"))
    merged["house_rolled"] = {
        "creator": [int(i) for i in house.get("creator") or [] if str(i).isdigit() or isinstance(i, int)],
        "opponent": [int(i) for i in house.get("opponent") or [] if str(i).isdigit() or isinstance(i, int)],
    }
    return merged


def merge_persisted_game_state(
    existing: Mapping[str, object],
    incoming: Mapping[str, object],
) -> dict[str, object]:
    """Keep HMAC rolls and the join deadline if the bot snapshot is behind."""
    merged = {**dict(existing), **dict(incoming)}
    for key in ("creator_rolls", "opponent_rolls"):
        if key not in existing and key not in incoming:
            continue
        old = dice_rolls(existing.get(key))
        new = dice_rolls(incoming.get(key))
        merged[key] = new if len(new) >= len(old) else old
    if existing.get("roll_deadline_at") and not incoming.get("roll_deadline_at"):
        merged["roll_deadline_at"] = existing["roll_deadline_at"]
    old_house = _as_map(existing.get("house_rolled")) if "house_rolled" in existing else {}
    new_house = _as_map(incoming.get("house_rolled")) if "house_rolled" in incoming else {}
    if old_house or new_house:
        merged["house_rolled"] = {
            "creator": _merge_index_lists(old_house.get("creator"), new_house.get("creator")),
            "opponent": _merge_index_lists(old_house.get("opponent"), new_house.get("opponent")),
        }
    return merged


def _merge_index_lists(left: object, right: object) -> list[int]:
    values: set[int] = set()
    for raw in (left, right):
        if not isinstance(raw, list):
            continue
        for item in raw:
            try:
                values.add(int(item))
            except (TypeError, ValueError):
                continue
    return sorted(values)


def is_group_chat_id(chat_id: object) -> bool:
    return isinstance(chat_id, int) and not isinstance(chat_id, bool) and chat_id < 0


def prompt_text(*, timeout_seconds: int = PVP_DICE_ROLL_TIMEOUT_SECONDS, group: bool = False) -> str:
    timeout = f"Если не кинете за {int(timeout_seconds)} с — казино кинет за вас."
    if group:
        return f"Кинь 🎲 в этот чат.\n{timeout}"
    return (
        "Соперник зашёл. Кинь 🎲 в игровой чат или кнопку на сайте.\n"
        f"{timeout}"
    )


def face_text(*, seat: str, value: int, house: bool) -> str:
    who = "создатель" if seat == "creator" else "соперник"
    source = "казино за игрока" if house else "бросок"
    return f"Кубик {who}: {int(value)} ({source})."


def outcome_from_rolls(
    *,
    creator_rolls: Sequence[int],
    opponent_rolls: Sequence[int],
    creator_id: int,
    opponent_id: int,
    house_rolled: Mapping[str, object] | None = None,
) -> dict[str, object]:
    creator_sum = sum(int(value) for value in creator_rolls)
    opponent_sum = sum(int(value) for value in opponent_rolls)
    payload: dict[str, object] = {
        "creator_score": creator_sum,
        "opponent_score": opponent_sum,
        "creator_rolls": list(creator_rolls),
        "opponent_rolls": list(opponent_rolls),
        "house_rolled": dict(house_rolled or {}),
    }
    if creator_sum == opponent_sum:
        payload["kind"] = "draw"
        payload["reason"] = "draw"
        return payload
    winner_id = creator_id if creator_sum > opponent_sum else opponent_id
    payload["kind"] = "winner"
    payload["winner_id"] = winner_id
    return payload


def room_roll_fields(
    row: Mapping[str, object],
    *,
    viewer_id: int | None,
) -> dict[str, object]:
    state = _as_map(row.get("game_state"))
    needed = rolls_needed(row)
    creator = dice_rolls(state.get("creator_rolls"))
    opponent = dice_rolls(state.get("opponent_rolls"))
    occupied = row.get("opponent_id") is not None
    status = str(row.get("status") or "")
    active = (
        status == "active"
        and occupied
        and is_pvp_dice(row)
        and is_player_counterparty(row)
    )
    seat = seat_for_player(row, viewer_id) if viewer_id is not None else None
    my_count = 0
    if seat == "creator":
        my_count = len(creator)
    elif seat == "opponent":
        my_count = len(opponent)
    can_roll = bool(active and seat and my_count < needed)
    deadline = state.get("roll_deadline_at") if active else None
    return {
        "rolls_needed": needed,
        "my_roll_count": my_count,
        "can_roll": can_roll,
        "roll_deadline_at": deadline if isinstance(deadline, str) else None,
        "house_will_roll": bool(active and (len(creator) < needed or len(opponent) < needed)),
    }


async def _enqueue_raw_outbox(
    conn,
    *,
    game_id: str,
    event_type: str,
    recipient_id: int,
    chat_id: int,
    text: str,
) -> None:
    if recipient_id <= 0:
        return
    payload = json.dumps(
        {"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"},
        separators=(",", ":"),
    )
    await conn.execute(
        """
        INSERT INTO casino_notification_outbox (event_key, event_type, game_id, recipient_id, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (game_id, event_type, recipient_id) DO NOTHING
        """,
        f"casino:{game_id}:{event_type}:{recipient_id}",
        event_type,
        game_id,
        int(recipient_id),
        payload,
    )


async def enqueue_roll_prompts(
    conn,
    *,
    game_id: str,
    creator_id: int,
    opponent_id: int,
    chat_id: int | None,
) -> None:
    """Group-only when the duel is bound to a group; DMs only when there is no group."""
    if is_group_chat_id(chat_id):
        owner = int(creator_id) if int(creator_id) > 0 else int(opponent_id)
        await _enqueue_raw_outbox(
            conn,
            game_id=game_id,
            event_type=EVENT_ROLL_PROMPT_GROUP,
            recipient_id=owner,
            chat_id=int(chat_id),
            text=prompt_text(group=True),
        )
        return
    text = prompt_text()
    for recipient in (int(creator_id), int(opponent_id)):
        await _enqueue_raw_outbox(
            conn,
            game_id=game_id,
            event_type=EVENT_ROLL_PROMPT,
            recipient_id=recipient,
            chat_id=recipient,
            text=text,
        )


async def enqueue_face(
    conn,
    *,
    game_id: str,
    creator_id: int,
    opponent_id: int,
    seat: str,
    index: int,
    value: int,
    house: bool,
    chat_id: int | None = None,
) -> None:
    text = face_text(seat=seat, value=value, house=house)
    event_type = f"pvp_dice_face_{seat}{index}"
    if is_group_chat_id(chat_id):
        owner = int(creator_id) if int(creator_id) > 0 else int(opponent_id)
        await _enqueue_raw_outbox(
            conn,
            game_id=game_id,
            event_type=event_type,
            recipient_id=owner,
            chat_id=int(chat_id),
            text=text,
        )
        return
    for recipient in (int(creator_id), int(opponent_id)):
        await _enqueue_raw_outbox(
            conn,
            game_id=game_id,
            event_type=event_type,
            recipient_id=recipient,
            chat_id=recipient,
            text=text,
        )


def _as_chat_id(value: object) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _chat_id_from_game(game: Mapping[str, object]) -> int | None:
    bound = _as_chat_id(game.get("game_chat_id"))
    state_chat = _as_chat_id(_as_map(game.get("game_state")).get("chat_id"))
    if is_group_chat_id(bound):
        return bound
    if is_group_chat_id(state_chat):
        return state_chat
    return bound if bound is not None else state_chat


async def touch_active_holds(conn, game_id: str) -> None:
    """Keep live-game holds valid past the 2h waiting-room expiry."""
    await conn.execute(
        """
        UPDATE casino_balance_holds
        SET expires_at = now() + interval '2 hours'
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
    )


def _hmac_seed(game: Mapping[str, object]) -> str | None:
    blob = _as_map(_as_map(game.get("game_data")).get(HMAC_DATA_KEY))
    seed = blob.get("seed")
    return str(seed) if isinstance(seed, str) and seed else None


async def activate_on_join(conn, game: Mapping[str, object]) -> dict[str, object]:
    """Set deadline + HMAC seed and ping both players. Returns latest game row dict."""
    if not is_pvp_dice(game) or not is_player_counterparty(game):
        return dict(game)
    if game.get("opponent_id") is None:
        return dict(game)
    await touch_active_holds(conn, str(game["game_id"]))
    state = _as_map(game.get("game_state"))
    started = game.get("started_at")
    if not isinstance(started, datetime):
        started = datetime.now(timezone.utc)
    deadline = _utc(started) + timedelta(seconds=PVP_DICE_ROLL_TIMEOUT_SECONDS)
    merged = merge_join_state(state, deadline_at=deadline)
    data = _as_map(game.get("game_data"))
    hmac_blob = _as_map(data.get(HMAC_DATA_KEY))
    seed = str(hmac_blob.get("seed") or "")
    if not seed:
        seed = secrets.token_hex(32)
        hmac_blob = {"seed": seed, "commit": pair_commit(seed)}
    game_id = str(game["game_id"])
    row = await conn.fetchrow(
        """
        UPDATE casino_games
        SET game_state = $2::jsonb,
            game_data = game_data || $3::jsonb,
            state_version = state_version + 1,
            updated_at = now()
        WHERE game_id = $1 AND status = 'active'
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, counterparty_kind, game_data, status, state_version,
                  game_state, outcome, created_at, started_at, outcome_committed_at, finished_at,
                  game_chat_binding_id, game_chat_id, game_chat_binding_revision
        """,
        game_id,
        json.dumps(merged, separators=(",", ":")),
        json.dumps({HMAC_DATA_KEY: hmac_blob}, separators=(",", ":")),
    )
    latest = dict(row) if row else dict(game)
    await enqueue_roll_prompts(
        conn,
        game_id=game_id,
        creator_id=int(latest["creator_id"]),
        opponent_id=int(latest["opponent_id"]),
        chat_id=_chat_id_from_game(latest),
    )
    return latest


def _house_map(state: Mapping[str, object]) -> dict[str, list[int]]:
    house = _as_map(state.get("house_rolled"))
    return {
        "creator": [int(i) for i in (house.get("creator") or []) if isinstance(i, int) or str(i).isdigit()],
        "opponent": [int(i) for i in (house.get("opponent") or []) if isinstance(i, int) or str(i).isdigit()],
    }


async def _write_state(conn, *, game_id: str, expected_version: int, state: Mapping[str, object]):
    row = await conn.fetchrow(
        """
        UPDATE casino_games
        SET game_state = $3::jsonb, state_version = state_version + 1, updated_at = now()
        WHERE game_id = $1 AND status = 'active' AND state_version = $2
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, counterparty_kind, game_data, status, state_version,
                  game_state, outcome, created_at, started_at, outcome_committed_at, finished_at,
                  game_chat_binding_id, game_chat_id, game_chat_binding_revision
        """,
        game_id,
        expected_version,
        json.dumps(dict(state), separators=(",", ":")),
    )
    if not row:
        raise HTTPException(status_code=409, detail="Game state version conflicts")
    return dict(row)


async def maybe_finish_pvp_dice(conn, game: Mapping[str, object]) -> dict[str, object]:
    if not is_pvp_dice(game) or str(game.get("status") or "") != "active":
        return dict(game)
    if not is_player_counterparty(game) or game.get("opponent_id") is None:
        return dict(game)
    state = _as_map(game.get("game_state"))
    needed = rolls_needed(game)
    creator = dice_rolls(state.get("creator_rolls"))
    opponent = dice_rolls(state.get("opponent_rolls"))
    if len(creator) < needed or len(opponent) < needed:
        return dict(game)
    from routers.internal_casino import (
        CasinoGameIdRequest,
        CasinoGameOutcomeRequest,
        commit_game_outcome_with_conn,
        settle_committed_outcome_with_conn,
    )

    payload = outcome_from_rolls(
        creator_rolls=creator,
        opponent_rolls=opponent,
        creator_id=int(game["creator_id"]),
        opponent_id=int(game["opponent_id"]),
        house_rolled=_house_map(state),
    )
    winner_id = payload.get("winner_id") if payload.get("kind") == "winner" else None
    committed = await commit_game_outcome_with_conn(
        conn,
        CasinoGameOutcomeRequest(
            game_id=str(game["game_id"]),
            winner_id=int(winner_id) if winner_id is not None else None,
            expected_state_version=int(game.get("state_version") or 0),
            outcome=payload,
        ),
    )
    settled = await settle_committed_outcome_with_conn(
        conn,
        CasinoGameIdRequest(game_id=str(game["game_id"])),
    )
    return settled.get("game") or committed.get("game") or dict(game)


async def record_roll(
    conn,
    *,
    game_id: str,
    telegram_id: int,
    value: int | None = None,
    house: bool = False,
) -> dict[str, object]:
    from routers.internal_casino import _game_for_update, lock_casino_game

    await lock_casino_game(conn, game_id)
    game = await _game_for_update(conn, game_id)
    if not is_pvp_dice(game):
        raise HTTPException(status_code=400, detail="Это не дуэль кубика")
    if str(game.get("status") or "") != "active":
        raise HTTPException(status_code=409, detail="Дуэль уже не принимает броски")
    if not is_player_counterparty(game):
        raise HTTPException(status_code=409, detail="Робот кидает сам")
    await touch_active_holds(conn, str(game["game_id"]))
    if not _hmac_seed(game):
        game = await activate_on_join(conn, game)
    seat = seat_for_player(game, telegram_id)
    if not seat:
        raise HTTPException(status_code=403, detail="Бросок только для участников")
    needed = rolls_needed(game)
    state = _as_map(game.get("game_state"))
    key = f"{seat}_rolls"
    current = dice_rolls(state.get(key))
    if len(current) >= needed:
        finished = await maybe_finish_pvp_dice(conn, game)
        return {"success": True, "idempotent": True, "game": as_game_payload(finished)}
    index = len(current)
    if value is not None:
        try:
            pip = int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Грань кубика 1–6") from exc
        if pip < 1 or pip > 6:
            raise HTTPException(status_code=400, detail="Грань кубика 1–6")
        used_house = house
    else:
        seed = _hmac_seed(game)
        if not seed:
            raise HTTPException(status_code=409, detail="HMAC сид ещё не готов")
        kind = "house" if house else "player"
        pip = hmac_pip(seed, game_id=str(game["game_id"]), seat=seat, index=index, kind=kind)
        used_house = house
    current.append(pip)
    state[key] = current
    if used_house:
        house_map = _house_map(state)
        marked = list(house_map.get(seat) or [])
        if index not in marked:
            marked.append(index)
        house_map[seat] = marked
        state["house_rolled"] = house_map
    written = await _write_state(
        conn,
        game_id=str(game["game_id"]),
        expected_version=int(game.get("state_version") or 0),
        state=state,
    )
    await enqueue_face(
        conn,
        game_id=str(game["game_id"]),
        creator_id=int(written["creator_id"]),
        opponent_id=int(written["opponent_id"]),
        seat=seat,
        index=index,
        value=pip,
        house=used_house,
        chat_id=_chat_id_from_game(written),
    )
    finished = await maybe_finish_pvp_dice(conn, written)
    return {"success": True, "idempotent": False, "game": as_game_payload(finished)}


def as_game_payload(game: Mapping[str, object]) -> dict[str, object]:
    if game.get("stake_rub") is not None and game.get("game_id") is not None and "bet_rub" not in game:
        return dict(game)
    from routers.internal_casino import _game_response

    return _game_response(game)


async def house_fill_game(conn, game: Mapping[str, object], *, now: datetime | None = None) -> dict[str, object]:
    if not is_pvp_dice(game) or not is_player_counterparty(game):
        return dict(game)
    if str(game.get("status") or "") != "active" or game.get("opponent_id") is None:
        return dict(game)
    clock = now or datetime.now(timezone.utc)
    state = _as_map(game.get("game_state"))
    deadline = parse_deadline(state, game.get("started_at"))
    if deadline is None or clock < deadline:
        return dict(game)
    await touch_active_holds(conn, str(game["game_id"]))
    if not _hmac_seed(game):
        game = await activate_on_join(conn, game)
        state = _as_map(game.get("game_state"))
    seed = _hmac_seed(game)
    if not seed:
        return dict(game)
    needed = rolls_needed(game)
    changed = False
    house_map = _house_map(state)
    for seat in ("creator", "opponent"):
        current = dice_rolls(state.get(f"{seat}_rolls"))
        while len(current) < needed:
            index = len(current)
            pip = hmac_pip(
                seed,
                game_id=str(game["game_id"]),
                seat=seat,
                index=index,
                kind="house",
            )
            current.append(pip)
            marked = list(house_map.get(seat) or [])
            marked.append(index)
            house_map[seat] = marked
            changed = True
            await enqueue_face(
                conn,
                game_id=str(game["game_id"]),
                creator_id=int(game["creator_id"]),
                opponent_id=int(game["opponent_id"]),
                seat=seat,
                index=index,
                value=pip,
                house=True,
                chat_id=_chat_id_from_game(game),
            )
        state[f"{seat}_rolls"] = current
    if not changed:
        return await maybe_finish_pvp_dice(conn, game)
    state["house_rolled"] = house_map
    written = await _write_state(
        conn,
        game_id=str(game["game_id"]),
        expected_version=int(game.get("state_version") or 0),
        state=state,
    )
    return await maybe_finish_pvp_dice(conn, written)


def _is_stale_hold_error(exc: BaseException) -> bool:
    detail = getattr(exc, "detail", None)
    text = str(detail if detail is not None else exc).lower()
    return "expired" in text or "not active" in text or "holds are required" in text


async def _recover_failed_fill(conn, game: Mapping[str, object], exc: BaseException) -> None:
    """Take a rotten overdue game out of the closer queue without blocking siblings."""
    game_id = str(game.get("game_id") or "")
    if not game_id:
        return
    from routers.internal_casino import (
        CasinoGameIdRequest,
        CasinoGameOutcomeRequest,
        _mark_game_manual_review,
        commit_game_outcome_with_conn,
        settle_committed_outcome_with_conn,
    )

    try:
        async with conn.transaction():
            if _is_stale_hold_error(exc):
                await commit_game_outcome_with_conn(
                    conn,
                    CasinoGameOutcomeRequest(
                        game_id=game_id,
                        winner_id=None,
                        expected_state_version=int(game.get("state_version") or 0),
                        outcome={"kind": "timeout", "reason": "pvp_dice_hold_expired"},
                    ),
                )
                await settle_committed_outcome_with_conn(conn, CasinoGameIdRequest(game_id=game_id))
                return
            await _mark_game_manual_review(
                conn,
                game_id=game_id,
                reason=f"pvp_dice_house_fill:{exc}"[:240],
            )
    except Exception:
        logger.exception("pvp dice recover failed game_id=%s", game_id)
        try:
            async with conn.transaction():
                await _mark_game_manual_review(
                    conn,
                    game_id=game_id,
                    reason=f"pvp_dice_house_fill:{exc}"[:240],
                )
        except Exception:
            logger.exception("pvp dice manual_review failed game_id=%s", game_id)


async def house_fill_if_due(conn, game_id: str, *, now: datetime | None = None) -> dict[str, object] | None:
    """Fill one overdue duel without scanning the rest of the closer queue."""
    clock = now or datetime.now(timezone.utc)
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_ACTIVE_PVP_COLUMNS}
                FROM casino_games
                WHERE game_id = $1
                  AND status = 'active'
                  AND game_type = 'pvp_dice'
                  AND opponent_id IS NOT NULL
                  AND COALESCE(counterparty_kind, 'player') = 'player'
                FOR UPDATE SKIP LOCKED
                """,
                game_id,
            )
            if not row:
                return None
            return await house_fill_game(conn, dict(row), now=clock)
    except Exception:
        logger.exception("pvp dice house fill one game_id=%s", game_id)
        return None


async def house_fill_due(conn, *, now: datetime | None = None) -> int:
    ids = await conn.fetch(
        """
        SELECT game_id
        FROM casino_games
        WHERE status = 'active'
          AND game_type = 'pvp_dice'
          AND opponent_id IS NOT NULL
          AND COALESCE(counterparty_kind, 'player') = 'player'
          AND started_at IS NOT NULL
          AND started_at <= now() - make_interval(secs => $1)
        ORDER BY started_at ASC, game_id ASC
        LIMIT 20
        """,
        PVP_DICE_ROLL_TIMEOUT_SECONDS,
    )
    filled = 0
    clock = now or datetime.now(timezone.utc)
    for item in ids:
        game_id = str(item["game_id"])
        before: dict[str, object] | None = None
        try:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"""
                    SELECT {_ACTIVE_PVP_COLUMNS}
                    FROM casino_games
                    WHERE game_id = $1
                      AND status = 'active'
                      AND game_type = 'pvp_dice'
                    FOR UPDATE SKIP LOCKED
                    """,
                    game_id,
                )
                if not row:
                    continue
                before = dict(row)
                after = await house_fill_game(conn, before, now=clock)
                if after.get("state_version") != before.get("state_version") or str(after.get("status")) != "active":
                    filled += 1
        except Exception as exc:
            if _is_stale_hold_error(exc):
                logger.warning("pvp dice house fill stale hold game_id=%s: %s", game_id, exc)
                snapshot = before or {"game_id": game_id, "state_version": 0}
                await _recover_failed_fill(conn, snapshot, exc)
            else:
                logger.exception("pvp dice house fill failed game_id=%s", game_id)
    return filled


def ensure_closer() -> None:
    global _closer_started, _closer_task
    if _closer_started:
        return
    _closer_started = True
    _closer_task = asyncio.create_task(_closer_loop())
    from casino_waiting import ensure_closer as waiting_ensure_closer

    waiting_ensure_closer()


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(1)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await house_fill_due(conn)
        except Exception:
            logger.exception("pvp dice closer")

"""Casino lobby chat, pairwise DMs, presence, and duel challenges."""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import uuid4

from fastapi import HTTPException

from bot_user_avatars import (
    bot_user_avatar_public_url,
    resolve_bot_user_avatar_path,
    schedule_prefetch_bot_user_avatars,
)
from casino_duels import reserved_opponent_of
from casino_finance import HEAD_TO_HEAD_GAME_TYPES, load_casino_settings, money

MAX_BODY = 280
RATE_WINDOW_SECONDS = 10
RATE_MAX_MESSAGES = 3
PRESENCE_ONLINE_SECONDS = 45
HISTORY_LIMIT = 80
LOBBY_LINK_RE = re.compile(r"(https?://|t\.me/|tg://)", re.IGNORECASE)

_lobby_subs: set[asyncio.Queue] = set()
_user_subs: dict[int, set[asyncio.Queue]] = defaultdict(set)
_rate: dict[tuple[int, int], deque[float]] = {}


def dm_pair(user_a: int, user_b: int) -> tuple[int, int]:
    lo, hi = sorted((int(user_a), int(user_b)))
    if lo == hi or lo == 0:
        raise ValueError("dm needs two distinct users")
    return lo, hi


def sanitize_body(raw: str) -> str:
    text = (raw or "").replace("\x00", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    if len(text) > MAX_BODY:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_BODY} символов")
    return text


def lobby_blocks_links(text: str) -> bool:
    return bool(LOBBY_LINK_RE.search(text or ""))


def rate_limit_ok(user_id: int, room_id: int, *, now: float | None = None) -> bool:
    stamp = now if now is not None else datetime.now(timezone.utc).timestamp()
    key = (int(user_id), int(room_id))
    bucket = _rate.setdefault(key, deque())
    cutoff = stamp - RATE_WINDOW_SECONDS
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_MAX_MESSAGES:
        return False
    bucket.append(stamp)
    return True


def presence_is_online(last_seen: datetime | None, *, now: datetime | None = None) -> bool:
    if last_seen is None:
        return False
    current = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return (current - last_seen) <= timedelta(seconds=PRESENCE_ONLINE_SECONDS)


def join_allowed(*, reserved_opponent_id: int | None, joiner_id: int) -> bool:
    if reserved_opponent_id is None:
        return True
    return int(reserved_opponent_id) == int(joiner_id)


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")


def _as_map(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def actor_payload(user_id: int, display_name: str, *, avatar_url: str | None) -> dict[str, object]:
    name = (display_name or "").strip() or str(user_id)
    initial = name.lstrip("@")[:1].upper() or "?"
    return {
        "user_id": int(user_id),
        "display_name": name,
        "initial": initial,
        "avatar_url": avatar_url,
    }


def message_payload(row: Mapping[str, object], actor: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "room_id": int(row["room_id"]),
        "kind": str(row["kind"]),
        "body": str(row.get("body") or ""),
        "payload": _as_map(row.get("payload")),
        "created_at": _iso(row.get("created_at")),
        "author": dict(actor),
    }


def subscribe_lobby() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    _lobby_subs.add(queue)
    return queue


def unsubscribe_lobby(queue: asyncio.Queue) -> None:
    _lobby_subs.discard(queue)


def subscribe_user(user_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    _user_subs[int(user_id)].add(queue)
    return queue


def unsubscribe_user(user_id: int, queue: asyncio.Queue) -> None:
    bucket = _user_subs.get(int(user_id))
    if not bucket:
        return
    bucket.discard(queue)
    if not bucket:
        _user_subs.pop(int(user_id), None)


def _emit(queues: Sequence[asyncio.Queue], payload: Mapping[str, object]) -> None:
    for queue in list(queues):
        try:
            queue.put_nowait(dict(payload))
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(dict(payload))
            except asyncio.QueueFull:
                pass


def publish_lobby(payload: Mapping[str, object]) -> None:
    _emit(list(_lobby_subs), payload)


def publish_user(user_id: int, payload: Mapping[str, object]) -> None:
    _emit(list(_user_subs.get(int(user_id), ())), payload)


def publish_presence(payload: Mapping[str, object]) -> None:
    publish_lobby(payload)
    for user_id, queues in list(_user_subs.items()):
        _emit(list(queues), payload)


def actor_chip(actors: Mapping[int, Mapping[str, object]], user_id: int) -> dict[str, object]:
    from casino_default_avatar import default_avatar_url_for_user

    uid = int(user_id)
    found = actors.get(uid)
    if found:
        return dict(found)
    return actor_payload(uid, str(uid), avatar_url=default_avatar_url_for_user(uid))


async def public_actors(conn, user_ids: Sequence[int]) -> dict[int, dict[str, object]]:
    """Batch lobby/profile chips. Missing users still get a numeric fallback name."""
    from casino_player_cosmetics import load_cosmetics_map

    out: dict[int, dict[str, object]] = {}
    seen: set[int] = set()
    ordered: list[int] = []
    for raw in user_ids:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid in seen:
            continue
        seen.add(uid)
        ordered.append(uid)
    schedule_prefetch_bot_user_avatars(ordered)
    cosmetics = await load_cosmetics_map(conn, ordered)
    for uid in ordered:
        out[uid] = await _actor(
            conn,
            uid,
            cosmetics=cosmetics.get(uid),
            cosmetics_loaded=True,
        )
    return out


async def _actor(
    conn,
    user_id: int,
    *,
    cosmetics: Mapping[str, object] | None = None,
    cosmetics_loaded: bool = False,
) -> dict[str, object]:
    from casino_player_cosmetics import apply_cosmetics, load_cosmetics_map

    if not cosmetics_loaded:
        loaded = await load_cosmetics_map(conn, [int(user_id)])
        cosmetics = loaded.get(int(user_id))

    presence = await conn.fetchrow(
        "SELECT display_name FROM casino_chat_presence WHERE user_id = $1",
        int(user_id),
    )
    name = str(presence["display_name"] or "").strip() if presence else ""
    if not name:
        row = await conn.fetchrow(
            "SELECT username, first_name FROM bot_users WHERE user_id = $1",
            int(user_id),
        )
        if row:
            username = str(row["username"] or "").strip()
            first = str(row["first_name"] or "").strip()
            name = f"@{username}" if username else first
    if not name:
        web = await conn.fetchrow(
            "SELECT display_name, username FROM web_users WHERE telegram_user_id = $1 LIMIT 1",
            int(user_id),
        )
        if web:
            name = str(web["display_name"] or web["username"] or "").strip()
        if not name:
            web_id = await conn.fetchrow(
                "SELECT display_name, username FROM web_users WHERE client_user_id = $1 LIMIT 1",
                int(user_id),
            )
            if web_id:
                name = str(web_id["display_name"] or web_id["username"] or "").strip()
    telegram_url = None
    if resolve_bot_user_avatar_path(int(user_id)):
        telegram_url = bot_user_avatar_public_url(user_id)
    display, avatar = apply_cosmetics(
        int(user_id),
        name or str(user_id),
        avatar_url=telegram_url,
        cosmetics=cosmetics,
    )
    return actor_payload(user_id, display, avatar_url=avatar)


async def touch_presence(conn, user_id: int, display_name: str) -> dict[str, object]:
    name = (display_name or "").strip()[:64] or str(user_id)
    await conn.execute(
        """
        INSERT INTO casino_chat_presence (user_id, display_name, last_seen)
        VALUES ($1, $2, now())
        ON CONFLICT (user_id) DO UPDATE
        SET display_name = EXCLUDED.display_name, last_seen = now()
        """,
        int(user_id),
        name,
    )
    actor = await _actor(conn, user_id)
    publish_presence({"type": "presence", "online": True, "user": actor})
    return actor


async def ensure_lobby_room(conn) -> int:
    row = await conn.fetchrow("SELECT id FROM casino_chat_rooms WHERE kind = 'lobby'")
    if row:
        return int(row["id"])
    created = await conn.fetchrow(
        """
        INSERT INTO casino_chat_rooms (kind) VALUES ('lobby')
        ON CONFLICT DO NOTHING
        RETURNING id
        """
    )
    if created:
        return int(created["id"])
    row = await conn.fetchrow("SELECT id FROM casino_chat_rooms WHERE kind = 'lobby'")
    if not row:
        raise HTTPException(status_code=500, detail="Лобби-чат не создан")
    return int(row["id"])


async def ensure_dm_room(conn, user_a: int, user_b: int) -> int:
    try:
        lo, hi = dm_pair(user_a, user_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Нельзя писать себе") from exc
    row = await conn.fetchrow(
        """
        SELECT id FROM casino_chat_rooms
        WHERE kind = 'dm' AND user_lo = $1 AND user_hi = $2
        """,
        lo,
        hi,
    )
    if row:
        return int(row["id"])
    created = await conn.fetchrow(
        """
        INSERT INTO casino_chat_rooms (kind, user_lo, user_hi)
        VALUES ('dm', $1, $2)
        ON CONFLICT (user_lo, user_hi) WHERE kind = 'dm' DO NOTHING
        RETURNING id
        """,
        lo,
        hi,
    )
    if created:
        return int(created["id"])
    row = await conn.fetchrow(
        """
        SELECT id FROM casino_chat_rooms
        WHERE kind = 'dm' AND user_lo = $1 AND user_hi = $2
        """,
        lo,
        hi,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Личка не создалась")
    return int(row["id"])


def assert_dm_member(room: Mapping[str, object], user_id: int) -> None:
    if str(room["kind"]) != "dm":
        raise HTTPException(status_code=400, detail="Это не личка")
    members = {int(room["user_lo"]), int(room["user_hi"])}
    if int(user_id) not in members:
        raise HTTPException(status_code=403, detail="Чужая переписка")


async def load_room(conn, room_id: int) -> dict[str, Any]:
    row = await conn.fetchrow("SELECT * FROM casino_chat_rooms WHERE id = $1", int(room_id))
    if not row:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return dict(row)


async def list_messages(conn, room_id: int, *, before_id: int = 0) -> list[dict[str, object]]:
    if before_id > 0:
        rows = await conn.fetch(
            """
            SELECT id, room_id, author_id, kind, body, payload, created_at
            FROM casino_chat_messages
            WHERE room_id = $1 AND id < $2
            ORDER BY id DESC
            LIMIT $3
            """,
            int(room_id),
            int(before_id),
            HISTORY_LIMIT,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, room_id, author_id, kind, body, payload, created_at
            FROM casino_chat_messages
            WHERE room_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            int(room_id),
            HISTORY_LIMIT,
        )
    actors = await public_actors(conn, [int(row["author_id"]) for row in rows])
    out: list[dict[str, object]] = []
    for row in reversed(list(rows)):
        out.append(message_payload(row, actors[int(row["author_id"])]))
    return out


async def insert_message(
    conn,
    *,
    room_id: int,
    author_id: int,
    kind: str,
    body: str,
    payload: Mapping[str, object] | None = None,
    lobby: bool,
) -> dict[str, object]:
    if not rate_limit_ok(author_id, room_id):
        raise HTTPException(status_code=429, detail="Слишком часто — подожди пару секунд")
    if lobby and lobby_blocks_links(body):
        raise HTTPException(status_code=400, detail="Ссылки в общем чате нельзя")
    row = await conn.fetchrow(
        """
        INSERT INTO casino_chat_messages (room_id, author_id, kind, body, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        RETURNING id, room_id, author_id, kind, body, payload, created_at
        """,
        int(room_id),
        int(author_id),
        kind,
        body,
        json.dumps(dict(payload or {}), ensure_ascii=False),
    )
    actor = await _actor(conn, author_id)
    return message_payload(row, actor)


async def online_users(conn) -> list[dict[str, object]]:
    rows = await conn.fetch(
        """
        SELECT user_id, display_name, last_seen
        FROM casino_chat_presence
        WHERE last_seen > now() - ($1::text || ' seconds')::interval
        ORDER BY last_seen DESC
        LIMIT 80
        """,
        str(PRESENCE_ONLINE_SECONDS),
    )
    now = datetime.now(timezone.utc)
    ids: list[int] = []
    for row in rows:
        if not presence_is_online(row["last_seen"], now=now):
            continue
        ids.append(int(row["user_id"]))
    actors = await public_actors(conn, ids)
    return [actors[uid] for uid in ids]


async def list_dms(conn, user_id: int) -> list[dict[str, object]]:
    rows = await conn.fetch(
        """
        SELECT r.id, r.user_lo, r.user_hi,
               m.body, m.kind, m.created_at, m.author_id
        FROM casino_chat_rooms r
        LEFT JOIN LATERAL (
            SELECT body, kind, created_at, author_id
            FROM casino_chat_messages
            WHERE room_id = r.id
            ORDER BY id DESC
            LIMIT 1
        ) m ON TRUE
        WHERE r.kind = 'dm' AND (r.user_lo = $1 OR r.user_hi = $1)
        ORDER BY COALESCE(m.created_at, r.created_at) DESC
        LIMIT 40
        """,
        int(user_id),
    )
    out: list[dict[str, object]] = []
    for row in rows:
        peer_id = int(row["user_hi"] if int(row["user_lo"]) == int(user_id) else row["user_lo"])
        out.append(
            {
                "room_id": int(row["id"]),
                "peer": await _actor(conn, peer_id),
                "last_body": str(row["body"] or ""),
                "last_kind": str(row["kind"] or "text"),
                "last_at": _iso(row["created_at"]),
            }
        )
    return out


def emit_message(*, lobby: bool, members: Sequence[int], message: Mapping[str, object]) -> None:
    event = {"type": "message", "lobby": lobby, "message": dict(message)}
    if lobby:
        publish_lobby(event)
        return
    for member in members:
        publish_user(member, event)


async def post_lobby(conn, *, author_id: int, body: str, display_name: str) -> dict[str, object]:
    await touch_presence(conn, author_id, display_name)
    room_id = await ensure_lobby_room(conn)
    text = sanitize_body(body)
    message = await insert_message(
        conn, room_id=room_id, author_id=author_id, kind="text", body=text, lobby=True
    )
    emit_message(lobby=True, members=(), message=message)
    return message


async def post_dm(conn, *, author_id: int, peer_id: int, body: str, display_name: str) -> dict[str, object]:
    await touch_presence(conn, author_id, display_name)
    room_id = await ensure_dm_room(conn, author_id, peer_id)
    text = sanitize_body(body)
    message = await insert_message(
        conn, room_id=room_id, author_id=author_id, kind="text", body=text, lobby=False
    )
    emit_message(lobby=False, members=(author_id, peer_id), message=message)
    return message


async def create_challenge(
    conn,
    *,
    author_id: int,
    peer_id: int,
    game_type: str,
    stake_rub: Decimal,
    display_name: str,
    in_lobby: bool,
    create_duel,
) -> dict[str, object]:
    if int(author_id) == int(peer_id):
        raise HTTPException(status_code=400, detail="Нельзя вызвать себя")
    if game_type not in HEAD_TO_HEAD_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Этот тип нельзя как дуэль")
    settings = await load_casino_settings(conn)
    if not settings.enabled_games.get(game_type, False):
        raise HTTPException(status_code=409, detail="Игра выключена")
    stake = money(stake_rub)
    if stake < settings.min_bet_rub or stake > settings.max_bet_rub:
        raise HTTPException(status_code=400, detail="Ставка вне лимита")
    await touch_presence(conn, author_id, display_name)
    game_id = f"web-{uuid4().hex[:12]}"
    await create_duel(conn, game_id=game_id, game_type=game_type, creator_id=author_id, stake_rub=stake)
    await conn.execute(
        """
        UPDATE casino_games
        SET game_state = COALESCE(game_state, '{}'::jsonb)
            || jsonb_build_object('reserved_opponent_id', $2::bigint)
        WHERE game_id = $1
        """,
        game_id,
        int(peer_id),
    )
    payload = {
        "game_id": game_id,
        "game_type": game_type,
        "stake_rub": float(stake),
        "peer_id": int(peer_id),
        "from_id": int(author_id),
    }
    body = f"Вызов: {game_type} на {stake} ₽"
    if in_lobby:
        room_id = await ensure_lobby_room(conn)
        message = await insert_message(
            conn,
            room_id=room_id,
            author_id=author_id,
            kind="challenge",
            body=body,
            payload=payload,
            lobby=True,
        )
        emit_message(lobby=True, members=(), message=message)
    else:
        room_id = await ensure_dm_room(conn, author_id, peer_id)
        message = await insert_message(
            conn,
            room_id=room_id,
            author_id=author_id,
            kind="challenge",
            body=body,
            payload=payload,
            lobby=False,
        )
        emit_message(lobby=False, members=(author_id, peer_id), message=message)
    return {"message": message, "game_id": game_id, "duel": payload}


def reserved_blocks_joiner(game: Mapping[str, object], joiner_id: int) -> bool:
    reserved = reserved_opponent_of(game)
    return not join_allowed(reserved_opponent_id=reserved, joiner_id=joiner_id)

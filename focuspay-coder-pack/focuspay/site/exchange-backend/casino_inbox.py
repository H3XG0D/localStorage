"""Website casino inbox: join notices and live sessions with a go-to-game href."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from casino_chat import publish_user, public_actors
from casino_finance import money
from casino_pvp_cards import card_duel_is_unfinishable

EVENT_YOU_JOINED = "you_joined"
EVENT_PLAYER_JOINED = "player_joined"

_LABELS = {
    "pvp_dice": "Кубики",
    "pvp_emoji": "Кубики",
    "cub": "Кубик",
    "baccara": "Баккара",
    "blackjack": "Блэкджек",
    "holdem": "Холдем",
    "roulette": "Рулетка",
    "jackpot": "Джекпот",
    "fixed_room": "Комната",
    "clan_war": "Война кланов",
    "russian_draughts": "Русские шашки",
}

_STATUS = {
    "waiting": "ожидание",
    "active": "идёт",
    "open": "набор",
    "countdown": "скоро старт",
    "ready": "набор",
    "running": "идёт",
    "accepted": "набор",
    "locked": "идёт",
}


def game_href(*, kind: str, game_id: str, game_type: str = "") -> str:
    gid = str(game_id or "").strip()
    gtype = str(game_type or "").strip()
    kind_key = str(kind or "").strip().lower()
    if kind_key == "v2" or (kind_key not in {"duel", "house", "poker", "room", "war", "jackpot", "roulette"} and gid.startswith("web-")):
        return f"/casino/tables/{gid}"
    if kind_key == "house":
        return f"/casino/play/pvp_dice?mode=house&view=table&ht={gid}"
    if kind_key == "poker" or gtype == "holdem":
        return f"/casino/poker/{gid}"
    if kind_key == "draughts" or gtype == "russian_draughts":
        return f"/casino/draughts/{gid}"
    if kind_key == "room" or gtype == "fixed_room":
        return f"/casino/rooms/{gid}"
    if kind_key == "war" or gtype == "clan_war":
        return f"/casino/wars/{gid}"
    if kind_key == "jackpot" or gtype == "jackpot":
        return "/casino/play/jackpot"
    if kind_key == "roulette" or gtype == "roulette":
        return "/casino/play/roulette?mode=players"
    if kind_key == "duel":
        return f"/casino/duels/{gid}"
    if gtype in {"pvp_dice", "pvp_emoji", "cub", "baccara", "blackjack"}:
        return f"/casino/tables/{gid}" if gid else f"/casino/play/{gtype if gtype != 'pvp_emoji' else 'pvp_dice'}?mode=players"
    return f"/casino/play/pvp_dice?mode=players"


def rewrite_stored_href(href: str, *, kind: str = "", game_id: str = "", game_type: str = "") -> str:
    """Recompute play links so leftover /casino/duels/web-… rows open v2 tables."""
    fresh = game_href(kind=kind, game_id=game_id, game_type=game_type)
    raw = str(href or "").strip()
    if not raw:
        return fresh
    kind_key = str(kind or "").strip().lower()
    if "/casino/duels/" in raw and kind_key != "duel":
        return fresh
    return raw


def game_label(game_type: str) -> str:
    key = str(game_type or "").strip()
    return _LABELS.get(key, key or "Игра")


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value or "")


def _stake_text(value: object) -> str:
    if value is None or value == "":
        return ""
    amount = money(value)
    if amount <= 0:
        return ""
    return f"{amount} ₽"


def _session_title(*, game_type: str, game_id: str) -> str:
    short = str(game_id or "")[:8].upper()
    label = game_label(game_type)
    return f"{label} · стол #{short}" if short else label


def _item_payload(
    *,
    event_type: str,
    game_id: str,
    href: str,
    title: str,
    body: str,
    payload: Mapping[str, object],
    created_at: datetime | None = None,
    item_id: int | None = None,
    read_at: object | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "event_type": event_type,
        "game_id": game_id,
        "href": href,
        "title": title,
        "body": body,
        "payload": dict(payload),
        "created_at": _iso(created_at or datetime.now(timezone.utc)),
        "read_at": _iso(read_at) if read_at else None,
    }
    if item_id is not None:
        row["id"] = int(item_id)
    return row


async def push_item(
    conn,
    *,
    recipient_id: int,
    event_type: str,
    game_id: str,
    href: str,
    title: str,
    body: str,
    payload: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    uid = int(recipient_id)
    if uid == 0:
        return None
    blob = dict(payload or {})
    item = _item_payload(
        event_type=event_type,
        game_id=str(game_id),
        href=href,
        title=title,
        body=body,
        payload=blob,
    )
    await conn.execute(
        """
        /* inbox:insert */
        INSERT INTO casino_web_inbox (
            recipient_id, event_type, game_id, href, title, body, payload
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (recipient_id, event_type, game_id) DO NOTHING
        """,
        uid,
        event_type,
        str(game_id),
        href,
        title,
        body,
        json.dumps(blob, separators=(",", ":"), default=str),
    )
    publish_user(uid, {"type": "inbox", "item": item})
    return item


async def notify_player_joined(
    conn,
    *,
    joiner_id: int,
    other_ids: Sequence[int],
    kind: str,
    game_id: str,
    game_type: str,
    stake_rub: object | None = None,
    notify_joiner: bool = True,
) -> None:
    href = game_href(kind=kind, game_id=game_id, game_type=game_type)
    label = game_label(game_type)
    stake = _stake_text(stake_rub)
    body = f"{label} · {stake}".strip(" ·") if stake else label
    payload = {"actor_id": int(joiner_id), "kind": kind, "game_type": game_type}
    if notify_joiner:
        await push_item(
            conn,
            recipient_id=int(joiner_id),
            event_type=EVENT_YOU_JOINED,
            game_id=str(game_id),
            href=href,
            title="Вы зашли в игру",
            body=body,
            payload=payload,
        )
    seen = {int(joiner_id)}
    for raw in other_ids:
        try:
            other = int(raw)
        except (TypeError, ValueError):
            continue
        if other == 0 or other in seen:
            continue
        seen.add(other)
        await push_item(
            conn,
            recipient_id=other,
            event_type=EVENT_PLAYER_JOINED,
            game_id=str(game_id),
            href=href,
            title="В игру зашли",
            body=body,
            payload=payload,
        )


def _as_map(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


async def list_inbox(conn, user_id: int, *, limit: int = 40) -> list[dict[str, object]]:
    rows = await conn.fetch(
        """
        SELECT id, event_type, game_id, href, title, body, payload, read_at, created_at
        FROM casino_web_inbox
        WHERE recipient_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        int(user_id),
        int(limit),
    )
    actor_ids: list[int] = []
    parsed: list[tuple[Any, dict[str, Any]]] = []
    for row in rows:
        payload = _as_map(row["payload"])
        parsed.append((row, payload))
        try:
            actor_ids.append(int(payload.get("actor_id") or 0))
        except (TypeError, ValueError):
            continue
    actors = await public_actors(conn, [uid for uid in actor_ids if uid])
    items: list[dict[str, object]] = []
    for row, payload in parsed:
        title = str(row["title"] or "")
        event_type = str(row["event_type"] or "")
        if event_type == EVENT_PLAYER_JOINED:
            actor = actors.get(int(payload.get("actor_id") or 0))
            name = str((actor or {}).get("display_name") or "").strip()
            if name:
                title = f"{name} зашёл в игру"
        href = rewrite_stored_href(
            str(row["href"] or ""),
            kind=str(payload.get("kind") or ""),
            game_id=str(row["game_id"] or ""),
            game_type=str(payload.get("game_type") or ""),
        )
        items.append(
            _item_payload(
                event_type=event_type,
                game_id=str(row["game_id"] or ""),
                href=href,
                title=title,
                body=str(row["body"] or ""),
                payload=payload,
                created_at=row["created_at"],
                item_id=int(row["id"]),
                read_at=row["read_at"],
            )
        )
    return items


async def mark_read(conn, user_id: int, item_ids: Sequence[int]) -> int:
    ids = [int(item) for item in item_ids if int(item) > 0]
    if not ids:
        return 0
    result = await conn.execute(
        """
        UPDATE casino_web_inbox
        SET read_at = COALESCE(read_at, now())
        WHERE recipient_id = $1 AND id = ANY($2::bigint[])
        """,
        int(user_id),
        ids,
    )
    text = str(result or "")
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _session(
    *,
    kind: str,
    game_id: str,
    game_type: str,
    status: str,
    stake_rub: object = None,
    can_cancel: bool = False,
    can_leave: bool = False,
) -> dict[str, object]:
    href = game_href(kind=kind, game_id=game_id, game_type=game_type)
    stake = _stake_text(stake_rub)
    status_label = _STATUS.get(str(status or ""), str(status or ""))
    bits = [part for part in (stake, status_label) if part]
    return {
        "kind": kind,
        "game_id": str(game_id),
        "game_type": str(game_type or ""),
        "href": href,
        "title": _session_title(game_type=game_type, game_id=game_id),
        "body": " · ".join(bits),
        "status": str(status or ""),
        "stake_rub": str(money(stake_rub)) if stake_rub not in (None, "") else "0.00",
        "can_cancel": bool(can_cancel),
        "can_leave": bool(can_leave),
    }


async def list_sessions(conn, user_id: int) -> list[dict[str, object]]:
    uid = int(user_id)
    sessions: list[dict[str, object]] = []
    duels = await conn.fetch(
        """
        SELECT game_id, game_type, status, bet_rub, creator_id, opponent_id,
               rng_commit, counterparty_kind
        FROM casino_games
        WHERE status IN ('waiting', 'active')
          AND (creator_id = $1 OR opponent_id = $1)
          AND COALESCE(counterparty_kind, 'player') <> 'pvp_robot'
        ORDER BY COALESCE(started_at, created_at) DESC
        LIMIT 20
        """,
        uid,
    )
    for row in duels:
        status = str(row["status"] or "")
        stuck = card_duel_is_unfinishable(row)
        sessions.append(
            _session(
                kind="duel",
                game_id=str(row["game_id"]),
                game_type=str(row["game_type"] or "pvp_dice"),
                status=status,
                stake_rub=row["bet_rub"],
                can_cancel=(status == "waiting" and int(row["creator_id"]) == uid) or stuck,
            )
        )
    tables = await conn.fetch(
        """
        SELECT t.table_id, t.game_type, t.status, t.stake_rub, t.creator_id
        FROM casino_v2_table_seats s
        JOIN casino_v2_tables t ON t.id = s.table_id
        WHERE s.telegram_id = $1
          AND s.status = 'seated'
          AND t.status IN ('open', 'ready', 'running', 'tie_break_running', 'outcome_committed', 'settling')
        ORDER BY t.updated_at DESC
        LIMIT 20
        """,
        uid,
    )
    for row in tables:
        gtype = str(row["game_type"] or "pvp_dice")
        if gtype == "pvp_emoji":
            gtype = "pvp_dice"
        status = str(row["status"] or "")
        is_creator = int(row["creator_id"]) == uid
        lobby = status in {"open", "ready"}
        sessions.append(
            _session(
                kind="v2",
                game_id=str(row["table_id"]),
                game_type=gtype,
                status=status,
                stake_rub=row["stake_rub"],
                can_cancel=is_creator and lobby,
                can_leave=not is_creator and lobby,
            )
        )
    houses = await conn.fetch(
        """
        SELECT t.table_id, t.game_type, t.status, s.stake_rub
        FROM casino_house_table_seats s
        JOIN casino_house_tables t ON t.id = s.table_pk
        WHERE s.telegram_id = $1
          AND s.kind = 'player'
          AND t.status IN ('open', 'running')
        ORDER BY t.updated_at DESC
        LIMIT 20
        """,
        uid,
    )
    for row in houses:
        status = str(row["status"] or "")
        sessions.append(
            _session(
                kind="house",
                game_id=str(row["table_id"]),
                game_type=str(row["game_type"] or "pvp_dice"),
                status=status,
                stake_rub=row["stake_rub"],
                can_leave=status == "open",
            )
        )
    poker = await conn.fetch(
        """
        SELECT t.table_id, t.status, t.big_blind_rub
        FROM casino_poker_seats s
        JOIN casino_poker_tables t ON t.id = s.table_pk
        WHERE s.user_id = $1
          AND s.status = 'sitting'
          AND t.status IN ('open', 'running')
        ORDER BY t.updated_at DESC
        LIMIT 20
        """,
        uid,
    )
    for row in poker:
        sessions.append(
            _session(
                kind="poker",
                game_id=str(row["table_id"]),
                game_type="holdem",
                status=str(row["status"] or ""),
                stake_rub=row["big_blind_rub"],
            )
        )
    rooms = await conn.fetch(
        """
        SELECT r.room_id, r.status, r.stake_rub
        FROM casino_fixed_room_seats s
        JOIN casino_fixed_room_rounds r ON r.id = s.room_pk
        WHERE s.user_id = $1
          AND r.status IN ('open', 'countdown', 'locked')
        ORDER BY r.created_at DESC
        LIMIT 20
        """,
        uid,
    )
    for row in rooms:
        sessions.append(
            _session(
                kind="room",
                game_id=str(row["room_id"]),
                game_type="fixed_room",
                status=str(row["status"] or ""),
                stake_rub=row["stake_rub"],
            )
        )
    wars = await conn.fetch(
        """
        SELECT w.war_id, w.status, w.stake_rub
        FROM casino_clan_war_fighters f
        JOIN casino_clan_wars w ON w.id = f.war_pk
        WHERE f.user_id = $1
          AND w.status IN ('open', 'accepted', 'locked')
        ORDER BY w.created_at DESC
        LIMIT 20
        """,
        uid,
    )
    for row in wars:
        sessions.append(
            _session(
                kind="war",
                game_id=str(row["war_id"]),
                game_type="clan_war",
                status=str(row["status"] or ""),
                stake_rub=row["stake_rub"],
            )
        )
    jackpots = await conn.fetch(
        """
        SELECT r.round_id, r.status, b.amount_rub
        FROM casino_jackpot_bets b
        JOIN casino_jackpot_rounds r ON r.id = b.round_pk
        WHERE b.user_id = $1 AND r.status IN ('open', 'locked')
        ORDER BY r.created_at DESC
        LIMIT 1
        """,
        uid,
    )
    for row in jackpots:
        sessions.append(
            _session(
                kind="jackpot",
                game_id=str(row["round_id"]),
                game_type="jackpot",
                status=str(row["status"] or ""),
                stake_rub=row["amount_rub"],
            )
        )
    roulette = await conn.fetch(
        """
        SELECT r.round_id, r.status, SUM(b.stake_rub) AS stake_rub
        FROM casino_roulette_bets b
        JOIN casino_roulette_rounds r ON r.id = b.round_pk
        WHERE b.user_id = $1 AND r.status IN ('open', 'locked', 'spinning')
        GROUP BY r.round_id, r.status
        ORDER BY r.round_id DESC
        LIMIT 1
        """,
        uid,
    )
    for row in roulette:
        sessions.append(
            _session(
                kind="roulette",
                game_id=str(row["round_id"]),
                game_type="roulette",
                status=str(row["status"] or ""),
                stake_rub=row["stake_rub"],
            )
        )
    return sessions


async def inbox_snapshot(conn, user_id: int) -> dict[str, object]:
    items = await list_inbox(conn, user_id)
    sessions = await list_sessions(conn, user_id)
    unread = sum(1 for item in items if not item.get("read_at"))
    return {
        "success": True,
        "unread": unread,
        "items": items,
        "sessions": sessions,
    }

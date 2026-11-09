"""Player clans: invite-only teams and weekly turnover ranking. No clan wallet."""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from fastapi import HTTPException

from casino_finance import money
from casino_weekly_wager import CASHBACK_GAME_TYPES, current_week_start

TAG_RE = re.compile(r"^[A-Z0-9]{3,8}$")
JOIN_COOLDOWN = timedelta(hours=24)
NAME_MIN = 3
NAME_MAX = 32
INVITE_ALPHABET = string.ascii_uppercase + string.digits
TOP_LIMIT = 20
DEFAULT_MAX_MEMBERS = 20


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_tag(raw: str) -> str:
    tag = (raw or "").strip().upper()
    if not TAG_RE.fullmatch(tag):
        raise HTTPException(status_code=400, detail="Тег: 3–8 символов A–Z и 0–9")
    return tag


def parse_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if len(name) < NAME_MIN or len(name) > NAME_MAX:
        raise HTTPException(status_code=400, detail="Имя команды: 3–32 символа")
    return name


def parse_invite_code(raw: str) -> str:
    code = re.sub(r"[^A-Z0-9]", "", (raw or "").strip().upper())
    if len(code) < 6 or len(code) > 16:
        raise HTTPException(status_code=400, detail="Неверный код приглашения")
    return code


def new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))


def format_clan_display_name(display_name: str, tag: str | None) -> str:
    name = (display_name or "").strip() or "Игрок"
    if not tag:
        return name
    prefix = f"[{tag}]"
    if name.startswith(prefix):
        return name
    return f"{prefix} {name}"


def wager_belongs(*, settled_at: datetime, joined_at: datetime, left_at: datetime | None) -> bool:
    if settled_at < joined_at:
        return False
    if left_at is not None and settled_at >= left_at:
        return False
    return True


def aggregate_clan_wagers(
    wagers: Sequence[tuple[int, Decimal, datetime]],
    memberships: Sequence[tuple[int, int, datetime, datetime | None]],
) -> dict[int, Decimal]:
    """Map clan_id -> attributed wager. memberships are (clan_id, user_id, joined_at, left_at)."""
    totals: dict[int, Decimal] = {}
    for clan_id, user_id, joined_at, left_at in memberships:
        for wager_user, amount, settled_at in wagers:
            if wager_user != user_id:
                continue
            if not wager_belongs(settled_at=settled_at, joined_at=joined_at, left_at=left_at):
                continue
            totals[clan_id] = money(totals.get(clan_id, 0) + money(amount))
    return totals


def _unique_violation(exc: BaseException) -> bool:
    return type(exc).__name__ == "UniqueViolationError"


def _as_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


PLAYER_WAGER_SQL = """
WITH week AS (
    SELECT ($1::date::timestamp AT TIME ZONE 'Europe/Moscow') AS start_at,
           (($1::date + 7)::timestamp AT TIME ZONE 'Europe/Moscow') AS end_at
),
player_wagers AS (
    SELECT g.creator_id AS user_id, g.bet_rub::numeric AS wager_rub, g.finished_at AS settled_at
    FROM casino_games g, week
    WHERE g.status = 'finished'
      AND g.finished_at >= week.start_at
      AND g.finished_at < week.end_at
      AND g.game_type = ANY($2::text[])
    UNION ALL
    SELECT g.opponent_id, g.bet_rub::numeric, g.finished_at
    FROM casino_games g, week
    WHERE g.status = 'finished'
      AND g.opponent_id IS NOT NULL
      AND g.finished_at >= week.start_at
      AND g.finished_at < week.end_at
      AND g.game_type = ANY($2::text[])
    UNION ALL
    SELECT (item.key)::bigint, (item.value)::numeric, h.settled_at
    FROM casino_poker_hands h, week, jsonb_each_text(h.wager_json) AS item
    WHERE h.settled_at IS NOT NULL
      AND h.settled_at >= week.start_at
      AND h.settled_at < week.end_at
    UNION ALL
    SELECT (item.key)::bigint, (item.value)::numeric, r.settled_at
    FROM casino_jackpot_rounds r, week, jsonb_each_text(r.wager_json) AS item
    WHERE r.settled_at IS NOT NULL
      AND r.settled_at >= week.start_at
      AND r.settled_at < week.end_at
    UNION ALL
    SELECT (item.key)::bigint, (item.value)::numeric, r.settled_at
    FROM casino_fixed_room_rounds r, week, jsonb_each_text(r.wager_json) AS item
    WHERE r.settled_at IS NOT NULL
      AND r.settled_at >= week.start_at
      AND r.settled_at < week.end_at
    UNION ALL
    SELECT (item.key)::bigint, (item.value)::numeric, r.settled_at
    FROM casino_clan_wars r, week, jsonb_each_text(r.wager_json) AS item
    WHERE r.settled_at IS NOT NULL
      AND r.settled_at >= week.start_at
      AND r.settled_at < week.end_at
)
"""


async def load_clan_settings(conn) -> tuple[bool, int]:
    rows = await conn.fetch(
        "/* clan:settings */ SELECT key, value FROM casino_settings WHERE key = ANY($1::text[])",
        ["clans_enabled", "clan_max_members"],
    )
    by_key = {str(row["key"]): row["value"] for row in rows}
    enabled = True
    raw_enabled = by_key.get("clans_enabled")
    if isinstance(raw_enabled, Mapping) and isinstance(raw_enabled.get("enabled"), bool):
        enabled = bool(raw_enabled["enabled"])
    max_members = DEFAULT_MAX_MEMBERS
    raw_max = by_key.get("clan_max_members")
    if isinstance(raw_max, Mapping) and isinstance(raw_max.get("value"), (int, float)) and not isinstance(raw_max.get("value"), bool):
        max_members = int(raw_max["value"])
    return enabled, max(2, min(max_members, 50))


async def _require_enabled(conn) -> int:
    enabled, cap = await load_clan_settings(conn)
    if not enabled:
        raise HTTPException(status_code=409, detail="Кланы выключены")
    return cap


async def active_membership(conn, user_id: int):
    return await conn.fetchrow(
        """/* clan:active */
        SELECT m.clan_id, m.role, m.joined_at, m.left_at,
               c.tag, c.name, c.owner_id, c.invite_code, c.disbanded_at, c.created_at
        FROM casino_clan_members m
        JOIN casino_clans c ON c.id = m.clan_id
        WHERE m.user_id = $1 AND m.left_at IS NULL AND c.disbanded_at IS NULL
        """,
        int(user_id),
    )


async def active_clan_tag(conn, user_id: int) -> str | None:
    row = await conn.fetchrow(
        """/* clan:live-tag */
        SELECT c.tag
        FROM casino_clan_members m
        JOIN casino_clans c ON c.id = m.clan_id
        WHERE m.user_id = $1 AND m.left_at IS NULL AND c.disbanded_at IS NULL
        """,
        int(user_id),
    )
    if not row:
        return None
    return str(row["tag"])


async def tagged_display_name(conn, user_id: int, display_name: str) -> str:
    return format_clan_display_name(display_name, await active_clan_tag(conn, user_id))


async def clan_brief_for_user(conn, user_id: int) -> dict[str, object] | None:
    row = await active_membership(conn, user_id)
    if not row:
        return None
    return {"tag": str(row["tag"]), "name": str(row["name"]), "role": str(row["role"])}


async def _last_leave(conn, user_id: int):
    return await conn.fetchrow(
        """/* clan:last-leave */
        SELECT left_at FROM casino_clan_members
        WHERE user_id = $1 AND left_at IS NOT NULL
        ORDER BY left_at DESC LIMIT 1
        """,
        int(user_id),
    )


async def _assert_join_cooldown(conn, user_id: int) -> None:
    row = await _last_leave(conn, user_id)
    left_at = _as_dt(row["left_at"]) if row else None
    if left_at is None:
        return
    elapsed = utcnow() - left_at
    if elapsed < JOIN_COOLDOWN:
        hours = int((JOIN_COOLDOWN - elapsed).total_seconds() // 3600) + 1
        raise HTTPException(status_code=409, detail=f"После выхода подождите {hours} ч до вступления в другую команду")


async def _live_count(conn, clan_id: int) -> int:
    row = await conn.fetchrow(
        "/* clan:count-live */ SELECT COUNT(*)::int AS n FROM casino_clan_members WHERE clan_id = $1 AND left_at IS NULL",
        int(clan_id),
    )
    return int(row["n"]) if row else 0


async def list_top(conn, *, limit: int = TOP_LIMIT) -> dict[str, object]:
    week_start = current_week_start()
    cap = max(1, min(int(limit), TOP_LIMIT))
    rows = await conn.fetch(
        f"""/* clan:top */
        {PLAYER_WAGER_SQL}
        SELECT c.id, c.tag, c.name, c.owner_id,
               COALESCE(live.member_count, 0)::int AS member_count,
               COALESCE(SUM(w.wager_rub), 0)::numeric AS wager_rub
        FROM casino_clans c
        LEFT JOIN casino_clan_members hist
          ON hist.clan_id = c.id
        LEFT JOIN player_wagers w
          ON w.user_id = hist.user_id
         AND w.settled_at >= hist.joined_at
         AND (hist.left_at IS NULL OR w.settled_at < hist.left_at)
        LEFT JOIN (
            SELECT clan_id, COUNT(*)::int AS member_count
            FROM casino_clan_members
            WHERE left_at IS NULL
            GROUP BY clan_id
        ) live ON live.clan_id = c.id
        WHERE c.disbanded_at IS NULL
        GROUP BY c.id, c.tag, c.name, c.owner_id, live.member_count
        ORDER BY wager_rub DESC, c.tag ASC
        LIMIT $3
        """,
        week_start,
        list(CASHBACK_GAME_TYPES),
        cap,
    )
    return {
        "week_start": week_start.isoformat(),
        "clans": [_top_row(row) for row in rows],
    }


def _top_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "tag": str(row["tag"]),
        "name": str(row["name"]),
        "owner_id": int(row["owner_id"]),
        "member_count": int(row["member_count"] or 0),
        "wager_rub": float(money(row["wager_rub"] or 0)),
    }


async def _member_wagers(conn, clan_id: int, week_start) -> dict[int, Decimal]:
    rows = await conn.fetch(
        f"""/* clan:member-wagers */
        {PLAYER_WAGER_SQL}
        SELECT hist.user_id, COALESCE(SUM(w.wager_rub), 0)::numeric AS wager_rub
        FROM casino_clan_members hist
        LEFT JOIN player_wagers w
          ON w.user_id = hist.user_id
         AND w.settled_at >= hist.joined_at
         AND (hist.left_at IS NULL OR w.settled_at < hist.left_at)
        WHERE hist.clan_id = $3
        GROUP BY hist.user_id
        """,
        week_start,
        list(CASHBACK_GAME_TYPES),
        int(clan_id),
    )
    return {int(row["user_id"]): money(row["wager_rub"] or 0) for row in rows}


async def _identities(conn, user_ids: Sequence[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await conn.fetch(
        """/* clan:identities */
        SELECT user_id, username, first_name FROM bot_users WHERE user_id = ANY($1::bigint[])
        """,
        list(user_ids),
    )
    names: dict[int, str] = {}
    for row in rows:
        uid = int(row["user_id"])
        names[uid] = str(row["username"] or row["first_name"] or uid)
    return names


async def _load_clan_by_tag(conn, tag: str):
    return await conn.fetchrow(
        "/* clan:get-tag */ SELECT id, tag, name, owner_id, invite_code, created_at, disbanded_at FROM casino_clans WHERE tag = $1",
        tag,
    )


async def clan_snapshot(
    conn,
    *,
    tag: str | None = None,
    clan_id: int | None = None,
    viewer_id: int | None = None,
    include_invite: bool = False,
) -> dict[str, object]:
    if tag:
        clan = await _load_clan_by_tag(conn, parse_tag(tag))
    elif clan_id is not None:
        clan = await conn.fetchrow(
            "/* clan:get-id */ SELECT id, tag, name, owner_id, invite_code, created_at, disbanded_at FROM casino_clans WHERE id = $1",
            int(clan_id),
        )
    else:
        raise HTTPException(status_code=400, detail="Нужен тег или id")
    if not clan or clan["disbanded_at"] is not None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    _, max_members = await load_clan_settings(conn)
    week_start = current_week_start()
    members = await conn.fetch(
        """/* clan:members */
        SELECT user_id, role, joined_at, left_at
        FROM casino_clan_members
        WHERE clan_id = $1 AND left_at IS NULL
        ORDER BY CASE WHEN role = 'owner' THEN 0 ELSE 1 END, joined_at
        """,
        int(clan["id"]),
    )
    wagers = await _member_wagers(conn, int(clan["id"]), week_start)
    ids = [int(row["user_id"]) for row in members]
    names = await _identities(conn, ids)
    live = []
    total = Decimal("0.00")
    my_role = None
    for row in members:
        uid = int(row["user_id"])
        amount = wagers.get(uid, Decimal("0.00"))
        total += amount
        role = str(row["role"])
        if viewer_id is not None and uid == int(viewer_id):
            my_role = role
        live.append(
            {
                "user_id": uid,
                "role": role,
                "joined_at": _iso(row["joined_at"]),
                "display_name": names.get(uid, str(uid)),
                "wager_rub": float(amount),
            }
        )
    owner = viewer_id is not None and int(viewer_id) == int(clan["owner_id"])
    payload: dict[str, object] = {
        "id": int(clan["id"]),
        "tag": str(clan["tag"]),
        "name": str(clan["name"]),
        "owner_id": int(clan["owner_id"]),
        "created_at": _iso(clan["created_at"]),
        "member_count": len(live),
        "max_members": max_members,
        "wager_rub": float(money(total)),
        "week_start": week_start.isoformat(),
        "members": live,
        "my_role": my_role,
        "is_owner": owner,
    }
    if include_invite and owner:
        payload["invite_code"] = str(clan["invite_code"])
    return payload


async def my_clan(conn, user_id: int) -> dict[str, object]:
    row = await active_membership(conn, user_id)
    if not row:
        enabled, _ = await load_clan_settings(conn)
        return {"clan": None, "enabled": enabled}
    snap = await clan_snapshot(conn, clan_id=int(row["clan_id"]), viewer_id=user_id, include_invite=True)
    enabled, _ = await load_clan_settings(conn)
    return {"clan": snap, "enabled": enabled}


async def create_clan(conn, *, user_id: int, tag: str, name: str) -> dict[str, object]:
    cap = await _require_enabled(conn)
    _ = cap
    tag = parse_tag(tag)
    name = parse_name(name)
    if await active_membership(conn, user_id):
        raise HTTPException(status_code=409, detail="Вы уже в команде")
    await _assert_join_cooldown(conn, user_id)
    existing = await _load_clan_by_tag(conn, tag)
    if existing:
        raise HTTPException(status_code=409, detail="Тег уже занят")
    code = new_invite_code()
    try:
        clan = await conn.fetchrow(
            """/* clan:insert-clan */
            INSERT INTO casino_clans (tag, name, owner_id, invite_code)
            VALUES ($1, $2, $3, $4)
            RETURNING id, tag, name, owner_id, invite_code, created_at, disbanded_at
            """,
            tag,
            name,
            int(user_id),
            code,
        )
        await conn.execute(
            """/* clan:insert-member */
            INSERT INTO casino_clan_members (clan_id, user_id, role, joined_at)
            VALUES ($1, $2, 'owner', $3)
            """,
            int(clan["id"]),
            int(user_id),
            utcnow(),
        )
    except Exception as exc:
        if _unique_violation(exc):
            raise HTTPException(status_code=409, detail="Тег или код уже занят") from exc
        raise
    return await clan_snapshot(conn, clan_id=int(clan["id"]), viewer_id=user_id, include_invite=True)


async def join_clan(conn, *, user_id: int, code: str) -> dict[str, object]:
    cap = await _require_enabled(conn)
    code = parse_invite_code(code)
    if await active_membership(conn, user_id):
        raise HTTPException(status_code=409, detail="Вы уже в команде")
    await _assert_join_cooldown(conn, user_id)
    clan = await conn.fetchrow(
        "/* clan:get-code */ SELECT id, tag, name, owner_id, invite_code, created_at, disbanded_at FROM casino_clans WHERE invite_code = $1",
        code,
    )
    if not clan or clan["disbanded_at"] is not None:
        raise HTTPException(status_code=404, detail="Код не найден")
    if await _live_count(conn, int(clan["id"])) >= cap:
        raise HTTPException(status_code=409, detail="Команда заполнена")
    try:
        await conn.execute(
            """/* clan:insert-member */
            INSERT INTO casino_clan_members (clan_id, user_id, role, joined_at)
            VALUES ($1, $2, 'member', $3)
            """,
            int(clan["id"]),
            int(user_id),
            utcnow(),
        )
    except Exception as exc:
        if _unique_violation(exc):
            raise HTTPException(status_code=409, detail="Вы уже в команде") from exc
        raise
    return await clan_snapshot(conn, clan_id=int(clan["id"]), viewer_id=user_id, include_invite=False)


async def leave_clan(conn, *, user_id: int) -> dict[str, object]:
    row = await active_membership(conn, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Вы не в команде")
    if str(row["role"]) == "owner":
        raise HTTPException(status_code=409, detail="Сначала передайте владение или распустите команду")
    await conn.execute(
        "/* clan:close-member */ UPDATE casino_clan_members SET left_at = $3 WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(user_id),
        utcnow(),
    )
    return {"ok": True, "left_tag": str(row["tag"])}


async def kick_member(conn, *, owner_id: int, target_id: int) -> dict[str, object]:
    if int(owner_id) == int(target_id):
        raise HTTPException(status_code=400, detail="Себя кикнуть нельзя — выйдите или распустите")
    row = await active_membership(conn, owner_id)
    if not row or str(row["role"]) != "owner":
        raise HTTPException(status_code=403, detail="Кик доступен владельцу")
    target = await conn.fetchrow(
        "/* clan:member-one */ SELECT user_id, role FROM casino_clan_members WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(target_id),
    )
    if not target:
        raise HTTPException(status_code=404, detail="Игрок не в этой команде")
    await conn.execute(
        "/* clan:close-member */ UPDATE casino_clan_members SET left_at = $3 WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(target_id),
        utcnow(),
    )
    return await clan_snapshot(conn, clan_id=int(row["clan_id"]), viewer_id=owner_id, include_invite=True)


async def rotate_invite(conn, *, owner_id: int) -> dict[str, object]:
    row = await active_membership(conn, owner_id)
    if not row or str(row["role"]) != "owner":
        raise HTTPException(status_code=403, detail="Код видит только владелец")
    code = new_invite_code()
    try:
        await conn.execute(
            "/* clan:set-code */ UPDATE casino_clans SET invite_code = $2 WHERE id = $1 AND disbanded_at IS NULL",
            int(row["clan_id"]),
            code,
        )
    except Exception as exc:
        if _unique_violation(exc):
            raise HTTPException(status_code=409, detail="Не удалось выдать код, повторите") from exc
        raise
    return await clan_snapshot(conn, clan_id=int(row["clan_id"]), viewer_id=owner_id, include_invite=True)


async def transfer_owner(conn, *, owner_id: int, target_id: int) -> dict[str, object]:
    if int(owner_id) == int(target_id):
        raise HTTPException(status_code=400, detail="Вы уже владелец")
    row = await active_membership(conn, owner_id)
    if not row or str(row["role"]) != "owner":
        raise HTTPException(status_code=403, detail="Передача доступна владельцу")
    target = await conn.fetchrow(
        "/* clan:member-one */ SELECT user_id, role FROM casino_clan_members WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(target_id),
    )
    if not target:
        raise HTTPException(status_code=404, detail="Игрок не в этой команде")
    now = utcnow()
    await conn.execute(
        "/* clan:set-owner */ UPDATE casino_clans SET owner_id = $2 WHERE id = $1",
        int(row["clan_id"]),
        int(target_id),
    )
    await conn.execute(
        "/* clan:set-role */ UPDATE casino_clan_members SET role = 'member' WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(owner_id),
    )
    await conn.execute(
        "/* clan:set-role */ UPDATE casino_clan_members SET role = 'owner' WHERE clan_id = $1 AND user_id = $2 AND left_at IS NULL",
        int(row["clan_id"]),
        int(target_id),
    )
    _ = now
    return await clan_snapshot(conn, clan_id=int(row["clan_id"]), viewer_id=owner_id, include_invite=False)


async def disband_clan(conn, *, actor_id: int, as_admin: bool = False, clan_id: int | None = None) -> dict[str, object]:
    if as_admin:
        if clan_id is None:
            raise HTTPException(status_code=400, detail="Нужен id команды")
        clan = await conn.fetchrow(
            "/* clan:get-id */ SELECT id, tag, name, owner_id, invite_code, created_at, disbanded_at FROM casino_clans WHERE id = $1",
            int(clan_id),
        )
        if not clan or clan["disbanded_at"] is not None:
            raise HTTPException(status_code=404, detail="Команда не найдена")
        target_id = int(clan["id"])
        tag = str(clan["tag"])
    else:
        row = await active_membership(conn, actor_id)
        if not row or str(row["role"]) != "owner":
            raise HTTPException(status_code=403, detail="Распустить может владелец")
        target_id = int(row["clan_id"])
        tag = str(row["tag"])
    now = utcnow()
    await conn.execute(
        "/* clan:disband-clan */ UPDATE casino_clans SET disbanded_at = $2 WHERE id = $1 AND disbanded_at IS NULL",
        target_id,
        now,
    )
    await conn.execute(
        "/* clan:close-all */ UPDATE casino_clan_members SET left_at = $2 WHERE clan_id = $1 AND left_at IS NULL",
        target_id,
        now,
    )
    return {"ok": True, "disbanded_tag": tag}

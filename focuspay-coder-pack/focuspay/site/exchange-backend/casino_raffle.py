"""FocusLucky live draw: sequential ticket-weighted places, auto RUB credit."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from casino_chat import actor_chip, public_actors
from casino_finance import money

logger = logging.getLogger("casino_raffle")

WATCH_PATH = "/casino/play/raffle"
HMAC_ALGORITHM = "hmac-sha256-place-mod-tickets"
MAX_PLACES = 20
MIN_PLACES = 1
SPIN_INTERVAL_MIN = 12
SPIN_INTERVAL_MAX = 120
PRE_SHOW_MIN = 5
PRE_SHOW_MAX = 300
NOTIFY_MINUTES_MIN = 1
NOTIFY_MINUTES_MAX = 120
DEFAULT_SPIN_INTERVAL = 30
DEFAULT_PRE_SHOW = 30
DEFAULT_NOTIFY_MINUTES = 15
SPIN_MS = 10500
MSK = timezone(timedelta(hours=3))
AUTOSTART_GRACE = timedelta(hours=2)
NOTIFY_MILESTONES: tuple[int, ...] = (360, 180, 60, 10)
NOTIFY_MILESTONE_LABELS: dict[int, str] = {
    360: "за 6 часов",
    180: "за 3 часа",
    60: "за 1 час",
    10: "за 10 минут",
}

DEFAULT_PRIZE_PLACES: list[dict[str, Any]] = [
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

_subscribers: set[asyncio.Queue] = set()
_closer_started = False


def make_seed() -> str:
    return secrets.token_hex(32)


def commit_seed(seed: str) -> str:
    return hashlib.sha256((seed or "").encode("utf-8")).hexdigest()


def hmac_index(seed: str, place: int, remaining: int) -> int:
    if remaining <= 0:
        raise ValueError("no tickets")
    digest = hmac.new(
        (seed or "").encode("utf-8"),
        f"place:{int(place)}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return int.from_bytes(digest[:8], "big") % int(remaining)


def chance_pct(tickets: int, remaining: int) -> float:
    if remaining <= 0 or tickets <= 0:
        return 0.0
    return round(min(100.0, tickets / remaining * 100), 1)


def format_chance_label(pct: float) -> str:
    if pct <= 0:
        return "0%"
    if pct == int(pct):
        return f"{int(pct)}%"
    return f"{pct:g}%"


def prize_pool_rub(places: Sequence[Mapping[str, Any]]) -> Decimal:
    total = Decimal("0")
    for row in places:
        total += money(row.get("prize_rub") or 0)
    return total


def normalize_prize_places(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        raise ValueError("Нужно хотя бы одно место")
    if not isinstance(raw, list):
        raise ValueError("prize_places must be a list")
    if len(raw) > MAX_PLACES:
        raise ValueError(f"Максимум {MAX_PLACES} мест")
    out: list[dict[str, Any]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise ValueError("Каждое место — объект с суммой")
        amount = money(row.get("prize_rub") or 0)
        if amount <= 0:
            raise ValueError("Сумма приза должна быть больше нуля")
        out.append(
            {
                "place": index + 1,
                "prize_rub": float(amount),
                "payout_method": "balance",
            }
        )
    if len(out) < MIN_PLACES:
        raise ValueError("Нужно хотя бы одно место")
    return out


def clamp_spin_interval(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Интервал спина — целое число секунд") from exc
    if n < SPIN_INTERVAL_MIN or n > SPIN_INTERVAL_MAX:
        raise ValueError(f"Интервал спина {SPIN_INTERVAL_MIN}–{SPIN_INTERVAL_MAX} сек")
    return n


def clamp_pre_show(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Пауза до 1-го места — целое число секунд") from exc
    if n < PRE_SHOW_MIN or n > PRE_SHOW_MAX:
        raise ValueError(f"Пауза до спина {PRE_SHOW_MIN}–{PRE_SHOW_MAX} сек")
    return n


def clamp_notify_minutes(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Предуведомление — целое число минут") from exc
    if n < NOTIFY_MINUTES_MIN or n > NOTIFY_MINUTES_MAX:
        raise ValueError(f"Предуведомление {NOTIFY_MINUTES_MIN}–{NOTIFY_MINUTES_MAX} мин")
    return n


def parse_draw_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Нужно дату и время розыгрыша")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Некорректные дата и время розыгрыша") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(timezone.utc)


def resolve_schedule(
    *,
    starts_at: Any | None = None,
    draw_at: Any | None = None,
    existing_starts: datetime | None = None,
    existing_draw: datetime | None = None,
) -> tuple[datetime, datetime, datetime]:
    """Return UTC starts_at, draw_at, ends_at. Naive ISO is MSK."""
    start = parse_draw_at(starts_at) if starts_at not in (None, "") else existing_starts
    draw = parse_draw_at(draw_at) if draw_at not in (None, "") else existing_draw
    if start is None:
        raise ValueError("Нужно начало набора")
    if draw is None:
        raise ValueError("Нужно дату и время розыгрыша")
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    else:
        start = start.astimezone(timezone.utc)
    if draw.tzinfo is None:
        draw = draw.replace(tzinfo=timezone.utc)
    else:
        draw = draw.astimezone(timezone.utc)
    if start >= draw:
        raise ValueError("Начало набора должно быть раньше розыгрыша")
    return start, draw, draw - timedelta(seconds=1)


def format_draw_msk(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(MSK)
    return f"{local.day:02d}.{local.month:02d} {local.hour:02d}:{local.minute:02d} МСК"


def parse_notify_milestones(raw: Any) -> set[int]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return set()
    if isinstance(raw, dict):
        out: set[int] = set()
        for key in raw:
            try:
                out.add(int(key))
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(raw, list):
        out = set()
        for item in raw:
            try:
                out.add(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return set()


def autostart_due(*, draw_at: datetime, now: datetime | None = None) -> bool:
    """Start a show only if draw_at is in the recent past, not months later."""
    if draw_at.tzinfo is None:
        draw_at = draw_at.replace(tzinfo=timezone.utc)
    current = now if now is not None else _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return draw_at <= current <= draw_at + AUTOSTART_GRACE


def due_notify_milestones(
    *,
    draw_at: datetime,
    now: datetime,
    sent: set[int] | None = None,
) -> list[int]:
    if draw_at.tzinfo is None:
        draw_at = draw_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    remaining = (draw_at - now).total_seconds()
    if remaining <= 0:
        return []
    minutes_left = remaining / 60.0
    bounds = list(NOTIFY_MILESTONES) + [0]
    already = sent or set()
    for index, offset in enumerate(NOTIFY_MILESTONES):
        lower = bounds[index + 1]
        if minutes_left > lower and minutes_left <= offset:
            if offset in already:
                return []
            return [offset]
    return []


def notify_schedule() -> list[dict[str, Any]]:
    return [
        {"minutes": minutes, "label": NOTIFY_MILESTONE_LABELS[minutes]}
        for minutes in NOTIFY_MILESTONES
    ]


def parse_prize_places(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        return [dict(row) for row in DEFAULT_PRIZE_PLACES]
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        try:
            place = int(row.get("place") or 0)
            amount = money(row.get("prize_rub") or 0)
        except (TypeError, ValueError):
            continue
        if place < 1:
            continue
        method = str(row.get("payout_method") or "balance").lower()
        if method != "balance":
            method = "balance"
        out.append({"place": place, "prize_rub": float(amount), "payout_method": method})
    out.sort(key=lambda item: int(item["place"]))
    return out or [dict(row) for row in DEFAULT_PRIZE_PLACES]


def verify_raffle_place(
    *,
    seed: str,
    commit: str,
    place: int,
    remaining_tickets: int,
    expected_index: int | None = None,
) -> dict[str, object]:
    computed = commit_seed(seed)
    commit_matches = computed.lower() == (commit or "").strip().lower()
    index = hmac_index(seed, place, remaining_tickets) if remaining_tickets > 0 else None
    index_matches = expected_index is None or (index is not None and index == int(expected_index))
    matches = bool(commit_matches and index_matches)
    return {
        "matches": matches,
        "commit_matches": commit_matches,
        "ticket_matches": index_matches,
        "computed_commit": computed,
        "winning_ticket": index,
        "total_tickets": remaining_tickets,
        "place": int(place),
        "algorithm": HMAC_ALGORITHM,
    }


def month_key_msk(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    at = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    local = at.astimezone(MSK)
    return f"{local.year:04d}-{local.month:02d}"


def normalize_kind(value: Any) -> str:
    kind = str(value or "monthly").strip().lower()
    if kind not in {"weekly", "monthly"}:
        raise ValueError("kind должен быть weekly или monthly")
    return kind


async def check_draw_conflict(
    conn, draw_at_utc: datetime, *, exclude_id: int | None = None
) -> dict[str, Any] | None:
    """Return conflicting campaign if any draw is within 24h. Naive = MSK."""
    target = draw_at_utc
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    rows = await conn.fetch(
        """
        SELECT id, title, kind, draw_at FROM raffle_campaigns
        WHERE draw_at IS NOT NULL AND status <> 'drawn'
        """
    )
    for row in rows:
        if exclude_id is not None and int(row["id"]) == int(exclude_id):
            continue
        other = row["draw_at"]
        if not isinstance(other, datetime):
            continue
        if other.tzinfo is None:
            other = other.replace(tzinfo=timezone.utc)
        if abs((other - target).total_seconds()) < 24 * 3600:
            d = dict(row)
            d["draw_at_msk"] = format_draw_msk(other)
            return d
    return None


def conflict_message(conflict: Mapping[str, Any]) -> str:
    return (
        f"На {conflict.get('draw_at_msk') or 'этот день'} уже запланирован "
        f"розыгрыш ({conflict.get('kind') or 'monthly'} #{conflict.get('id')}). "
        "Между розыгрышами должно быть минимум 24 часа."
    )


def payout_order_id(campaign_id: int, place: int) -> str:
    return f"flucky-{int(campaign_id)}-{int(place)}"[:64]


def watch_url() -> str:
    site = (os.getenv("PUBLIC_SITE_URL") or "https://focuspay.org").rstrip("/")
    if "gateway" in site or site.startswith("http://backend"):
        site = "https://focuspay.org"
    return f"{site}{WATCH_PATH}"


def watch_keyboard() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "Смотреть розыгрыш", "url": watch_url()}]]}


def telegram_notice_payload(chat_id: int, text: str, *, preview: bool = False) -> str:
    return json.dumps(
        {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": not preview,
            "reply_markup": watch_keyboard(),
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def publish(payload: Mapping[str, object]) -> None:
    for queue in list(_subscribers):
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


def ensure_closer() -> None:
    global _closer_started
    if _closer_started:
        return
    _closer_started = True
    asyncio.create_task(_closer_loop())


async def _closer_loop() -> None:
    from db import get_pool

    while True:
        await asyncio.sleep(1)
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await maybe_advance_show(conn)
        except Exception:
            logger.exception("raffle closer")


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _campaign_editable(status: str) -> bool:
    return str(status) in {"draft", "active", "closed"}


async def _lock_campaign(conn, campaign_id: int) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT * FROM raffle_campaigns WHERE id = $1 FOR UPDATE",
        int(campaign_id),
    )
    return dict(row) if row else None


async def _watch_campaign(conn) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT * FROM raffle_campaigns
        WHERE status = 'drawing'
        ORDER BY id DESC
        LIMIT 1
        """
    )
    if row:
        return dict(row)
    row = await conn.fetchrow(
        """
        SELECT * FROM raffle_campaigns
        WHERE status = 'active'
          AND starts_at <= now()
          AND ends_at >= now()
        ORDER BY starts_at DESC
        LIMIT 1
        """
    )
    if row:
        return dict(row)
    row = await conn.fetchrow(
        """
        SELECT * FROM raffle_campaigns
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None


async def _campaign_by_id(conn, campaign_id: int) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT * FROM raffle_campaigns WHERE id = $1",
        int(campaign_id),
    )
    return dict(row) if row else None


async def campaign_list(conn, viewer_id: int | None = None, limit: int = 24) -> list[dict[str, Any]]:
    exists = await conn.fetchval("SELECT to_regclass('public.raffle_campaigns')")
    if not exists:
        return []
    try:
        rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.month_label, c.kind, c.month_key,
                   c.status, c.draw_at, c.ends_at,
                   c.prize_places, c.prize_pool_rub,
                   (SELECT count(*) FROM raffle_winners w WHERE w.campaign_id = c.id) AS winner_count,
                   COALESCE((
                       SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                       WHERE t.campaign_id = c.id AND t.status = 'active'
                   ), 0) AS ticket_count,
                   COALESCE((
                       SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                       WHERE t.campaign_id = c.id AND t.status = 'active' AND t.user_id = $1
                   ), 0) AS my_tickets
            FROM raffle_campaigns c
            WHERE c.status <> 'draft' OR c.draw_at IS NOT NULL
            ORDER BY COALESCE(c.draw_at, c.ends_at) DESC NULLS LAST, c.id DESC
            LIMIT $2
            """,
            int(viewer_id or 0),
            int(limit),
        )
    except Exception:
        rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.month_label, c.status, c.draw_at, c.ends_at,
                   c.prize_places, c.prize_pool_rub,
                   (SELECT count(*) FROM raffle_winners w WHERE w.campaign_id = c.id) AS winner_count,
               COALESCE((
                   SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                   WHERE t.campaign_id = c.id AND t.status = 'active'
               ), 0) AS ticket_count,
               COALESCE((
                   SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                   WHERE t.campaign_id = c.id AND t.status = 'active' AND t.user_id = $1
               ), 0) AS my_tickets
        FROM raffle_campaigns c
        WHERE c.status <> 'draft' OR c.draw_at IS NOT NULL
        ORDER BY COALESCE(c.draw_at, c.ends_at) DESC NULLS LAST, c.id DESC
        LIMIT $2
        """,
        int(viewer_id or 0),
        int(limit),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        places = parse_prize_places(row.get("prize_places"))
        draw_iso = _iso(row.get("draw_at"))
        kind = str(row.get("kind") or "monthly") if "kind" in row else "monthly"
        mkey = row.get("month_key") if "month_key" in row else None
        out.append(
            {
                "campaign_id": int(row["id"]),
                "title": row.get("title") or "FocusLucky",
                "month_label": row.get("month_label"),
                "kind": kind,
                "month_key": mkey or (month_key_msk(row.get("draw_at")) if isinstance(row.get("draw_at"), datetime) else None),
                "status": str(row["status"]),
                "draw_at": _iso(row.get("draw_at")),
                "ends_at": _iso(row.get("ends_at")),
                "prize_pool_rub": float(row.get("prize_pool_rub") or prize_pool_rub(places)),
                "place_count": len(places),
                "winner_count": int(row["winner_count"] or 0),
                "ticket_count": int(row["ticket_count"] or 0),
                "my_tickets": int(row["my_tickets"] or 0),
            }
        )
    return out


async def winner_user_ids(conn, campaign_id: int) -> set[int]:
    rows = await conn.fetch(
        "SELECT user_id FROM raffle_winners WHERE campaign_id = $1",
        int(campaign_id),
    )
    return {int(row["user_id"]) for row in rows}


async def remaining_ticket_rows(
    conn, campaign_id: int, excluded: set[int]
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT user_id, ticket_no_from, ticket_no_to, ticket_count
        FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND status = 'active'
        ORDER BY ticket_no_from
        """,
        int(campaign_id),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        uid = int(row["user_id"])
        if uid in excluded:
            continue
        out.append(dict(row))
    return out


def remaining_ticket_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(row["ticket_count"]) for row in rows)


def find_ticket_owner(
    rows: Sequence[Mapping[str, Any]], ordinal: int
) -> tuple[int, int] | None:
    pos = 0
    for row in rows:
        count = int(row["ticket_count"])
        pos += count
        if ordinal <= pos:
            offset = ordinal - (pos - count) - 1
            winning_no = int(row["ticket_no_from"]) + offset
            return int(row["user_id"]), winning_no
    return None


async def _credit_place(conn, *, campaign_id: int, place: int, user_id: int, amount: Decimal, winner_id: int) -> None:
    order_id = payout_order_id(campaign_id, place)
    note = f"FocusLucky, {int(place)} место"
    await conn.execute(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'adjustment', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        """,
        int(user_id),
        amount,
        order_id,
        note,
    )
    await conn.execute(
        """
        UPDATE raffle_winners
        SET status = 'paid', paid_at = now(), payout_note = $2
        WHERE id = $1 AND status = 'pending'
        """,
        int(winner_id),
        note,
    )


def _raffle_kind_prefix(kind: Any) -> str:
    return "Недельный " if str(kind or "monthly") == "weekly" else ""


def started_html(*, minutes: int | None, live: bool, kind: Any = "monthly") -> str:
    url = html.escape(watch_url())
    prefix = _raffle_kind_prefix(kind)
    if live:
        return (
            f"🍀 <b>{prefix}FocusLucky начинается</b>\n\n"
            "Розыгрыш мест — смотрите в одном месте.\n"
            f'<a href="{url}">Открыть трансляцию</a>'
        )
    wait = max(1, int(minutes or 1))
    return (
        f"🍀 <b>{prefix}FocusLucky скоро начнётся</b>\n\n"
        f"Старт через <b>{wait} мин</b>. Места крутятся по очереди с 1-го.\n"
        f'<a href="{url}">Смотреть розыгрыш</a>'
    )


def soon_html(*, minutes: int, draw_at: datetime, kind: Any = "monthly") -> str:
    url = html.escape(watch_url())
    when = html.escape(format_draw_msk(draw_at))
    prefix = _raffle_kind_prefix(kind)
    if minutes >= 360:
        title = f"{prefix}FocusLucky сегодня"
        body = f"Розыгрыш в <b>{when}</b>. Места крутятся по очереди с 1-го."
    elif minutes >= 180:
        title = f"{prefix}FocusLucky через 3 часа"
        body = f"Старт в <b>{when}</b>."
    elif minutes >= 60:
        title = f"{prefix}FocusLucky через час"
        body = f"Старт в <b>{when}</b>."
    else:
        title = f"{prefix}FocusLucky скоро начнётся"
        body = f"Старт через <b>10 мин</b>, в <b>{when}</b>."
    return (
        f"🍀 <b>{title}</b>\n\n"
        f"{body}\n"
        f'<a href="{url}">Смотреть розыгрыш</a>'
    )


def place_win_html(*, place: int, prize_rub: Decimal | float, ticket_no: int) -> str:
    amount = html.escape(f"{money(prize_rub):f}".rstrip("0").rstrip("."))
    return (
        "🎉 <b>FocusLucky — вы выиграли!</b>\n\n"
        f"<b>{int(place)} место</b>\n"
        f"Билет: <b>#{int(ticket_no)}</b>\n"
        f"Приз: <b>{amount} ₽</b> уже на балансе."
    )


async def enqueue_participant_notices(
    conn,
    *,
    campaign_id: int,
    event_type: str,
    text: str,
    stamp: str | None = None,
) -> int:
    rows = await conn.fetch(
        """
        SELECT user_id
        FROM raffle_participants
        WHERE campaign_id = $1 AND tickets_total > 0
        """,
        int(campaign_id),
    )
    return await _enqueue_notice_rows(
        conn,
        campaign_id=int(campaign_id),
        event_type=event_type,
        text=text,
        user_ids=[int(row["user_id"]) for row in rows],
        stamp=stamp,
    )


async def enqueue_bot_user_notices(
    conn,
    *,
    campaign_id: int,
    event_type: str,
    text: str,
    stamp: str | None = None,
) -> int:
    exists = await conn.fetchval("SELECT to_regclass('public.bot_users')")
    if not exists:
        return await enqueue_participant_notices(
            conn,
            campaign_id=campaign_id,
            event_type=event_type,
            text=text,
            stamp=stamp,
        )
    rows = await conn.fetch("SELECT user_id FROM bot_users WHERE user_id > 0")
    return await _enqueue_notice_rows(
        conn,
        campaign_id=int(campaign_id),
        event_type=event_type,
        text=text,
        user_ids=[int(row["user_id"]) for row in rows],
        stamp=stamp,
    )


async def _enqueue_notice_rows(
    conn,
    *,
    campaign_id: int,
    event_type: str,
    text: str,
    user_ids: Sequence[int],
    stamp: str | None = None,
) -> int:
    inserted = 0
    key_type = f"{event_type}:{stamp}" if stamp else event_type
    for uid in user_ids:
        if uid <= 0:
            continue
        payload = telegram_notice_payload(uid, text)
        result = await conn.execute(
            """
            INSERT INTO raffle_notification_outbox
                (event_key, event_type, campaign_id, recipient_id, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (event_key) DO NOTHING
            """,
            f"raffle:{int(campaign_id)}:{key_type}:{uid}"[:160],
            event_type,
            int(campaign_id),
            uid,
            payload,
        )
        if str(result).endswith("1"):
            inserted += 1
    return inserted


async def enqueue_winner_notice(
    conn,
    *,
    campaign_id: int,
    user_id: int,
    place: int,
    prize_rub: Decimal | float,
    ticket_no: int,
) -> None:
    uid = int(user_id)
    if uid <= 0:
        return
    payload = telegram_notice_payload(
        uid,
        place_win_html(place=place, prize_rub=prize_rub, ticket_no=ticket_no),
    )
    await conn.execute(
        """
        INSERT INTO raffle_notification_outbox
            (event_key, event_type, campaign_id, recipient_id, payload)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        ON CONFLICT (event_key) DO NOTHING
        """,
        f"raffle:{int(campaign_id)}:place_win:{uid}:{int(place)}"[:160],
        "raffle_place_win",
        int(campaign_id),
        uid,
        payload,
    )


async def update_prize_places(campaign_id: int, raw_places: Any) -> dict[str, Any]:
    places = normalize_prize_places(raw_places)
    pool = prize_pool_rub(places)
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            camp = await _lock_campaign(conn, campaign_id)
            if not camp:
                raise ValueError("Кампания не найдена")
            if not _campaign_editable(str(camp["status"])):
                raise ValueError("Призы нельзя менять во время и после шоу")
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET prize_places = $2::jsonb, prize_pool_rub = $3, updated_at = now()
                WHERE id = $1
                """,
                int(campaign_id),
                json.dumps(places),
                pool,
            )
    return {"prize_places": places, "prize_pool_rub": float(pool)}


async def update_draw_at(campaign_id: int, raw: Any) -> dict[str, Any]:
    return await update_schedule(campaign_id, draw_at=raw)


async def update_schedule(
    campaign_id: int,
    *,
    starts_at: Any | None = None,
    draw_at: Any | None = None,
) -> dict[str, Any]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            camp = await _lock_campaign(conn, campaign_id)
            if not camp:
                raise ValueError("Кампания не найдена")
            status = str(camp["status"])
            if status in {"drawing", "drawn"}:
                raise ValueError("Время нельзя менять во время и после шоу")
            start, draw, ends_at = resolve_schedule(
                starts_at=starts_at,
                draw_at=draw_at,
                existing_starts=camp.get("starts_at"),
                existing_draw=camp.get("draw_at"),
            )
            conflict = await check_draw_conflict(conn, draw, exclude_id=int(campaign_id))
            if conflict:
                raise ValueError(conflict_message(conflict))
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET starts_at = $2,
                    draw_at = $3,
                    ends_at = $4,
                    notify_milestones = '{}'::jsonb,
                    notify_sent_at = NULL,
                    updated_at = now()
                WHERE id = $1
                """,
                int(campaign_id),
                start,
                draw,
                ends_at,
            )
            outbox = await conn.fetchval("SELECT to_regclass('public.raffle_notification_outbox')")
            if outbox:
                await conn.execute(
                    """
                    DELETE FROM raffle_notification_outbox
                    WHERE campaign_id = $1
                      AND event_type LIKE 'raffle_soon_%'
                      AND status IN ('pending', 'processing')
                    """,
                    int(campaign_id),
                )
    return {
        "starts_at": _iso(start),
        "draw_at": _iso(draw),
        "ends_at": _iso(ends_at),
    }


async def update_show_settings(
    campaign_id: int,
    *,
    spin_interval_seconds: Any | None = None,
    pre_show_seconds: Any | None = None,
) -> dict[str, Any]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            camp = await _lock_campaign(conn, campaign_id)
            if not camp:
                raise ValueError("Кампания не найдена")
            if str(camp["status"]) == "drawing":
                raise ValueError("Настройки шоу нельзя менять во время розыгрыша")
            interval = (
                clamp_spin_interval(spin_interval_seconds)
                if spin_interval_seconds is not None
                else int(camp.get("spin_interval_seconds") or DEFAULT_SPIN_INTERVAL)
            )
            pre = (
                clamp_pre_show(pre_show_seconds)
                if pre_show_seconds is not None
                else int(camp.get("pre_show_seconds") or DEFAULT_PRE_SHOW)
            )
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET spin_interval_seconds = $2,
                    pre_show_seconds = $3,
                    updated_at = now()
                WHERE id = $1
                """,
                int(campaign_id),
                interval,
                pre,
            )
    return {
        "spin_interval_seconds": interval,
        "pre_show_seconds": pre,
        "notify_schedule": notify_schedule(),
        "watch_path": WATCH_PATH,
    }


async def start_show(conn, campaign_id: int, *, notify: bool = True) -> dict[str, Any]:
    camp = await _lock_campaign(conn, campaign_id)
    if not camp:
        raise ValueError("Кампания не найдена")
    status = str(camp["status"])
    if status == "drawing":
        return camp
    if status == "drawn":
        raise ValueError("Розыгрыш уже проведён")
    if status not in {"active", "closed"}:
        raise ValueError(f"Нельзя запустить шоу при status={status}")
    existing = await conn.fetchval(
        "SELECT 1 FROM raffle_winners WHERE campaign_id = $1 LIMIT 1",
        int(campaign_id),
    )
    if existing:
        raise ValueError("Розыгрыш уже проведён")
    tickets = await conn.fetchval(
        """
        SELECT COALESCE(SUM(ticket_count), 0)::int
        FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND status = 'active'
        """,
        int(campaign_id),
    )
    if int(tickets or 0) <= 0:
        raise ValueError("Нет активных билетов")
    if status == "active":
        await conn.execute(
            """
            UPDATE raffle_campaigns
            SET status = 'closed', updated_at = now()
            WHERE id = $1 AND status = 'active'
            """,
            int(campaign_id),
        )
    seed = make_seed()
    commit = commit_seed(seed)
    now = _now()
    pre = int(camp.get("pre_show_seconds") or DEFAULT_PRE_SHOW)
    next_spin = now + timedelta(seconds=pre)
    await conn.execute(
        """
        UPDATE raffle_campaigns
        SET status = 'drawing',
            draw_seed = $2,
            draw_commit = $3,
            show_started_at = $4,
            spin_started_at = NULL,
            current_place = 1,
            next_spin_at = $5,
            notify_sent_at = COALESCE(notify_sent_at, $4),
            updated_at = now()
        WHERE id = $1
        """,
        int(campaign_id),
        seed,
        commit,
        now,
        next_spin,
    )
    if notify:
        await enqueue_bot_user_notices(
            conn,
            campaign_id=int(campaign_id),
            event_type="raffle_started",
            text=started_html(minutes=None, live=True, kind=camp.get("kind")),
        )
    publish({"type": "countdown", "campaign_id": int(campaign_id), "next_spin_at": _iso(next_spin)})
    camp = await conn.fetchrow("SELECT * FROM raffle_campaigns WHERE id = $1", int(campaign_id))
    return dict(camp) if camp else {"id": int(campaign_id), "status": "drawing"}


async def _finish_show(conn, campaign_id: int) -> None:
    await conn.execute(
        """
        UPDATE raffle_campaigns
        SET status = 'drawn',
            next_spin_at = NULL,
            updated_at = now()
        WHERE id = $1
        """,
        int(campaign_id),
    )
    publish({"type": "show_done", "campaign_id": int(campaign_id)})


async def _settle_next_place(conn, camp: Mapping[str, Any]) -> dict[str, Any] | None:
    campaign_id = int(camp["id"])
    places = parse_prize_places(camp.get("prize_places"))
    excluded = await winner_user_ids(conn, campaign_id)
    next_place = len(excluded) + 1
    if next_place > len(places):
        await _finish_show(conn, campaign_id)
        return None
    rows = await remaining_ticket_rows(conn, campaign_id, excluded)
    remaining = remaining_ticket_count(rows)
    if remaining <= 0:
        await _finish_show(conn, campaign_id)
        return None
    seed = str(camp.get("draw_seed") or "")
    if not seed:
        raise ValueError("Нет seed шоу")
    index = hmac_index(seed, next_place, remaining)
    found = find_ticket_owner(rows, index + 1)
    if not found:
        await _finish_show(conn, campaign_id)
        return None
    user_id, winning_no = found
    by_user: dict[int, int] = {}
    for row in rows:
        uid = int(row["user_id"])
        by_user[uid] = by_user.get(uid, 0) + int(row["ticket_count"])
    actor_ids = list(by_user.keys())
    actors = await public_actors(conn, actor_ids) if actor_ids else {}
    spin_players = []
    for uid, tickets in sorted(by_user.items(), key=lambda item: (-item[1], item[0])):
        actor = actor_chip(actors, uid)
        spin_players.append(
            {
                "user_id": uid,
                "display_name": actor["display_name"],
                "initial": actor["initial"],
                "avatar_url": actor.get("avatar_url"),
                "tickets": tickets,
                "chance_pct": chance_pct(tickets, remaining),
            }
        )
    prize = next(row for row in places if int(row["place"]) == next_place)
    amount = money(prize["prize_rub"])
    now = _now()
    interval = int(camp.get("spin_interval_seconds") or DEFAULT_SPIN_INTERVAL)
    scheduled = camp.get("next_spin_at")
    if isinstance(scheduled, datetime):
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        next_spin = scheduled + timedelta(seconds=interval)
    else:
        next_spin = now + timedelta(seconds=interval)
    winner_tickets = int(by_user.get(user_id) or 0)
    winner_chance = chance_pct(winner_tickets, remaining)
    winner_row = await conn.fetchrow(
        """
        INSERT INTO raffle_winners (
            campaign_id, place, user_id, winning_ticket_no,
            prize_rub, payout_method, status, eligible_tickets, hmac_index, winner_tickets
        )
        VALUES ($1, $2, $3, $4, $5, 'balance', 'pending', $6, $7, $8)
        ON CONFLICT (campaign_id, place) DO NOTHING
        RETURNING id
        """,
        campaign_id,
        next_place,
        user_id,
        winning_no,
        amount,
        remaining,
        index,
        winner_tickets,
    )
    if not winner_row:
        return None
    await _credit_place(
        conn,
        campaign_id=campaign_id,
        place=next_place,
        user_id=user_id,
        amount=amount,
        winner_id=int(winner_row["id"]),
    )
    await enqueue_winner_notice(
        conn,
        campaign_id=campaign_id,
        user_id=user_id,
        place=next_place,
        prize_rub=amount,
        ticket_no=winning_no,
    )
    more_places = next_place < len(places)
    more_players = remaining_ticket_count(
        await remaining_ticket_rows(conn, campaign_id, excluded | {user_id})
    ) > 0
    await conn.execute(
        """
        UPDATE raffle_campaigns
        SET current_place = $2,
            spin_started_at = $3,
            next_spin_at = $4,
            updated_at = now()
        WHERE id = $1
        """,
        campaign_id,
        next_place,
        now,
        next_spin if (more_places and more_players) else None,
    )
    if not (more_places and more_players):
        await _finish_show(conn, campaign_id)
    payload = {
        "type": "spin",
        "campaign_id": campaign_id,
        "place": next_place,
        "winner_id": user_id,
        "winning_ticket": winning_no,
        "hmac_index": index,
        "eligible_tickets": remaining,
        "winner_tickets": winner_tickets,
        "chance_pct": winner_chance,
        "prize_rub": float(amount),
        "players": spin_players,
        "next_spin_at": _iso(next_spin) if (more_places and more_players) else None,
    }
    publish(payload)
    publish({"type": "place_settled", **payload})
    return payload


async def maybe_advance_show(conn) -> None:
    exists = await conn.fetchval("SELECT to_regclass('public.raffle_campaigns')")
    if not exists:
        return
    await _maybe_pre_notify(conn)
    await _maybe_autostart(conn)
    row = await conn.fetchrow(
        """
        SELECT * FROM raffle_campaigns
        WHERE status = 'drawing'
        ORDER BY id DESC
        LIMIT 1
        FOR UPDATE
        """
    )
    if not row:
        return
    camp = dict(row)
    due = camp.get("next_spin_at")
    if due is None:
        await _finish_show(conn, int(camp["id"]))
        return
    if isinstance(due, datetime) and due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if isinstance(due, datetime) and due > _now():
        return
    await _settle_next_place(conn, camp)


async def _maybe_pre_notify(conn) -> None:
    rows = await conn.fetch(
        """
        SELECT * FROM raffle_campaigns
        WHERE status IN ('active', 'closed')
          AND draw_at IS NOT NULL
        FOR UPDATE SKIP LOCKED
        """
    )
    now = _now()
    for row in rows:
        camp = dict(row)
        draw_at = camp.get("draw_at")
        if not isinstance(draw_at, datetime):
            continue
        sent = parse_notify_milestones(camp.get("notify_milestones"))
        due = due_notify_milestones(draw_at=draw_at, now=now, sent=sent)
        if not due:
            continue
        raw_milestones = camp.get("notify_milestones")
        if isinstance(raw_milestones, str):
            try:
                raw_milestones = json.loads(raw_milestones)
            except json.JSONDecodeError:
                raw_milestones = {}
        milestones = dict(raw_milestones) if isinstance(raw_milestones, dict) else {}
        stamp = str(int(draw_at.timestamp()))
        for minutes in due:
            await enqueue_bot_user_notices(
                conn,
                campaign_id=int(camp["id"]),
                event_type=f"raffle_soon_{int(minutes)}",
                text=soon_html(minutes=int(minutes), draw_at=draw_at, kind=camp.get("kind")),
                stamp=stamp,
            )
            milestones[str(int(minutes))] = _iso(now)
        await conn.execute(
            """
            UPDATE raffle_campaigns
            SET notify_milestones = $2::jsonb,
                notify_sent_at = COALESCE(notify_sent_at, $3),
                updated_at = now()
            WHERE id = $1
            """,
            int(camp["id"]),
            json.dumps(milestones),
            now,
        )


async def _maybe_autostart(conn) -> None:
    rows = await conn.fetch(
        """
        SELECT id FROM raffle_campaigns
        WHERE status IN ('active', 'closed')
          AND draw_at IS NOT NULL
          AND draw_at <= now()
          AND draw_at > now() - interval '2 hours'
          AND NOT EXISTS (
              SELECT 1 FROM raffle_winners w WHERE w.campaign_id = raffle_campaigns.id
          )
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        """
    )
    for row in rows:
        try:
            await start_show(conn, int(row["id"]), notify=True)
        except ValueError:
            logger.info("raffle autostart skipped for %s", row["id"])


async def snapshot(
    conn,
    viewer_id: int | None = None,
    campaign_id: int | None = None,
) -> dict[str, Any]:
    exists = await conn.fetchval("SELECT to_regclass('public.raffle_campaigns')")
    if not exists:
        return empty_snapshot(viewer_id)
    if campaign_id:
        camp = await _campaign_by_id(conn, campaign_id)
    else:
        camp = await _watch_campaign(conn)
    if not camp:
        return empty_snapshot(viewer_id)
    campaign_id = int(camp["id"])
    status = str(camp["status"])
    archived = status == "drawn"
    places = parse_prize_places(camp.get("prize_places"))
    winner_rows = await conn.fetch(
        """
        SELECT w.place, w.user_id, w.winning_ticket_no, w.prize_rub, w.status,
               w.eligible_tickets, w.hmac_index, w.paid_at, w.winner_tickets, bu.username
        FROM raffle_winners w
        LEFT JOIN bot_users bu ON bu.user_id = w.user_id
        WHERE w.campaign_id = $1
        ORDER BY w.place
        """,
        campaign_id,
    )
    excluded: set[int] = set() if archived else {int(row["user_id"]) for row in winner_rows}
    ticket_rows = await remaining_ticket_rows(conn, campaign_id, excluded)
    remaining = remaining_ticket_count(ticket_rows)
    by_user: dict[int, int] = {}
    for row in ticket_rows:
        uid = int(row["user_id"])
        by_user[uid] = by_user.get(uid, 0) + int(row["ticket_count"])
    actor_ids = list(by_user.keys()) + [int(row["user_id"]) for row in winner_rows]
    if viewer_id:
        actor_ids.append(int(viewer_id))
    actors = await public_actors(conn, actor_ids) if actor_ids else {}
    players = []
    for uid, tickets in sorted(by_user.items(), key=lambda item: (-item[1], item[0])):
        actor = actor_chip(actors, uid)
        pct = chance_pct(tickets, remaining)
        players.append(
            {
                "user_id": uid,
                "display_name": actor["display_name"],
                "initial": actor["initial"],
                "avatar_url": actor.get("avatar_url"),
                "tickets": tickets,
                "chance_pct": pct,
            }
        )
    winners = []
    for row in winner_rows:
        uid = int(row["user_id"])
        actor = actor_chip(actors, uid)
        tickets = int(row["winner_tickets"] or 0)
        eligible = int(row["eligible_tickets"] or 0)
        winners.append(
            {
                "place": int(row["place"]),
                "user_id": uid,
                "display_name": actor["display_name"],
                "initial": actor["initial"],
                "avatar_url": actor.get("avatar_url"),
                "username": row.get("username"),
                "winning_ticket_no": int(row["winning_ticket_no"]),
                "prize_rub": float(row["prize_rub"]),
                "payout_status": str(row["status"]),
                "eligible_tickets": eligible,
                "tickets": tickets,
                "chance_pct": chance_pct(tickets, eligible),
                "hmac_index": row["hmac_index"],
            }
        )
    next_place = len(winners) + 1
    current_prize = next((row for row in places if int(row["place"]) == next_place), None)
    if archived:
        current_prize = None
        next_place = None
    spin_started = camp.get("spin_started_at")
    last_winner = winners[-1] if winners else None
    seed_public = status == "drawn"
    my_tickets = 0
    if viewer_id:
        my_tickets = by_user.get(int(viewer_id), 0)
    return {
        "campaign_id": campaign_id,
        "status": status,
        "title": camp.get("title") or "FocusLucky",
        "month_label": camp.get("month_label"),
        "kind": str(camp.get("kind") or "monthly"),
        "month_key": camp.get("month_key") or month_key_msk(camp.get("draw_at")),
        "commit_hash": camp.get("draw_commit"),
        "server_seed": camp.get("draw_seed") if seed_public else None,
        "algorithm": HMAC_ALGORITHM,
        "watch_path": WATCH_PATH,
        "prize_places": places,
        "prize_pool_rub": float(camp.get("prize_pool_rub") or prize_pool_rub(places)),
        "spin_interval_seconds": int(camp.get("spin_interval_seconds") or DEFAULT_SPIN_INTERVAL),
        "pre_show_seconds": int(camp.get("pre_show_seconds") or DEFAULT_PRE_SHOW),
        "notify_schedule": notify_schedule(),
        "show_started_at": _iso(camp.get("show_started_at")),
        "spin_started_at": _iso(spin_started),
        "next_spin_at": _iso(camp.get("next_spin_at")),
        "current_place": int(camp["current_place"]) if camp.get("current_place") else next_place,
        "next_place": next_place,
        "next_prize_rub": float(current_prize["prize_rub"]) if current_prize else None,
        "remaining_tickets": remaining,
        "player_count": len(players),
        "players": players,
        "winners": winners,
        "last_winner": last_winner,
        "my_user_id": int(viewer_id) if viewer_id else None,
        "my_tickets": my_tickets,
        "my_chance_pct": chance_pct(my_tickets, remaining),
        "draw_at": _iso(camp.get("draw_at")),
    }


def empty_snapshot(viewer_id: int | None) -> dict[str, Any]:
    return {
        "campaign_id": None,
        "status": "none",
        "title": "FocusLucky",
        "month_label": None,
        "kind": "monthly",
        "month_key": None,
        "commit_hash": None,
        "server_seed": None,
        "algorithm": HMAC_ALGORITHM,
        "watch_path": WATCH_PATH,
        "prize_places": [],
        "prize_pool_rub": 0,
        "spin_interval_seconds": DEFAULT_SPIN_INTERVAL,
        "pre_show_seconds": DEFAULT_PRE_SHOW,
        "notify_schedule": notify_schedule(),
        "show_started_at": None,
        "spin_started_at": None,
        "next_spin_at": None,
        "current_place": None,
        "next_place": None,
        "next_prize_rub": None,
        "remaining_tickets": 0,
        "player_count": 0,
        "players": [],
        "winners": [],
        "last_winner": None,
        "my_user_id": int(viewer_id) if viewer_id else None,
        "my_tickets": 0,
        "my_chance_pct": 0,
        "draw_at": None,
    }


async def start_show_for_admin(campaign_id: int) -> dict[str, Any]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            result = await start_show(conn, int(campaign_id), notify=True)
    ensure_closer()
    return result


async def snapshot_for_user(viewer_id: int | None, campaign_id: int | None = None) -> dict[str, Any]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        async with conn.transaction():
            ensure_closer()
            try:
                await maybe_advance_show(conn)
            except Exception:
                logger.exception("raffle snapshot advance")
            return await snapshot(conn, viewer_id, campaign_id)


async def campaigns_for_user(viewer_id: int | None) -> list[dict[str, Any]]:
    from db import get_pool

    db = await get_pool()
    async with db.acquire() as conn:
        return await campaign_list(conn, viewer_id)

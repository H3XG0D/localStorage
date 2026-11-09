"""Массовая рассылка покупателям в Telegram."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from broadcast_emoji import apply_premium_emoji, fit_premium_text
from config import settings
from db import get_pool
from text_sanitize import sanitize_telegram_html
from telegram_notify import (
    PHOTO_CAPTION_MAX,
    download_telegram_file,
    send_user_message_detailed,
    send_user_photo_bytes,
    send_user_sticker,
)
import broadcast_stickers as bst

logger = logging.getLogger("broadcast_service")

# Telegram stickers in broadcasts render full-size. Keep off so deploys do not
# auto-attach a pack sticker to every job (panel default used to be "auto").
BROADCAST_STICKERS_ENABLED = False

BROADCAST_DELAY = 0.05
BROADCAST_LIMIT = 100_000
SCHEDULER_TICK_SEC = 15
MAX_PENDING_JOBS = 50
MAX_ENABLED_SCHEDULES = 20
MIN_SCHEDULE_AHEAD = timedelta(minutes=1)
MAX_SCHEDULE_AHEAD = timedelta(days=30)
SCHEDULE_CATCHUP = timedelta(hours=2)
MSK = ZoneInfo("Europe/Moscow")
SCHEDULE_TZ = "Europe/Moscow"

BROADCAST_SEGMENTS: dict[str, str] = {
    "all": "Все в боте",
    "inactive7": "Не заходили 7+ дней",
    "inactive30": "Не заходили 30+ дней",
    "paid": "Есть оплаченные сделки",
    "no_deals": "В боте, без оплаченных сделок",
    "referrers": "Рефереры",
}

BROADCAST_DESTINATIONS: dict[str, str] = {
    "bot": "Бот",
    "news": "Новости",
}
NEWS_DESTINATION_LABEL = "Новости FocusPay"

SegmentKey = Literal["all", "inactive7", "inactive30", "paid", "no_deals", "referrers"]
RecurringAction = Literal["wait", "enqueue", "skip_missed"]

_running_jobs: set[int] = set()
_cancel_requested: set[int] = set()
_tick_lock: asyncio.Lock | None = None


def _get_tick_lock() -> asyncio.Lock:
    global _tick_lock
    if _tick_lock is None:
        _tick_lock = asyncio.Lock()
    return _tick_lock


def _segment_query(segment: str) -> str:
    seg = (segment or "all").strip().lower()
    if seg == "inactive7":
        return """
            SELECT user_id FROM bot_users
            WHERE last_seen_at < now() - interval '7 days'
            ORDER BY last_seen_at DESC
            LIMIT $1
        """
    if seg == "inactive30":
        return """
            SELECT user_id FROM bot_users
            WHERE last_seen_at < now() - interval '30 days'
            ORDER BY last_seen_at DESC
            LIMIT $1
        """
    if seg == "paid":
        return """
            SELECT DISTINCT bu.user_id
            FROM bot_users bu
            JOIN orders o ON o.user_id = bu.user_id AND o.status = 'PAID'
            ORDER BY bu.user_id
            LIMIT $1
        """
    if seg == "no_deals":
        return """
            SELECT bu.user_id
            FROM bot_users bu
            WHERE NOT EXISTS (
                SELECT 1 FROM orders o
                WHERE o.user_id = bu.user_id AND o.status = 'PAID'
            )
            ORDER BY bu.last_seen_at DESC NULLS LAST
            LIMIT $1
        """
    if seg == "referrers":
        return """
            SELECT DISTINCT referrer_user_id AS user_id
            FROM user_referral_attributions
            WHERE referrer_user_id IS NOT NULL AND referrer_user_id > 0
            ORDER BY referrer_user_id
            LIMIT $1
        """
    return """
        SELECT user_id FROM bot_users
        ORDER BY last_seen_at DESC NULLS LAST
        LIMIT $1
    """


def _validate_segment(segment: str) -> str:
    seg = (segment or "all").strip().lower() or "all"
    if seg not in BROADCAST_SEGMENTS:
        raise HTTPException(status_code=400, detail="Неизвестный сегмент")
    return seg


def normalize_segment(segment: str) -> str:
    return _validate_segment(segment)


def normalize_destination(destination: str | None) -> str:
    dest = (destination or "bot").strip().lower() or "bot"
    if dest not in BROADCAST_DESTINATIONS:
        raise HTTPException(status_code=400, detail="Неизвестное направление рассылки")
    return dest


async def resolve_news_chat_id() -> int:
    """Chat id канала новостей: env, иначе последняя активная привязка."""
    configured = int(getattr(settings, "telegram_news_chat_id", 0) or 0)
    if configured:
        return configured
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT chat_id
                FROM news_chat_allowlist
                WHERE active = TRUE
                ORDER BY confirmed_at DESC
                LIMIT 1
                """
            )
    except Exception:
        logger.warning("news chat allowlist lookup failed", exc_info=True)
        return 0
    if not row:
        return 0
    try:
        return int(row["chat_id"] or 0)
    except (TypeError, ValueError, KeyError):
        return 0


def _parse_sticker_ids(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    return []


def _parse_days_of_week(raw) -> list[int]:
    if raw is None:
        return [1, 2, 3, 4, 5, 6, 7]
    values: list[int] = []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = [p for p in text.replace("{", "").replace("}", "").split(",") if p.strip()]
    for item in raw:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= day <= 7 and day not in values:
            values.append(day)
    values.sort()
    return values


def validate_days_of_week(raw) -> list[int]:
    days = _parse_days_of_week(raw)
    if not days:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один день недели")
    return days


def parse_time_local(value: str | time | None) -> time:
    if isinstance(value, time):
        return time(value.hour, value.minute)
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Нужно время повтора")
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Некорректное время")
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(status_code=400, detail="Некорректное время")
    return time(hour, minute)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=MSK)
    return value.astimezone(timezone.utc)


def coerce_scheduled_at(
    value: datetime | str | None,
    *,
    now: datetime | None = None,
    required: bool = False,
) -> datetime | None:
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail="Нужно время публикации")
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            if required:
                raise HTTPException(status_code=400, detail="Нужно время публикации")
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректное время слота") from exc
    if not isinstance(value, datetime):
        raise HTTPException(status_code=400, detail="Некорректное время слота")
    value_utc = _as_utc(value)
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    if value_utc < now_utc + MIN_SCHEDULE_AHEAD:
        raise HTTPException(status_code=400, detail="Время слота — минимум через 1 минуту")
    if value_utc > now_utc + MAX_SCHEDULE_AHEAD:
        raise HTTPException(status_code=400, detail="Слот не дальше 30 дней")
    return value_utc


def job_is_due(
    status: str | None,
    scheduled_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if (status or "") != "pending":
        return False
    if scheduled_at is None:
        return True
    now_utc = _as_utc(now or datetime.now(timezone.utc))
    return _as_utc(scheduled_at) <= now_utc


def recurring_action(
    now: datetime,
    *,
    time_local: time,
    days_of_week: list[int],
    last_enqueued_date: date | None,
    catchup: timedelta = SCHEDULE_CATCHUP,
) -> RecurringAction:
    now_msk = now.astimezone(MSK) if now.tzinfo else now.replace(tzinfo=MSK)
    today = now_msk.date()
    if now_msk.isoweekday() not in days_of_week:
        return "wait"
    if last_enqueued_date == today:
        return "wait"
    slot = datetime.combine(today, time_local, tzinfo=MSK)
    if now_msk < slot:
        return "wait"
    if now_msk > slot + catchup:
        return "skip_missed"
    return "enqueue"


def _row_get(r, key: str, default=None):
    if r is None:
        return default
    getter = getattr(r, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            try:
                return getter(key)
            except Exception:
                return default
    try:
        return r[key]
    except Exception:
        return default


def _iso(value) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def _time_hhmm(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def _clean_broadcast_text(text: str, max_len: int = 4096) -> str:
    cleaned = sanitize_telegram_html(text, max_len=max_len)
    return fit_premium_text(apply_premium_emoji(cleaned), max_len)


async def _plan_stickers(
    *,
    apply_stickers: bool,
    sticker_mode: str,
    selected_sticker_ids: list[str] | None,
    text: str,
) -> tuple[list[str], str, str]:
    if not BROADCAST_STICKERS_ENABLED:
        return [], bst.STICKER_STATUS_NONE, "none"
    planned_ids: list[str] = []
    planned_status = bst.STICKER_STATUS_NONE
    mode = "none"
    if apply_stickers:
        try:
            catalog = await bst.list_live_catalog()
        except Exception:
            logger.warning("broadcast sticker catalog fetch failed", exc_info=True)
            catalog = []
        planned_ids, planned_status = bst.plan_sticker_ids(
            sticker_mode=sticker_mode,
            selected_sticker_ids=selected_sticker_ids,
            text=text,
            catalog=catalog,
        )
        mode = (sticker_mode or "none").strip().lower() or "none"
    return planned_ids, planned_status, mode


def _sticker_json(ids: list[str]) -> str | None:
    return json.dumps(ids, ensure_ascii=False) if ids else None


async def recover_stale_jobs() -> None:
    """Помечаем зависшие running-задачи после перезапуска API."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE broadcast_jobs
            SET status = 'failed',
                error_summary = 'Прервано перезапуском сервера',
                finished_at = now()
            WHERE status = 'running'
            """
        )


async def list_segments() -> list[dict]:
    out = []
    for key, label in BROADCAST_SEGMENTS.items():
        count = await count_segment(key)
        out.append({"id": key, "label": label, "count": count})
    return out


async def count_segment(segment: str) -> int:
    seg = _validate_segment(segment)
    pool = await get_pool()
    query = _segment_query(seg)
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, BROADCAST_LIMIT)
    return len(rows)


async def get_recipient_ids(segment: str) -> list[int]:
    seg = _validate_segment(segment)
    pool = await get_pool()
    query = _segment_query(seg)
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, BROADCAST_LIMIT)
    return [int(r["user_id"]) for r in rows]


async def has_running_job() -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT 1 FROM broadcast_jobs WHERE status = 'running' LIMIT 1"
        )
    return bool(val)


async def _pending_job_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT count(*) FROM broadcast_jobs WHERE status = 'pending'"
        )
    return int(val or 0)


async def _enabled_schedule_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT count(*) FROM broadcast_schedules WHERE enabled = true"
        )
    return int(val or 0)


def _job_row(r) -> dict:
    created = _row_get(r, "created_at")
    started = _row_get(r, "started_at")
    finished = _row_get(r, "finished_at")
    scheduled = _row_get(r, "scheduled_at")
    sticker_ids = _parse_sticker_ids(_row_get(r, "sticker_ids"))
    sticker_mode = (_row_get(r, "sticker_mode") or "none") or "none"
    sticker_status = _row_get(r, "sticker_status") or "none"
    schedule_id = _row_get(r, "schedule_id")
    destination = normalize_destination(_row_get(r, "destination") or "bot")
    return {
        "id": r["id"],
        "sender_role": r["sender_role"],
        "sender_id": r["sender_id"],
        "sender_label": _row_get(r, "sender_label"),
        "segment": r["segment"],
        "segment_label": BROADCAST_SEGMENTS.get(r["segment"], r["segment"]),
        "destination": destination,
        "destination_label": BROADCAST_DESTINATIONS[destination],
        "message_text": r["message_text"],
        "photo_file_id": _row_get(r, "photo_file_id"),
        "sticker_ids": sticker_ids,
        "sticker_mode": sticker_mode,
        "sticker_status": sticker_status,
        "stickers": bst.public_sticker_rows(sticker_ids, status=str(sticker_status)),
        "status": r["status"],
        "total_count": int(_row_get(r, "total_count") or 0),
        "sent_count": int(_row_get(r, "sent_count") or 0),
        "failed_count": int(_row_get(r, "failed_count") or 0),
        "error_summary": _row_get(r, "error_summary"),
        "schedule_id": int(schedule_id) if schedule_id is not None else None,
        "scheduled_at": _iso(scheduled),
        "created_at": _iso(created),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
    }


def _schedule_row(r) -> dict:
    sticker_ids = _parse_sticker_ids(_row_get(r, "sticker_ids"))
    sticker_mode = (_row_get(r, "sticker_mode") or "none") or "none"
    sticker_status = _row_get(r, "sticker_status") or "none"
    last = _row_get(r, "last_enqueued_date")
    destination = normalize_destination(_row_get(r, "destination") or "bot")
    return {
        "id": r["id"],
        "sender_role": r["sender_role"],
        "sender_id": r["sender_id"],
        "sender_label": _row_get(r, "sender_label"),
        "segment": r["segment"],
        "segment_label": BROADCAST_SEGMENTS.get(r["segment"], r["segment"]),
        "destination": destination,
        "destination_label": BROADCAST_DESTINATIONS[destination],
        "message_text": r["message_text"],
        "photo_file_id": _row_get(r, "photo_file_id"),
        "sticker_ids": sticker_ids,
        "sticker_mode": sticker_mode,
        "sticker_status": sticker_status,
        "stickers": bst.public_sticker_rows(sticker_ids, status=str(sticker_status)),
        "time_local": _time_hhmm(_row_get(r, "time_local")),
        "days_of_week": _parse_days_of_week(_row_get(r, "days_of_week")),
        "timezone": _row_get(r, "timezone") or SCHEDULE_TZ,
        "enabled": bool(_row_get(r, "enabled", True)),
        "last_enqueued_date": last.isoformat() if hasattr(last, "isoformat") else (str(last) if last else None),
        "created_at": _iso(_row_get(r, "created_at")),
        "updated_at": _iso(_row_get(r, "updated_at")),
    }


async def list_jobs(*, limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM broadcast_jobs
            ORDER BY
              CASE WHEN status IN ('draft', 'pending', 'running') THEN 0 ELSE 1 END,
              CASE WHEN status = 'draft' THEN 0 ELSE 1 END,
              CASE WHEN status IN ('pending', 'running')
                   THEN COALESCE(scheduled_at, created_at) END ASC NULLS LAST,
              created_at DESC,
              id DESC
            LIMIT $1
            """,
            min(limit, 100),
        )
    return [_job_row(r) for r in rows]


async def get_job(job_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM broadcast_jobs WHERE id = $1",
            job_id,
        )
    return _job_row(row) if row else None


async def create_job(
    *,
    sender_role: str,
    sender_id: int,
    sender_label: str | None,
    segment: str,
    message_text: str,
    photo_file_id: str | None = None,
    sticker_mode: str = "none",
    selected_sticker_ids: list[str] | None = None,
    apply_stickers: bool = False,
    scheduled_at: datetime | str | None = None,
    schedule_id: int | None = None,
    require_future_slot: bool = False,
    kick: bool = True,
    now: datetime | None = None,
    destination: str = "bot",
) -> dict:
    seg = _validate_segment(segment)
    dest = normalize_destination(destination)
    caption_max = PHOTO_CAPTION_MAX if (photo_file_id or "").strip() else 4096
    text = _clean_broadcast_text((message_text or "").strip(), max_len=caption_max)
    photo = (photo_file_id or "").strip() or None

    if not text and not photo:
        raise HTTPException(status_code=400, detail="Нужен текст или фото")

    if photo and len((message_text or "").strip()) > PHOTO_CAPTION_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Подпись к фото — не более {PHOTO_CAPTION_MAX} символов (лимит Telegram)",
        )

    slot = coerce_scheduled_at(scheduled_at, required=require_future_slot, now=now)
    planned_ids, planned_status, mode = await _plan_stickers(
        apply_stickers=apply_stickers,
        sticker_mode=sticker_mode,
        selected_sticker_ids=selected_sticker_ids,
        text=text or (message_text or ""),
    )

    if await _pending_job_count() >= MAX_PENDING_JOBS:
        raise HTTPException(
            status_code=409,
            detail=f"Слишком много задач в очереди (максимум {MAX_PENDING_JOBS}).",
        )

    sticker_ids_json = _sticker_json(planned_ids)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO broadcast_jobs (
                sender_role, sender_id, sender_label, segment,
                message_text, photo_file_id, status, total_count,
                sticker_ids, sticker_mode, sticker_status,
                scheduled_at, schedule_id, destination
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', 0, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            sender_role,
            sender_id,
            sender_label,
            seg,
            text,
            photo,
            sticker_ids_json,
            mode,
            planned_status,
            slot,
            schedule_id,
            dest,
        )

    job = _job_row(row)
    if kick:
        kick_worker()
    return job


async def patch_job(
    job_id: int,
    *,
    text: str | None = None,
    scheduled_at: Any = ...,
    segment: str | None = None,
    destination: str | None = None,
    sticker_mode: str | None = None,
    selected_sticker_ids: list[str] | None = None,
    sender_role: str = "operator",
    apply_stickers: bool = False,
) -> dict:
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Рассылка не найдена")
    if job["status"] not in ("draft", "pending") or job.get("started_at"):
        raise HTTPException(status_code=400, detail="Можно менять только черновик или ожидающую рассылку")

    fields: dict[str, Any] = {}
    next_text = job.get("message_text") or ""
    if text is not None:
        cleaned = _clean_broadcast_text(text.strip(), max_len=4096)
        if not cleaned and not (job.get("photo_file_id") or "").strip():
            raise HTTPException(status_code=400, detail="Нужен текст или фото")
        fields["message_text"] = cleaned
        next_text = cleaned
    if segment is not None:
        fields["segment"] = _validate_segment(segment)
    if destination is not None:
        fields["destination"] = normalize_destination(destination)
    if scheduled_at is not ...:
        fields["scheduled_at"] = coerce_scheduled_at(scheduled_at)
    resticker = sticker_mode is not None or selected_sticker_ids is not None
    if resticker or (apply_stickers and text is not None):
        planned_ids, planned_status, mode = await _plan_stickers(
            apply_stickers=apply_stickers,
            sticker_mode=sticker_mode if sticker_mode is not None else str(job.get("sticker_mode") or "none"),
            selected_sticker_ids=(
                selected_sticker_ids
                if selected_sticker_ids is not None
                else list(job.get("sticker_ids") or [])
            ),
            text=next_text,
        )
        fields["sticker_ids"] = _sticker_json(planned_ids)
        fields["sticker_mode"] = mode
        fields["sticker_status"] = planned_status

    if not fields:
        return job

    sets = []
    args: list[Any] = []
    for key, value in fields.items():
        args.append(value)
        sets.append(f"{key} = ${len(args)}")
    args.append(job_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE broadcast_jobs
            SET {", ".join(sets)}
            WHERE id = ${len(args)} AND status = ${len(args) + 1} AND started_at IS NULL
            RETURNING *
            """,
            *args,
            job["status"],
        )
    if not row:
        raise HTTPException(status_code=400, detail="Можно менять только черновик или ожидающую рассылку")
    if scheduled_at is not ... and job["status"] == "pending":
        kick_worker()
    return _job_row(row)


async def preview_stickers(
    *,
    sticker_mode: str = "none",
    selected_sticker_ids: list[str] | None = None,
    text: str = "",
    apply_stickers: bool = False,
) -> dict:
    if not BROADCAST_STICKERS_ENABLED:
        apply_stickers = False
    if not apply_stickers:
        return {
            "sticker_mode": "none",
            "sticker_status": bst.STICKER_STATUS_NONE,
            "stickers": [],
        }
    try:
        catalog = await bst.list_live_catalog()
    except Exception:
        logger.warning("broadcast sticker catalog fetch failed", exc_info=True)
        catalog = []
    ids, status = bst.plan_sticker_ids(
        sticker_mode=sticker_mode,
        selected_sticker_ids=selected_sticker_ids,
        text=text,
        catalog=catalog,
    )
    return {
        "sticker_mode": (sticker_mode or "none").strip().lower() or "none",
        "sticker_status": status,
        "stickers": bst.public_sticker_rows(ids, status=status),
    }


async def cancel_job(job_id: int) -> dict:
    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Рассылка не найдена")
    if job["status"] not in ("draft", "pending", "running"):
        raise HTTPException(status_code=400, detail="Рассылку нельзя отменить")

    _cancel_requested.add(job_id)

    if job["status"] in ("draft", "pending"):
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE broadcast_jobs
                SET status = 'cancelled', finished_at = now(),
                    error_summary = 'Отменено до старта'
                WHERE id = $1 AND status = $2
                RETURNING *
                """,
                job_id,
                job["status"],
            )
        if row:
            return _job_row(row)

    return await get_job(job_id) or job


async def launch_draft(job_id: int) -> dict:
    """Черновик из отчётов становится обычной рассылкой и уходит воркером."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE broadcast_jobs
            SET status = 'pending'
            WHERE id = $1 AND status = 'draft' AND started_at IS NULL
            RETURNING *
            """,
            job_id,
        )
    if not row:
        raise HTTPException(status_code=400, detail="Можно запустить только черновик")
    kick_worker()
    return _job_row(row)


async def list_schedules(*, limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM broadcast_schedules
            ORDER BY enabled DESC, time_local ASC, id DESC
            LIMIT $1
            """,
            min(limit, 100),
        )
    return [_schedule_row(r) for r in rows]


async def get_schedule(schedule_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM broadcast_schedules WHERE id = $1",
            schedule_id,
        )
    return _schedule_row(row) if row else None


async def create_schedule(
    *,
    sender_role: str,
    sender_id: int,
    sender_label: str | None,
    segment: str,
    message_text: str,
    photo_file_id: str | None = None,
    sticker_mode: str = "none",
    selected_sticker_ids: list[str] | None = None,
    apply_stickers: bool = False,
    time_local: str | time,
    days_of_week: list[int] | None = None,
    enabled: bool = True,
    destination: str = "bot",
) -> dict:
    seg = _validate_segment(segment)
    dest = normalize_destination(destination)
    caption_max = PHOTO_CAPTION_MAX if (photo_file_id or "").strip() else 4096
    text = _clean_broadcast_text((message_text or "").strip(), max_len=caption_max)
    photo = (photo_file_id or "").strip() or None
    if not text and not photo:
        raise HTTPException(status_code=400, detail="Нужен текст или фото")
    slot_time = parse_time_local(time_local)
    days = validate_days_of_week(days_of_week)
    planned_ids, planned_status, mode = await _plan_stickers(
        apply_stickers=apply_stickers,
        sticker_mode=sticker_mode,
        selected_sticker_ids=selected_sticker_ids,
        text=text or (message_text or ""),
    )
    if enabled and await _enabled_schedule_count() >= MAX_ENABLED_SCHEDULES:
        raise HTTPException(
            status_code=409,
            detail=f"Слишком много активных повторов (максимум {MAX_ENABLED_SCHEDULES}).",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO broadcast_schedules (
                sender_role, sender_id, sender_label, segment,
                message_text, photo_file_id,
                sticker_ids, sticker_mode, sticker_status,
                time_local, days_of_week, timezone, enabled, destination
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING *
            """,
            sender_role,
            sender_id,
            sender_label,
            seg,
            text,
            photo,
            _sticker_json(planned_ids),
            mode,
            planned_status,
            slot_time,
            days,
            SCHEDULE_TZ,
            enabled,
            dest,
        )
    kick_worker()
    return _schedule_row(row)


async def patch_schedule(
    schedule_id: int,
    *,
    sender_role: str,
    apply_stickers: bool,
    text: str | None = None,
    segment: str | None = None,
    time_local: str | time | None = None,
    days_of_week: list[int] | None = None,
    enabled: bool | None = None,
    sticker_mode: str | None = None,
    selected_sticker_ids: list[str] | None = None,
    photo_file_id: str | None = None,
    destination: str | None = None,
) -> dict:
    current = await get_schedule(schedule_id)
    if not current:
        raise HTTPException(status_code=404, detail="Повтор не найден")

    fields: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    next_text = current["message_text"]
    if text is not None:
        next_text = _clean_broadcast_text(text.strip(), max_len=4096)
        fields["message_text"] = next_text
    if segment is not None:
        fields["segment"] = _validate_segment(segment)
    if destination is not None:
        fields["destination"] = normalize_destination(destination)
    if time_local is not None:
        fields["time_local"] = parse_time_local(time_local)
    if days_of_week is not None:
        fields["days_of_week"] = validate_days_of_week(days_of_week)
    if photo_file_id is not None:
        fields["photo_file_id"] = (photo_file_id or "").strip() or None
    if enabled is not None:
        if enabled and not current["enabled"] and await _enabled_schedule_count() >= MAX_ENABLED_SCHEDULES:
            raise HTTPException(
                status_code=409,
                detail=f"Слишком много активных повторов (максимум {MAX_ENABLED_SCHEDULES}).",
            )
        fields["enabled"] = enabled

    resticker = sticker_mode is not None or selected_sticker_ids is not None or text is not None
    if resticker:
        planned_ids, planned_status, mode = await _plan_stickers(
            apply_stickers=apply_stickers,
            sticker_mode=sticker_mode if sticker_mode is not None else current["sticker_mode"],
            selected_sticker_ids=selected_sticker_ids if selected_sticker_ids is not None else current["sticker_ids"],
            text=next_text or "",
        )
        fields["sticker_ids"] = _sticker_json(planned_ids)
        fields["sticker_mode"] = mode
        fields["sticker_status"] = planned_status

    sets = []
    args: list[Any] = []
    for key, value in fields.items():
        args.append(value)
        sets.append(f"{key} = ${len(args)}")
    args.append(schedule_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE broadcast_schedules
            SET {", ".join(sets)}
            WHERE id = ${len(args)}
            RETURNING *
            """,
            *args,
        )
    kick_worker()
    return _schedule_row(row)


async def delete_schedule(schedule_id: int) -> dict:
    current = await get_schedule(schedule_id)
    if not current:
        raise HTTPException(status_code=404, detail="Повтор не найден")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM broadcast_schedules WHERE id = $1", schedule_id)
    return {"ok": True, "id": schedule_id}


async def _mark_schedule_enqueued(schedule_id: int, day: date) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE broadcast_schedules
            SET last_enqueued_date = $2, updated_at = now()
            WHERE id = $1
            """,
            schedule_id,
            day,
        )


async def enqueue_due_schedules(*, now: datetime | None = None) -> int:
    now_msk = (now or datetime.now(timezone.utc)).astimezone(MSK)
    today = now_msk.date()
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM broadcast_schedules WHERE enabled = true"
            )
    except Exception:
        logger.exception("broadcast schedule list failed")
        return 0

    created = 0
    for raw in rows:
        row = _schedule_row(raw)
        slot_time = parse_time_local(row["time_local"])
        last = row["last_enqueued_date"]
        last_date = date.fromisoformat(last) if last else None
        action = recurring_action(
            now_msk,
            time_local=slot_time,
            days_of_week=row["days_of_week"],
            last_enqueued_date=last_date,
        )
        if action == "wait":
            continue
        if action == "skip_missed":
            await _mark_schedule_enqueued(int(row["id"]), today)
            continue
        try:
            await create_job(
                sender_role=str(row["sender_role"]),
                sender_id=int(row["sender_id"]),
                sender_label=row.get("sender_label"),
                segment=str(row["segment"]),
                destination=str(row.get("destination") or "bot"),
                message_text=str(row["message_text"] or ""),
                photo_file_id=row.get("photo_file_id"),
                sticker_mode=str(row.get("sticker_mode") or "none"),
                selected_sticker_ids=list(row.get("sticker_ids") or []),
                apply_stickers=False,
                schedule_id=int(row["id"]),
                kick=False,
            )
            await _mark_schedule_enqueued(int(row["id"]), today)
            created += 1
        except HTTPException as exc:
            logger.warning("broadcast schedule %s enqueue skipped: %s", row["id"], exc.detail)
        except Exception:
            logger.exception("broadcast schedule %s enqueue failed", row["id"])
    return created


async def claim_next_job() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH next_job AS (
                SELECT id
                FROM broadcast_jobs
                WHERE status = 'pending'
                  AND (scheduled_at IS NULL OR scheduled_at <= now())
                  AND NOT EXISTS (
                      SELECT 1 FROM broadcast_jobs r WHERE r.status = 'running'
                  )
                ORDER BY scheduled_at NULLS FIRST, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE broadcast_jobs j
            SET status = 'running', started_at = now()
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.*
            """
        )
    return _job_row(row) if row else None


async def start_next_if_idle() -> None:
    if _running_jobs:
        return
    try:
        claimed = await claim_next_job()
    except Exception:
        logger.exception("broadcast claim failed")
        return
    if not claimed:
        return
    asyncio.create_task(_run_claimed(int(claimed["id"])))


async def _run_claimed(job_id: int) -> None:
    try:
        await run_job(job_id)
    finally:
        try:
            await start_next_if_idle()
        except Exception:
            logger.exception("broadcast follow-up start failed")


def kick_worker() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(scheduler_tick())


async def scheduler_tick() -> None:
    lock = _get_tick_lock()
    async with lock:
        try:
            await enqueue_due_schedules()
        except Exception:
            logger.exception("broadcast schedule tick failed")
        try:
            await start_next_if_idle()
        except Exception:
            logger.exception("broadcast start tick failed")


async def scheduler_loop() -> None:
    await asyncio.sleep(2)
    while True:
        try:
            await scheduler_tick()
        except Exception:
            logger.exception("broadcast scheduler loop failed")
        await asyncio.sleep(SCHEDULER_TICK_SEC)


async def _update_progress(
    job_id: int,
    *,
    sent: int,
    failed: int,
    status: str | None = None,
    error_summary: str | None = None,
    finished: bool = False,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if finished:
            await conn.execute(
                """
                UPDATE broadcast_jobs
                SET sent_count = $2, failed_count = $3,
                    status = COALESCE($4, status),
                    error_summary = COALESCE($5, error_summary),
                    finished_at = now()
                WHERE id = $1
                """,
                job_id,
                sent,
                failed,
                status,
                error_summary,
            )
        else:
            await conn.execute(
                """
                UPDATE broadcast_jobs
                SET sent_count = $2, failed_count = $3
                WHERE id = $1
                """,
                job_id,
                sent,
                failed,
            )


async def run_job(job_id: int, user_ids: list[int] | None = None) -> None:
    if job_id in _running_jobs:
        return
    _running_jobs.add(job_id)

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM broadcast_jobs WHERE id = $1",
                job_id,
            )
        if not row:
            return
        if row["status"] == "cancelled":
            return

        if normalize_destination(_row_get(row, "destination") or "bot") == "news":
            await _run_news_post(job_id, row)
            return

        if user_ids is None:
            try:
                user_ids = await get_recipient_ids(row["segment"])
            except HTTPException:
                user_ids = []

        if not user_ids:
            await _update_progress(
                job_id,
                sent=0,
                failed=0,
                status="failed",
                error_summary="В сегменте нет получателей",
                finished=True,
            )
            return

        # Sanitize again at the send boundary.  This also repairs legacy jobs
        # that were stored with unsupported tags such as <br>.
        text = _clean_broadcast_text(row["message_text"] or "")
        photo_file_id = _row_get(row, "photo_file_id")
        sticker_slugs = (
            _parse_sticker_ids(_row_get(row, "sticker_ids")) if BROADCAST_STICKERS_ENABLED else []
        )
        sticker_file_ids: list[str] = []
        if sticker_slugs:
            sticker_file_ids, resolve_status = await bst.resolve_sticker_file_ids(sticker_slugs)
            if resolve_status == bst.STICKER_STATUS_SKIPPED_EMPTY:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE broadcast_jobs
                        SET sticker_status = $2
                        WHERE id = $1
                        """,
                        job_id,
                        bst.STICKER_STATUS_SKIPPED_EMPTY,
                    )

        photo_payload: tuple[bytes, str, str] | None = None
        if photo_file_id:
            downloaded = await download_telegram_file(photo_file_id)
            if not downloaded:
                await _update_progress(
                    job_id,
                    sent=0,
                    failed=0,
                    status="failed",
                    error_summary="Не удалось получить фото из Telegram. Загрузите картинку заново.",
                    finished=True,
                )
                return
            photo_bytes, photo_mime = downloaded
            ext = "jpg"
            if "png" in photo_mime:
                ext = "png"
            elif "webp" in photo_mime:
                ext = "webp"
            elif "gif" in photo_mime:
                ext = "gif"
            photo_payload = (photo_bytes, photo_mime, f"broadcast.{ext}")

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE broadcast_jobs
                SET status = 'running',
                    started_at = COALESCE(started_at, now()),
                    total_count = $2
                WHERE id = $1 AND status IN ('pending', 'running')
                """,
                job_id,
                len(user_ids),
            )

        sent = 0
        failed = 0
        first_error: str | None = None

        for i, uid in enumerate(user_ids):
            if job_id in _cancel_requested:
                await _update_progress(
                    job_id,
                    sent=sent,
                    failed=failed,
                    status="cancelled",
                    error_summary="Отменено оператором",
                    finished=True,
                )
                return

            ok = False
            err_msg: str | None = None
            try:
                for fid in sticker_file_ids:
                    await send_user_sticker(uid, fid)
                if photo_payload:
                    photo_bytes, photo_mime, photo_name = photo_payload
                    ok, err_msg = await send_user_photo_bytes(
                        uid,
                        photo_bytes,
                        text,
                        filename=photo_name,
                        content_type=photo_mime,
                    )
                elif text:
                    ok, err_msg = await send_user_message_detailed(uid, text)
            except Exception as e:
                logger.warning("broadcast send uid=%s job=%s: %s", uid, job_id, e)
                err_msg = str(e)

            if ok:
                sent += 1
            else:
                failed += 1
                if err_msg and not first_error:
                    first_error = err_msg

            if (i + 1) % 25 == 0:
                await _update_progress(job_id, sent=sent, failed=failed)

            await asyncio.sleep(BROADCAST_DELAY)

        summary = None
        if failed and first_error:
            summary = f"Пример ошибки: {first_error[:400]}"

        await _update_progress(
            job_id,
            sent=sent,
            failed=failed,
            status="done",
            error_summary=summary,
            finished=True,
        )
    except Exception as e:
        logger.exception("broadcast job %s failed", job_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE broadcast_jobs
                SET status = 'failed', error_summary = $2, finished_at = now()
                WHERE id = $1
                """,
                job_id,
                str(e)[:500],
            )
    finally:
        _running_jobs.discard(job_id)
        _cancel_requested.discard(job_id)


async def _run_news_post(job_id: int, row) -> None:
    """Один пост в канал новостей. Сегмент бота не читается."""
    chat_id = await resolve_news_chat_id()
    if not chat_id:
        await _update_progress(
            job_id,
            sent=0,
            failed=0,
            status="failed",
            error_summary="Группа новостей не привязана",
            finished=True,
        )
        return

    text = _clean_broadcast_text(row["message_text"] or "")
    photo_file_id = _row_get(row, "photo_file_id")
    sticker_slugs = (
        _parse_sticker_ids(_row_get(row, "sticker_ids")) if BROADCAST_STICKERS_ENABLED else []
    )
    sticker_file_ids: list[str] = []
    if sticker_slugs:
        sticker_file_ids, _resolve_status = await bst.resolve_sticker_file_ids(sticker_slugs)

    photo_payload: tuple[bytes, str, str] | None = None
    if photo_file_id:
        downloaded = await download_telegram_file(photo_file_id)
        if not downloaded:
            await _update_progress(
                job_id,
                sent=0,
                failed=1,
                status="failed",
                error_summary="Не удалось получить фото из Telegram. Загрузите картинку заново.",
                finished=True,
            )
            return
        photo_bytes, photo_mime = downloaded
        ext = "jpg"
        if "png" in photo_mime:
            ext = "png"
        elif "webp" in photo_mime:
            ext = "webp"
        elif "gif" in photo_mime:
            ext = "gif"
        photo_payload = (photo_bytes, photo_mime, f"broadcast.{ext}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE broadcast_jobs
            SET status = 'running',
                started_at = COALESCE(started_at, now()),
                total_count = 1
            WHERE id = $1 AND status IN ('pending', 'running')
            """,
            job_id,
        )

    if job_id in _cancel_requested:
        await _update_progress(
            job_id,
            sent=0,
            failed=0,
            status="cancelled",
            error_summary="Отменено оператором",
            finished=True,
        )
        return

    ok = False
    err_msg: str | None = None
    try:
        for fid in sticker_file_ids:
            await send_user_sticker(chat_id, fid)
        if photo_payload:
            photo_bytes, photo_mime, photo_name = photo_payload
            ok, err_msg = await send_user_photo_bytes(
                chat_id,
                photo_bytes,
                text,
                filename=photo_name,
                content_type=photo_mime,
            )
        elif text:
            ok, err_msg = await send_user_message_detailed(chat_id, text)
        else:
            err_msg = "Нужен текст или фото"
    except Exception as e:
        logger.warning("news broadcast job=%s failed: %s", job_id, type(e).__name__)
        err_msg = str(e)

    await _update_progress(
        job_id,
        sent=1 if ok else 0,
        failed=0 if ok else 1,
        status="done" if ok else "failed",
        error_summary=None if ok else (err_msg or "Не удалось отправить в новости")[:400],
        finished=True,
    )

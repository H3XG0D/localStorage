"""FocusLucky raffle: DB access, UI data, draw, payouts."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from services.db import get_pool
from services.raffle_constants import (
    DEFAULT_PRIZE_PLACES,
    KIND_REFERRAL,
    format_chance_pct,
    format_place_label,
    format_prize_rub,
    format_prizes_block,
    format_ticket_numbers,
    format_winner_line,
    resolve_info_text,
    win_chance_pct,
)

logger = logging.getLogger("raffle_db")

MSK = timezone(timedelta(hours=3))


def _parse_prize_places(raw: Any) -> list[dict]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        return list(DEFAULT_PRIZE_PLACES)
    return list(raw)


async def get_active_campaigns(conn=None) -> list[dict]:
    """All campaigns open for accrual (weekly + monthly share one ticket pool)."""
    query = """
        SELECT *
        FROM raffle_campaigns
        WHERE status = 'active'
          AND starts_at <= now()
          AND ends_at >= now()
        ORDER BY id
    """

    async def _run(c):
        rows = await c.fetch(query)
        return [dict(r) for r in rows]

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


async def get_active_campaign(conn=None) -> dict | None:
    query = """
        SELECT *
        FROM raffle_campaigns
        WHERE status = 'active'
          AND starts_at <= now()
          AND ends_at >= now()
        ORDER BY starts_at DESC
        LIMIT 1
    """

    async def _run(c):
        row = await c.fetchrow(query)
        return dict(row) if row else None

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


async def get_campaign_by_id(campaign_id: int, conn=None) -> dict | None:
    async def _run(c):
        row = await c.fetchrow(
            "SELECT * FROM raffle_campaigns WHERE id = $1",
            campaign_id,
        )
        return dict(row) if row else None

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


def raffle_kind_title(kind: str | None) -> str:
    return "Недельный" if str(kind or "monthly") == "weekly" else "Месячный"


async def get_campaign_for_user(user_id: int, kind: str | None = None) -> dict | None:
    """Live/active campaign of given kind (default monthly), else latest drawn."""
    pool = await get_pool()
    kind_filter = ""
    params: list = []
    if kind in ("weekly", "monthly"):
        kind_filter = "AND kind = $1"
        params.append(kind)
    async with pool.acquire() as conn:
        drawing = await conn.fetchrow(
            f"""
            SELECT * FROM raffle_campaigns
            WHERE status = 'drawing' {kind_filter}
            ORDER BY id DESC
            LIMIT 1
            """,
            *params,
        )
        if drawing:
            return dict(drawing)
        if kind in ("weekly", "monthly"):
            active = await conn.fetchrow(
                """
                SELECT * FROM raffle_campaigns
                WHERE status = 'active'
                  AND starts_at <= now()
                  AND ends_at >= now()
                  AND kind = $1
                ORDER BY starts_at DESC
                LIMIT 1
                """,
                kind,
            )
        else:
            active = await get_active_campaign(conn)
        if active:
            return dict(active)
        row = await conn.fetchrow(
            f"""
            SELECT c.*
            FROM raffle_campaigns c
            WHERE c.status = 'drawn' {kind_filter.replace('kind', 'c.kind')}
            ORDER BY draw_at DESC NULLS LAST, ends_at DESC
            LIMIT 1
            """,
            *params,
        )
        return dict(row) if row else None


async def pool_active_ticket_count(campaign_id: int, conn) -> int:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(ticket_count), 0)::int
        FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND status = 'active'
        """,
        campaign_id,
    )
    return int(val or 0)


async def get_participant(campaign_id: int, user_id: int, conn) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT * FROM raffle_participants
        WHERE campaign_id = $1 AND user_id = $2
        """,
        campaign_id,
        user_id,
    )
    return dict(row) if row else None


async def get_user_active_ranges(
    campaign_id: int, user_id: int, conn
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT ticket_no_from, ticket_no_to, ticket_count
        FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND user_id = $2 AND status = 'active'
        ORDER BY ticket_no_from
        """,
        campaign_id,
        user_id,
    )
    return [dict(r) for r in rows]


async def get_user_snapshot(campaign_id: int, user_id: int, conn) -> dict:
    participant = await get_participant(campaign_id, user_id, conn)
    pool_total = await pool_active_ticket_count(campaign_id, conn)
    ranges = await get_user_active_ranges(campaign_id, user_id, conn)
    tickets = int(participant["tickets_total"]) if participant else 0
    pct = win_chance_pct(tickets, pool_total)
    return {
        "tickets_total": tickets,
        "win_chance_pct": pct,
        "win_chance_label": format_chance_pct(pct),
        "ticket_numbers": format_ticket_numbers(ranges),
        "ranges": ranges,
        "pool_total": pool_total,
    }


async def get_winners(campaign_id: int, conn=None) -> list[dict]:
    async def _run(c):
        rows = await c.fetch(
            """
            SELECT place, user_id, winning_ticket_no, prize_rub,
                   payout_method, status
            FROM raffle_winners
            WHERE campaign_id = $1
            ORDER BY place
            """,
            campaign_id,
        )
        return [dict(r) for r in rows]

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


def _days_until(end_at) -> int:
    """Календарные дни до даты (по МСК), для обратной совместимости."""
    return _days_until_draw(end_at)


def _days_until_draw(draw_at) -> int:
    if not draw_at:
        return 0
    now = datetime.now(MSK)
    if draw_at.tzinfo is None:
        target = draw_at.replace(tzinfo=MSK)
    else:
        target = draw_at.astimezone(MSK)
    return max(0, (target.date() - now.date()).days)


def _ru_days_word(n: int) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return "дней"
    rem = n % 10
    if rem == 1:
        return "день"
    if 2 <= rem <= 4:
        return "дня"
    return "дней"


def format_draw_countdown_line(draw_at) -> str | None:
    if not draw_at:
        return None
    days = _days_until_draw(draw_at)
    date_part = _format_draw_date(draw_at)
    if days == 0:
        return f"Розыгрыш <b>{date_part}</b> — <b>сегодня</b>"
    if days == 1:
        return f"Розыгрыш <b>{date_part}</b> — <b>завтра</b>"
    word = _ru_days_word(days)
    return f"Розыгрыш <b>{date_part}</b> — через <b>{days}</b> {word}"


def _format_draw_date(draw_at) -> str:
    if not draw_at:
        return "—"
    if draw_at.tzinfo is None:
        draw_at = draw_at.replace(tzinfo=MSK)
    else:
        draw_at = draw_at.astimezone(MSK)
    months_ru = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    return f"{draw_at.day} {months_ru[draw_at.month - 1]}, {draw_at.hour:02d}:{draw_at.minute:02d} МСК"


async def build_focus_lucky_message(user_id: int, kind: str | None = None) -> str | None:
    kind = kind if kind in ("weekly", "monthly") else "monthly"
    campaign = await get_campaign_for_user(user_id, kind)
    if not campaign:
        return None

    pool = await get_pool()
    async with pool.acquire() as conn:
        snap = await get_user_snapshot(campaign["id"], user_id, conn)
        winners = await get_winners(campaign["id"], conn) if campaign["status"] in {"drawn", "drawing"} else []

    month = campaign.get("month_label") or campaign.get("slug", "")
    month = f"{raffle_kind_title(campaign.get('kind'))} · {month}"
    prize_places = _parse_prize_places(campaign.get("prize_places"))

    from services.config_rates import PUBLIC_SITE_URL
    site = (PUBLIC_SITE_URL or "https://focuspay.org").rstrip("/")
    if "gateway" in site or site.startswith("http://backend"):
        site = "https://focuspay.org"
    watch = f"{site}/casino/play/raffle"

    if campaign["status"] == "drawing":
        lines = [
            f"🍀 <b>FocusLucky — {month}</b>",
            "",
            "Сейчас идёт живой розыгрыш. Места крутятся по очереди с 1-го.",
            f'<a href="{watch}">Смотреть трансляцию</a>',
            "",
            f"🎟 Ваши билеты: {snap['ticket_numbers']}",
            f"Шанс текущего места: {snap.get('win_chance_label') or '0%'}",
        ]
        if winners:
            lines.append("")
            lines.append("Уже занято:")
            for w in winners:
                lines.append(
                    format_winner_line(
                        int(w["place"]),
                        int(w["winning_ticket_no"]),
                        w["prize_rub"],
                        str(w["payout_method"]),
                    )
                )
        return "\n".join(lines)

    if campaign["status"] == "drawn" and winners:
        from services.ux_copy import RULE
        from services.tg_emoji import e

        lines = [
            f"{e('sport')} <b>FocusLucky — {month}</b>",
            RULE,
            "",
            "🏁 <b>Розыгрыш завершён</b>",
            "",
        ]
        for w in winners:
            lines.append(
                format_winner_line(
                    int(w["place"]),
                    int(w["winning_ticket_no"]),
                    w["prize_rub"],
                    str(w["payout_method"]),
                )
            )
        lines.extend(["", f"🎟 Ваши билеты: {snap['ticket_numbers']}"])
        user_won = [w for w in winners if int(w["user_id"]) == user_id]
        if user_won:
            w = user_won[0]
            lines.append(
                f"\n🎉 <b>Поздравляем!</b> "
                f"<b>{format_place_label(int(w['place']))}</b> · "
                f"билет #{w['winning_ticket_no']} — "
                f"{format_prize_rub(w['prize_rub'])}!"
            )
        elif snap["tickets_total"] > 0:
            lines.append("\n😔 В этот раз не повезло — удачи в следующем месяце!")
        return "\n".join(lines)

    from services.ux_copy import txt_focus_lucky

    draw_line = None
    if campaign["status"] == "active" and campaign.get("draw_at"):
        draw_line = format_draw_countdown_line(campaign["draw_at"])

    return txt_focus_lucky(
        month=month,
        tickets_total=int(snap["tickets_total"] or 0),
        ticket_numbers=str(snap.get("ticket_numbers") or ""),
        win_chance=snap.get("win_chance_label"),
        prizes_html=format_prizes_block(prize_places),
        draw_line=draw_line,
        info_text=resolve_info_text(campaign),
    ) + (await _other_kind_summary(user_id, kind))


async def _other_kind_summary(user_id: int, kind: str) -> str:
    other = "weekly" if kind == "monthly" else "monthly"
    try:
        camp = await get_campaign_for_user(user_id, other)
    except Exception:
        return ""
    if not camp or str(camp.get("status")) not in {"active", "closed", "drawing"}:
        return ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        snap = await get_user_snapshot(camp["id"], user_id, conn)
    title = raffle_kind_title(other)
    if camp.get("draw_at"):
        countdown = format_draw_countdown_line(camp["draw_at"]) or ""
    else:
        countdown = ""
    tickets = int(snap["tickets_total"] or 0)
    chance = snap.get("win_chance_label") or "0%"
    head = f"\n\n➕ <b>{title} розыгрыш</b>: {countdown}" if countdown else f"\n\n➕ <b>{title} розыгрыш</b>"
    return (
        f"{head}\n"
        f"🎟 Ваши билеты: <b>{tickets}</b> · шанс {chance}"
    )


async def find_ticket_owner(
    campaign_id: int, ordinal: int, conn, *, exclude_users: set[int] | None = None
) -> tuple[int, int] | None:
    """Map 1-based ordinal among active tickets to (user_id, winning_ticket_no)."""
    exclude_users = exclude_users or set()
    rows = await conn.fetch(
        """
        SELECT user_id, ticket_no_from, ticket_no_to, ticket_count
        FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND status = 'active'
        ORDER BY ticket_no_from
        """,
        campaign_id,
    )
    pos = 0
    for row in rows:
        uid = int(row["user_id"])
        if uid in exclude_users:
            continue
        pos += int(row["ticket_count"])
        if ordinal <= pos:
            offset = ordinal - (pos - int(row["ticket_count"])) - 1
            winning_no = int(row["ticket_no_from"]) + offset
            return uid, winning_no
    return None


async def run_draw(campaign_id: int, *, moderated_by: int | None = None) -> dict:
    raise ValueError(
        "Мгновенный розыгрыш отключён. Запустите живое шоу FocusLucky."
    )


async def start_show(campaign_id: int) -> dict:
    """Close accrual and arm the live sequential draw. FastAPI closer spins places."""
    from services.config_rates import PUBLIC_SITE_URL

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            camp = await conn.fetchrow(
                "SELECT * FROM raffle_campaigns WHERE id = $1 FOR UPDATE",
                campaign_id,
            )
            if not camp:
                raise ValueError("Кампания не найдена")
            camp = dict(camp)
            status = str(camp["status"])
            if status == "drawing":
                return {"campaign_id": campaign_id, "status": "drawing"}
            if status == "drawn":
                raise ValueError("Розыгрыш уже проведён")
            if status not in {"active", "closed"}:
                raise ValueError(f"Нельзя запустить шоу при status={status}")
            existing = await conn.fetchval(
                "SELECT 1 FROM raffle_winners WHERE campaign_id = $1 LIMIT 1",
                campaign_id,
            )
            if existing:
                raise ValueError("Розыгрыш уже проведён")
            total = await pool_active_ticket_count(campaign_id, conn)
            if total <= 0:
                raise ValueError("Нет активных билетов")
            if status == "active":
                await conn.execute(
                    """
                    UPDATE raffle_campaigns
                    SET status = 'closed', updated_at = now()
                    WHERE id = $1 AND status = 'active'
                    """,
                    campaign_id,
                )
            seed = secrets.token_hex(32)
            commit = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            pre = int(camp.get("pre_show_seconds") or 30)
            site = (PUBLIC_SITE_URL or "https://focuspay.org").rstrip("/")
            if "gateway" in site or site.startswith("http://backend"):
                site = "https://focuspay.org"
            url = f"{site}/casino/play/raffle"
            text = (
                "🍀 <b>FocusLucky начинается</b>\n\n"
                "Розыгрыш мест — смотрите в одном месте.\n"
                f'<a href="{url}">Открыть трансляцию</a>'
            )
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET status = 'drawing',
                    draw_seed = $2,
                    draw_commit = $3,
                    show_started_at = now(),
                    current_place = 1,
                    next_spin_at = now() + ($4::int * interval '1 second'),
                    notify_sent_at = COALESCE(notify_sent_at, now()),
                    updated_at = now()
                WHERE id = $1
                """,
                campaign_id,
                seed,
                commit,
                pre,
            )
            recipients = await conn.fetch(
                """
                SELECT user_id FROM raffle_participants
                WHERE campaign_id = $1 AND tickets_total > 0
                """,
                campaign_id,
            )
            payload = json.dumps(
                {
                    "chat_id": 0,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": {
                        "inline_keyboard": [[{"text": "Смотреть розыгрыш", "url": url}]]
                    },
                },
                ensure_ascii=False,
            )
            for row in recipients:
                uid = int(row["user_id"])
                if uid <= 0:
                    continue
                body = json.loads(payload)
                body["chat_id"] = uid
                await conn.execute(
                    """
                    INSERT INTO raffle_notification_outbox
                        (event_key, event_type, campaign_id, recipient_id, payload)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (event_key) DO NOTHING
                    """,
                    f"raffle:{campaign_id}:raffle_started:{uid}"[:160],
                    "raffle_started",
                    campaign_id,
                    uid,
                    json.dumps(body, ensure_ascii=False),
                )
    return {"campaign_id": campaign_id, "status": "drawing", "seed": seed}


async def pay_balance_winners(campaign_id: int) -> list[dict]:
    pool = await get_pool()
    paid: list[dict] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, place, user_id, prize_rub, payout_method, status
                FROM raffle_winners
                WHERE campaign_id = $1
                  AND payout_method = 'balance'
                  AND status = 'pending'
                FOR UPDATE
                """,
                campaign_id,
            )
            for row in rows:
                w = dict(row)
                amount = float(w["prize_rub"])
                note = f"FocusLucky, {w['place']} место"
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                    VALUES ($1, 'adjustment', $2, $3, $4)
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    int(w["user_id"]),
                    amount,
                    f"flucky-{int(campaign_id)}-{int(w['place'])}"[:64],
                    note,
                )
                await conn.execute(
                    """
                    UPDATE raffle_winners
                    SET status = 'paid', paid_at = now(), payout_note = $2
                    WHERE id = $1
                    """,
                    w["id"],
                    note,
                )
                paid.append(w)
    return paid


async def get_campaign_stats(campaign_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await get_campaign_by_id(campaign_id, conn)
        if not camp:
            return {}
        participants = await conn.fetchval(
            "SELECT COUNT(*)::int FROM raffle_participants WHERE campaign_id = $1",
            campaign_id,
        )
        pool_total = await pool_active_ticket_count(campaign_id, conn)
        return {
            "campaign": camp,
            "participants": int(participants or 0),
            "pool_total": pool_total,
            "next_ticket_no": int(camp.get("next_ticket_no") or 1),
        }


async def close_campaign(campaign_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE raffle_campaigns
            SET status = 'closed', updated_at = now()
            WHERE id = $1 AND status = 'active'
            """,
            campaign_id,
        )
        return result.endswith("1")


async def activate_campaign(campaign_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE raffle_campaigns SET status = 'draft', updated_at = now()
                WHERE status = 'active'
                """
            )
            result = await conn.execute(
                """
                UPDATE raffle_campaigns
                SET status = 'active', updated_at = now()
                WHERE id = $1 AND status IN ('draft', 'closed')
                """,
                campaign_id,
            )
            return result.endswith("1")


async def create_monthly_campaign(
    *,
    slug: str,
    month_label: str,
    starts_at: datetime,
    ends_at: datetime,
    draw_at: datetime | None = None,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO raffle_campaigns (
                slug, title, month_label, starts_at, ends_at, draw_at,
                status, prize_places, prize_pool_rub
            )
            VALUES ($1, 'FocusLucky', $2, $3, $4, $5, 'draft', $6::jsonb, 14500)
            RETURNING id
            """,
            slug,
            month_label,
            starts_at,
            ends_at,
            draw_at,
            json.dumps(DEFAULT_PRIZE_PLACES),
        )
        return int(row["id"])


async def start_new_campaign_without_draw(campaign_id: int) -> dict:
    """Close the latest campaign without winners/payouts and start a clean one."""
    from services.raffle_schedule import campaign_schedule

    starts_at, ends_at, draw_at = campaign_schedule()
    month_names = (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    )
    month_label = f"{month_names[starts_at.month - 1]} {starts_at.year}"
    slug = f"focuslucky-{starts_at:%Y%m%d-%H%M%S}"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            latest_id = await conn.fetchval(
                "SELECT id FROM raffle_campaigns ORDER BY id DESC LIMIT 1 FOR UPDATE"
            )
            if latest_id is None or int(latest_id) != int(campaign_id):
                raise ValueError("Кампания уже сменилась. Обновите панель.")

            status = await conn.fetchval(
                "SELECT status FROM raffle_campaigns WHERE id = $1",
                campaign_id,
            )
            if str(status) == "drawing":
                raise ValueError("Дождитесь конца шоу")

            paid_count = await conn.fetchval(
                "SELECT COUNT(*) FROM raffle_winners "
                "WHERE campaign_id = $1 AND status = 'paid'",
                campaign_id,
            )
            if int(paid_count or 0) > 0:
                raise ValueError(
                    "У кампании уже есть выплаты. Запуск без розыгрыша запрещён."
                )

            await conn.execute(
                "DELETE FROM raffle_winners WHERE campaign_id = $1",
                campaign_id,
            )
            await conn.execute(
                """
                UPDATE raffle_campaigns
                SET status = 'closed', draw_seed = NULL, updated_at = now()
                WHERE id = $1
                """,
                campaign_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO raffle_campaigns (
                    slug, title, month_label, starts_at, ends_at, draw_at,
                    status, prize_places, prize_pool_rub
                )
                VALUES ($1, 'FocusLucky', $2, $3, $4, $5,
                        'active', $6::jsonb, 14500)
                RETURNING *
                """,
                slug,
                month_label,
                starts_at,
                ends_at,
                draw_at,
                json.dumps(DEFAULT_PRIZE_PLACES),
            )
            return dict(row)


async def get_campaign_for_admin() -> dict | None:
    """Active campaign or most recent for admin panel."""
    campaign = await get_active_campaign()
    if campaign:
        return campaign
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM raffle_campaigns ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None


async def count_participants(campaign_id: int, conn=None) -> int:
    query = (
        "SELECT COUNT(*)::int FROM raffle_participants WHERE campaign_id = $1"
    )

    async def _run(c):
        val = await c.fetchval(query, campaign_id)
        return int(val or 0)

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


async def list_participants_page(
    campaign_id: int,
    *,
    offset: int = 0,
    limit: int = 15,
    conn=None,
) -> list[dict]:
    query = """
        SELECT p.user_id, p.tickets_own, p.tickets_referral, p.tickets_total,
               p.own_volume_rub, p.referral_volume_rub,
               bu.username,
               EXISTS (
                   SELECT 1 FROM raffle_accrual_blocks b
                   WHERE b.campaign_id = p.campaign_id AND b.user_id = p.user_id
               ) AS accrual_blocked
        FROM raffle_participants p
        LEFT JOIN bot_users bu ON bu.user_id = p.user_id
        WHERE p.campaign_id = $1
        ORDER BY p.tickets_total DESC, p.user_id ASC
        OFFSET $2 LIMIT $3
    """

    async def _run(c):
        rows = await c.fetch(query, campaign_id, offset, limit)
        return [dict(r) for r in rows]

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


def format_participant_admin_line(
    row: dict, *, rank: int, pool_total: int
) -> str:
    uid = int(row["user_id"])
    username = row.get("username")
    uname = f"@{username}" if username else "—"
    tickets = int(row["tickets_total"])
    own = int(row["tickets_own"])
    ref = int(row["tickets_referral"])
    chance = format_chance_pct(win_chance_pct(tickets, pool_total))
    blocked = " 🚫" if row.get("accrual_blocked") else ""
    return (
        f"{rank}. <code>{uid}</code> {uname}{blocked}\n"
        f"   билеты: <b>{tickets}</b> (свои {own} / реф {ref}) · шанс <b>{chance}</b>"
    )


async def is_accrual_blocked(
    campaign_id: int,
    user_id: int,
    conn=None,
    *,
    kind: str | None = None,
) -> bool:
    query = """
        SELECT scope FROM raffle_accrual_blocks
        WHERE campaign_id = $1 AND user_id = $2
        LIMIT 1
    """

    async def _run(c):
        row = await c.fetchrow(query, campaign_id, user_id)
        if not row:
            return False
        scope = str(row["scope"] or "all")
        if scope == "all":
            return True
        if scope == "referral" and kind == KIND_REFERRAL:
            return True
        return False

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


async def get_accrual_block_scope(
    campaign_id: int, user_id: int, conn=None
) -> str | None:
    query = """
        SELECT scope FROM raffle_accrual_blocks
        WHERE campaign_id = $1 AND user_id = $2
        LIMIT 1
    """

    async def _run(c):
        row = await c.fetchrow(query, campaign_id, user_id)
        return str(row["scope"]) if row else None

    if conn is not None:
        return await _run(conn)
    pool = await get_pool()
    async with pool.acquire() as acquired:
        return await _run(acquired)


async def set_accrual_blocked(
    campaign_id: int,
    user_id: int,
    blocked: bool,
    *,
    blocked_by: int | None = None,
    note: str | None = None,
    scope: str = "all",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if blocked:
            await conn.execute(
                """
                INSERT INTO raffle_accrual_blocks (
                    campaign_id, user_id, blocked_by, note, scope
                )
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (campaign_id, user_id) DO UPDATE
                SET blocked_by = EXCLUDED.blocked_by,
                    note = COALESCE(EXCLUDED.note, raffle_accrual_blocks.note),
                    scope = EXCLUDED.scope
                """,
                campaign_id,
                user_id,
                blocked_by,
                note,
                scope,
            )
        else:
            await conn.execute(
                """
                DELETE FROM raffle_accrual_blocks
                WHERE campaign_id = $1 AND user_id = $2
                """,
                campaign_id,
                user_id,
            )


async def update_campaign_text(
    campaign_id: int,
    *,
    info_text: str | None = None,
    how_to_text: str | None = None,
    clear_info: bool = False,
    clear_how: bool = False,
) -> bool:
    sets: list[str] = ["updated_at = now()"]
    args: list[Any] = []
    idx = 1

    if clear_info:
        sets.append("info_text = NULL")
    elif info_text is not None:
        sets.append(f"info_text = ${idx}")
        args.append(info_text)
        idx += 1

    if clear_how:
        sets.append("how_to_text = NULL")
    elif how_to_text is not None:
        sets.append(f"how_to_text = ${idx}")
        args.append(how_to_text)
        idx += 1

    if len(sets) == 1:
        return False

    args.append(campaign_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE raffle_campaigns SET {', '.join(sets)} WHERE id = ${idx}",
            *args,
        )
        return result.endswith("1")


async def get_participant_admin_detail(
    campaign_id: int, user_id: int
) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        participant = await get_participant(campaign_id, user_id, conn)
        if not participant:
            blocked = await is_accrual_blocked(campaign_id, user_id, conn)
            if not blocked:
                return None
            row = await conn.fetchrow(
                "SELECT username FROM bot_users WHERE user_id = $1",
                user_id,
            )
            return {
                "user_id": user_id,
                "username": row["username"] if row else None,
                "tickets_own": 0,
                "tickets_referral": 0,
                "tickets_total": 0,
                "own_volume_rub": 0,
                "referral_volume_rub": 0,
                "accrual_blocked": True,
                "ticket_numbers": "—",
                "win_chance_label": "0%",
            }

        snap = await get_user_snapshot(campaign_id, user_id, conn)
        username = await conn.fetchval(
            "SELECT username FROM bot_users WHERE user_id = $1",
            user_id,
        )
        blocked = await is_accrual_blocked(campaign_id, user_id, conn)
        return {
            **participant,
            "username": username,
            "accrual_blocked": blocked,
            "ticket_numbers": snap["ticket_numbers"],
            "win_chance_label": snap["win_chance_label"],
        }

"""FocusLucky raffle — admin API service (shared DB with tg bot)."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from db import get_pool
from raffle_phase import campaign_phase
from user_referral_db import fetch_user_referrer
import casino_raffle as raffle_show

PRIZE_PLACES_COUNT = raffle_show.MAX_PLACES
MSK = timezone(timedelta(hours=3))
MONTH_NAMES = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)

DEFAULT_PRIZE_PLACES = raffle_show.DEFAULT_PRIZE_PLACES


def next_cycle_times(*, now: datetime | None = None, kind: str = "monthly") -> tuple[datetime, datetime, datetime, str, str]:
    starts_at = now or datetime.now(MSK)
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=MSK)
    kind = str(kind or "monthly").lower()
    if kind == "weekly":
        # Next Sunday 20:00 MSK
        days_ahead = (6 - starts_at.weekday()) % 7 or 7
        draw_day = (starts_at + timedelta(days=days_ahead)).date()
    else:
        draw_day = (starts_at + timedelta(days=30)).date()
    draw_at = datetime(draw_day.year, draw_day.month, draw_day.day, 20, 0, 0, tzinfo=MSK)
    ends_at = draw_at - timedelta(seconds=1)
    month_label = f"{MONTH_NAMES[starts_at.month - 1]} {starts_at.year}"
    slug = f"focuslucky-{starts_at:%Y%m%d-%H%M%S}" if kind == "monthly" else f"focuslucky-weekly-{starts_at:%Y%m%d-%H%M%S}"
    return starts_at, ends_at, draw_at, month_label, slug


def month_key_msk_local(value: datetime | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    at = value if value.tzinfo is not None else value.replace(tzinfo=MSK)
    local = at.astimezone(MSK)
    return f"{local.year:04d}-{local.month:02d}"


async def check_draw_conflict(draw_at_utc: datetime, *, exclude_id: int | None = None) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await raffle_show.check_draw_conflict(conn, draw_at_utc, exclude_id=exclude_id)


async def create_campaign(*, kind: str, draw_at: datetime, prize_places: Any | None = None) -> dict:
    from datetime import timezone as _tz
    kind = raffle_show.normalize_kind(kind)
    if draw_at.tzinfo is None:
        draw_at = draw_at.replace(tzinfo=MSK)
    draw_utc = draw_at.astimezone(_tz.utc)
    starts = datetime.now(MSK).astimezone(_tz.utc)
    if draw_utc <= starts:
        raise ValueError("Время розыгрыша должно быть в будущем")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            conflict = await raffle_show.check_draw_conflict(conn, draw_utc)
            if conflict:
                raise ValueError(raffle_show.conflict_message(conflict))
            places = raffle_show.normalize_prize_places(
                prize_places if prize_places else list(DEFAULT_PRIZE_PLACES)
            )
            pool_rub = float(raffle_show.prize_pool_rub(places))
            msk_draw = draw_utc.astimezone(MSK)
            month_label = f"{MONTH_NAMES[msk_draw.month - 1]} {msk_draw.year}"
            slug = f"focuslucky-{kind}-{msk_draw:%Y%m%d-%H%M}-{secrets.token_hex(3)}"
            mkey = f"{msk_draw.year:04d}-{msk_draw.month:02d}"
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO raffle_campaigns (
                        slug, title, month_label, kind, month_key,
                        starts_at, ends_at, draw_at, status,
                        prize_places, prize_pool_rub
                    )
                    VALUES ($1, 'FocusLucky', $2, $3, $4, $5, $6, $7,
                            'active', $8::jsonb, $9)
                    RETURNING *
                    """,
                    slug, month_label, kind, mkey, starts,
                    draw_utc - timedelta(seconds=1), draw_utc,
                    json.dumps(places), pool_rub,
                )
            except Exception:
                # DB without kind/month_key columns (migration not applied)
                row = await conn.fetchrow(
                    """
                    INSERT INTO raffle_campaigns (
                        slug, title, month_label,
                        starts_at, ends_at, draw_at, status,
                        prize_places, prize_pool_rub
                    )
                    VALUES ($1, 'FocusLucky', $2, $3, $4, $5,
                            'active', $6::jsonb, $7)
                    RETURNING *
                    """,
                    slug, month_label, starts,
                    draw_utc - timedelta(seconds=1), draw_utc,
                    json.dumps(places), pool_rub,
                )
            return _serialize_row(row)

DEFAULT_INFO_TEXT = (
    "+1 билет за каждые 1 000 ₽ вашего обмена\n"
    "+1 билет за каждые 3 000 ₽ обменов ваших друзей"
)

DEFAULT_HOW_TO_TEXT = (
    "<b>Как получить билеты FocusLucky</b>\n\n"
    "• <b>+1 билет</b> за каждые <b>1 000 ₽</b> вашего обмена\n"
    "• <b>+1 билет</b> за каждые <b>3 000 ₽</b> обменов ваших друзей "
    "по реферальной ссылке\n\n"
    "Билеты начисляются автоматически после успешного обмена.\n"
    "У каждого билета есть уникальный номер."
)


def _serialize_row(row) -> dict:
    if row is None:
        return {}
    out = dict(row)
    for key, val in out.items():
        if isinstance(val, datetime):
            out[key] = val.isoformat()
        elif isinstance(val, (dict, list)):
            continue
        elif hasattr(val, "__float__") and not isinstance(val, (int, float, bool)):
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                pass
    if "prize_places" in out and isinstance(out["prize_places"], str):
        out["prize_places"] = json.loads(out["prize_places"])
    return out


def _parse_prize_places(raw: Any) -> list[dict]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not raw:
        return list(DEFAULT_PRIZE_PLACES)
    return list(raw)


def win_chance_pct(user_tickets: int, pool_total: int) -> float:
    return raffle_show.chance_pct(user_tickets, pool_total)


def format_chance_pct(pct: float) -> str:
    if pct <= 0:
        return "0%"
    if pct == int(pct):
        return f"{int(pct)}%"
    return f"{pct:g}%"


def format_ticket_numbers(ranges: list[dict], *, max_show: int = 20) -> str:
    if not ranges:
        return "—"
    parts: list[str] = []
    total = 0
    for r in ranges:
        f, t, c = int(r["ticket_no_from"]), int(r["ticket_no_to"]), int(r["ticket_count"])
        total += c
        parts.append(f"#{f}" if f == t else f"#{f}–#{t}")
    if total <= 3:
        return ", ".join(parts)
    if total <= max_show:
        return f"{', '.join(parts)} ({total} шт.)"
    first, last = ranges[0], ranges[-1]
    return f"#{first['ticket_no_from']}–#{last['ticket_no_to']} ({total} шт.)"


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


async def get_active_campaign(conn) -> dict | None:
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
    return _serialize_row(row) if row else None


async def get_campaign_by_id(campaign_id: int, conn) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM raffle_campaigns WHERE id = $1",
        campaign_id,
    )
    return _serialize_row(row) if row else None


async def get_campaign_for_admin() -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await get_active_campaign(conn)
        if camp:
            return camp
        row = await conn.fetchrow(
            "SELECT * FROM raffle_campaigns ORDER BY id DESC LIMIT 1"
        )
        return _serialize_row(row) if row else None


def _format_prize_places_display(places: list[dict]) -> list[dict]:
    out = []
    for p in sorted(places, key=lambda x: int(x["place"])):
        method = str(p.get("payout_method", "balance"))
        out.append(
            {
                "place": int(p["place"]),
                "prize_rub": float(p.get("prize_rub", 0)),
                "payout_method": method,
                "payout_label": "LTC" if method == "ltc" else "Баланс",
            }
        )
    return out


def _participant_item(row: dict, *, rank: int, pool_total: int) -> dict:
    tickets = int(row["tickets_total"])
    scope = row.get("accrual_block_scope")
    return {
        "rank": rank,
        "user_id": int(row["user_id"]),
        "username": row.get("username"),
        "tickets_own": int(row["tickets_own"]),
        "tickets_referral": int(row["tickets_referral"]),
        "tickets_total": tickets,
        "own_volume_rub": float(row["own_volume_rub"] or 0),
        "referral_volume_rub": float(row["referral_volume_rub"] or 0),
        "win_chance_pct": win_chance_pct(tickets, pool_total),
        "win_chance_label": format_chance_pct(win_chance_pct(tickets, pool_total)),
        "accrual_blocked": scope == "all",
        "referral_accrual_blocked": scope in ("all", "referral"),
        "accrual_block_scope": scope,
    }


async def get_campaign_overview() -> dict | None:
    camp = await get_campaign_for_admin()
    if not camp:
        return None
    cid = int(camp["id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        stats_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int AS participants,
                COALESCE(SUM(tickets_own), 0)::int AS tickets_own_total,
                COALESCE(SUM(tickets_referral), 0)::int AS tickets_referral_total,
                COALESCE(SUM(own_volume_rub), 0)::float AS own_volume_total_rub,
                COALESCE(SUM(referral_volume_rub), 0)::float AS referral_volume_total_rub
            FROM raffle_participants
            WHERE campaign_id = $1
            """,
            cid,
        )
        pool_total = await pool_active_ticket_count(cid, conn)
        blocked = await conn.fetchval(
            "SELECT COUNT(*)::int FROM raffle_accrual_blocks WHERE campaign_id = $1",
            cid,
        )
        top_rows = await conn.fetch(
            """
            SELECT p.user_id, p.tickets_own, p.tickets_referral, p.tickets_total,
                   p.own_volume_rub, p.referral_volume_rub, bu.username,
                   EXISTS (
                       SELECT 1 FROM raffle_accrual_blocks b
                       WHERE b.campaign_id = p.campaign_id AND b.user_id = p.user_id
                   ) AS accrual_blocked
            FROM raffle_participants p
            LEFT JOIN bot_users bu ON bu.user_id = p.user_id
            WHERE p.campaign_id = $1
            ORDER BY p.tickets_total DESC, p.user_id ASC
            LIMIT 5
            """,
            cid,
        )
        accrual_rows = await conn.fetch(
            """
            SELECT r.created_at, r.user_id, r.kind, r.ticket_count,
                   r.ticket_no_from, r.ticket_no_to, r.order_id, bu.username
            FROM raffle_ticket_ranges r
            LEFT JOIN bot_users bu ON bu.user_id = r.user_id
            WHERE r.campaign_id = $1 AND r.status = 'active'
            ORDER BY r.created_at DESC
            LIMIT 15
            """,
            cid,
        )
        winner_rows = await conn.fetch(
            """
            SELECT w.place, w.user_id, w.winning_ticket_no, w.prize_rub,
                   w.payout_method, w.status, w.payout_tx_hash, w.payout_wallet,
                   w.paid_by_operator_id, oa.username AS issuer_username,
                   oa.display_name AS issuer_display_name, bu.username
            FROM raffle_winners w
            LEFT JOIN bot_users bu ON bu.user_id = w.user_id
            LEFT JOIN operator_accounts oa ON oa.id = w.paid_by_operator_id
            WHERE w.campaign_id = $1
            ORDER BY w.place
            """,
            cid,
        )

    phase = campaign_phase(camp)
    prize_places = _parse_prize_places(camp.get("prize_places"))
    stats = dict(stats_row) if stats_row else {}

    winners = []
    winners_paid = 0
    winners_pending_balance = 0
    winners_pending_ltc = 0
    for w in winner_rows:
        wd = dict(w)
        method = str(wd["payout_method"])
        st = str(wd["status"])
        if st == "paid":
            winners_paid += 1
        elif method == "balance":
            winners_pending_balance += 1
        elif method == "ltc":
            winners_pending_ltc += 1
        issuer_username = (wd.get("issuer_username") or "").strip()
        issuer_display = (wd.get("issuer_display_name") or "").strip()
        issuer_label = None
        if wd.get("paid_by_operator_id"):
            if issuer_display and issuer_username:
                issuer_label = f"{issuer_display} (@{issuer_username})"
            elif issuer_username:
                issuer_label = f"@{issuer_username}"
            elif issuer_display:
                issuer_label = issuer_display
            else:
                issuer_label = f"#{wd['paid_by_operator_id']}"
        winners.append(
            {
                "place": int(wd["place"]),
                "user_id": int(wd["user_id"]),
                "username": wd.get("username"),
                "winning_ticket_no": int(wd["winning_ticket_no"]),
                "prize_rub": float(wd["prize_rub"]),
                "payout_method": method,
                "payout_label": "LTC" if method == "ltc" else "Баланс",
                "payout_status": st,
                "payout_tx_hash": wd.get("payout_tx_hash"),
                "payout_wallet": wd.get("payout_wallet"),
                "paid_by_operator_label": issuer_label,
            }
        )

    recent_accruals = []
    for r in accrual_rows:
        rd = dict(r)
        f, t = int(rd["ticket_no_from"]), int(rd["ticket_no_to"])
        ticket_label = f"#{f}" if f == t else f"#{f}–#{t}"
        created = rd["created_at"]
        recent_accruals.append(
            {
                "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                "user_id": int(rd["user_id"]),
                "username": rd.get("username"),
                "kind": str(rd["kind"]),
                "kind_label": "Свой обмен" if rd["kind"] == "own" else "Реферал",
                "ticket_count": int(rd["ticket_count"]),
                "ticket_label": ticket_label,
                "order_id": str(rd["order_id"]),
            }
        )

    top_participants = [
        _participant_item(dict(row), rank=i + 1, pool_total=pool_total)
        for i, row in enumerate(top_rows)
    ]

    return {
        "campaign": camp,
        "participants": int(stats.get("participants") or 0),
        "pool_total": pool_total,
        "next_ticket_no": int(camp.get("next_ticket_no") or 1),
        "accrual_blocked_count": int(blocked or 0),
        "tickets_own_total": int(stats.get("tickets_own_total") or 0),
        "tickets_referral_total": int(stats.get("tickets_referral_total") or 0),
        "own_volume_total_rub": float(stats.get("own_volume_total_rub") or 0),
        "referral_volume_total_rub": float(stats.get("referral_volume_total_rub") or 0),
        "total_tickets_issued": int(camp.get("total_tickets_issued") or 0),
        "total_tickets_void": int(camp.get("total_tickets_void") or 0),
        "prize_pool_rub": float(camp.get("prize_pool_rub") or 0),
        "prize_places": _format_prize_places_display(prize_places),
        "winners": winners,
        "winners_paid_count": winners_paid,
        "winners_pending_balance": winners_pending_balance,
        "winners_pending_ltc": winners_pending_ltc,
        "top_participants": top_participants,
        "recent_accruals": recent_accruals,
        "default_info_text": DEFAULT_INFO_TEXT,
        "default_how_to_text": DEFAULT_HOW_TO_TEXT,
        "resolved_info_text": camp.get("info_text") or DEFAULT_INFO_TEXT,
        "resolved_how_to_text": camp.get("how_to_text") or DEFAULT_HOW_TO_TEXT,
        "spin_interval_seconds": int(camp.get("spin_interval_seconds") or raffle_show.DEFAULT_SPIN_INTERVAL),
        "pre_show_seconds": int(camp.get("pre_show_seconds") or raffle_show.DEFAULT_PRE_SHOW),
        "notify_schedule": raffle_show.notify_schedule(),
        "watch_path": raffle_show.WATCH_PATH,
        "show_started_at": camp.get("show_started_at"),
        "spin_started_at": camp.get("spin_started_at"),
        "next_spin_at": camp.get("next_spin_at"),
        "current_place": camp.get("current_place"),
        "draw_commit": camp.get("draw_commit"),
        "prizes_locked": str(camp.get("status")) in {"drawing", "drawn"},
        "show_settings_locked": str(camp.get("status")) == "drawing",
        "draw_at_locked": str(camp.get("status")) in {"drawing", "drawn"},
        **phase,
    }


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
        blocked = await conn.fetchval(
            "SELECT COUNT(*)::int FROM raffle_accrual_blocks WHERE campaign_id = $1",
            campaign_id,
        )
        return {
            "campaign": camp,
            "participants": int(participants or 0),
            "pool_total": pool_total,
            "next_ticket_no": int(camp.get("next_ticket_no") or 1),
            "accrual_blocked_count": int(blocked or 0),
        }


async def list_participants(
    campaign_id: int,
    *,
    page: int = 1,
    limit: int = 20,
    q: str | None = None,
) -> dict:
    offset = max(0, (page - 1) * limit)
    q = (q or "").strip()
    pool = await get_pool()
    async with pool.acquire() as conn:
        pool_total = await pool_active_ticket_count(campaign_id, conn)

        if q:
            if q.isdigit():
                filter_sql = "AND (p.user_id = $2 OR CAST(p.user_id AS TEXT) LIKE $3)"
                filter_args: list[Any] = [campaign_id, int(q), f"{q}%"]
            else:
                uname = q.lstrip("@").lower()
                filter_sql = "AND LOWER(bu.username) LIKE $2"
                filter_args = [campaign_id, f"%{uname}%"]
            total = await conn.fetchval(
                f"""
                SELECT COUNT(*)::int
                FROM raffle_participants p
                LEFT JOIN bot_users bu ON bu.user_id = p.user_id
                WHERE p.campaign_id = $1 {filter_sql}
                """,
                *filter_args,
            )
            rows = await conn.fetch(
                f"""
                SELECT p.user_id, p.tickets_own, p.tickets_referral, p.tickets_total,
                       p.own_volume_rub, p.referral_volume_rub,
                       bu.username,
                       bl.scope AS accrual_block_scope
                FROM raffle_participants p
                LEFT JOIN bot_users bu ON bu.user_id = p.user_id
                LEFT JOIN raffle_accrual_blocks bl
                    ON bl.campaign_id = p.campaign_id AND bl.user_id = p.user_id
                WHERE p.campaign_id = $1 {filter_sql}
                ORDER BY p.tickets_total DESC, p.user_id ASC
                OFFSET ${len(filter_args) + 1} LIMIT ${len(filter_args) + 2}
                """,
                *filter_args,
                offset,
                limit,
            )
        else:
            total = await conn.fetchval(
                "SELECT COUNT(*)::int FROM raffle_participants WHERE campaign_id = $1",
                campaign_id,
            )
            rows = await conn.fetch(
                """
                SELECT p.user_id, p.tickets_own, p.tickets_referral, p.tickets_total,
                       p.own_volume_rub, p.referral_volume_rub,
                       bu.username,
                       bl.scope AS accrual_block_scope
                FROM raffle_participants p
                LEFT JOIN bot_users bu ON bu.user_id = p.user_id
                LEFT JOIN raffle_accrual_blocks bl
                    ON bl.campaign_id = p.campaign_id AND bl.user_id = p.user_id
                WHERE p.campaign_id = $1
                ORDER BY p.tickets_total DESC, p.user_id ASC
                OFFSET $2 LIMIT $3
                """,
                campaign_id,
                offset,
                limit,
            )

    items = [
        _participant_item(dict(row), rank=offset + i + 1, pool_total=pool_total)
        for i, row in enumerate(rows)
    ]
    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "limit": limit,
        "pool_total": pool_total,
        "q": q or None,
    }


async def get_participant_detail(campaign_id: int, user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*, bu.username, bl.scope AS accrual_block_scope
            FROM raffle_participants p
            LEFT JOIN bot_users bu ON bu.user_id = p.user_id
            LEFT JOIN raffle_accrual_blocks bl
                ON bl.campaign_id = p.campaign_id AND bl.user_id = p.user_id
            WHERE p.campaign_id = $1 AND p.user_id = $2
            """,
            campaign_id,
            user_id,
        )
        blocked_only = False
        if not row:
            block_scope = await conn.fetchval(
                """
                SELECT scope FROM raffle_accrual_blocks
                WHERE campaign_id = $1 AND user_id = $2
                """,
                campaign_id,
                user_id,
            )
            if not block_scope:
                return None
            blocked_only = True
            username = await conn.fetchval(
                "SELECT username FROM bot_users WHERE user_id = $1",
                user_id,
            )
            invited_by = await fetch_user_referrer(conn, user_id)
            return {
                "user_id": user_id,
                "username": username,
                "tickets_own": 0,
                "tickets_referral": 0,
                "tickets_total": 0,
                "own_volume_rub": 0,
                "referral_volume_rub": 0,
                "ticket_numbers": "—",
                "win_chance_label": "0%",
                "accrual_blocked": block_scope == "all",
                "referral_accrual_blocked": block_scope in ("all", "referral"),
                "accrual_block_scope": block_scope,
                "blocked_only": True,
                "invited_by": invited_by,
            }

        r = dict(row)
        ranges = await conn.fetch(
            """
            SELECT ticket_no_from, ticket_no_to, ticket_count
            FROM raffle_ticket_ranges
            WHERE campaign_id = $1 AND user_id = $2 AND status = 'active'
            ORDER BY ticket_no_from
            """,
            campaign_id,
            user_id,
        )
        pool_total = await pool_active_ticket_count(campaign_id, conn)
        tickets = int(r["tickets_total"])
        invited_by = await fetch_user_referrer(conn, user_id)
        scope = r.get("accrual_block_scope")
        return {
            "user_id": user_id,
            "username": r.get("username"),
            "tickets_own": int(r["tickets_own"]),
            "tickets_referral": int(r["tickets_referral"]),
            "tickets_total": tickets,
            "own_volume_rub": float(r["own_volume_rub"] or 0),
            "referral_volume_rub": float(r["referral_volume_rub"] or 0),
            "ticket_numbers": format_ticket_numbers([dict(x) for x in ranges]),
            "win_chance_pct": win_chance_pct(tickets, pool_total),
            "win_chance_label": format_chance_pct(
                win_chance_pct(tickets, pool_total)
            ),
            "accrual_blocked": scope == "all",
            "referral_accrual_blocked": scope in ("all", "referral"),
            "accrual_block_scope": scope,
            "blocked_only": blocked_only,
            "invited_by": invited_by,
        }


async def set_accrual_blocked(
    campaign_id: int,
    user_id: int,
    blocked: bool,
    *,
    blocked_by: int | None = None,
    scope: str = "all",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if blocked:
            await conn.execute(
                """
                INSERT INTO raffle_accrual_blocks (campaign_id, user_id, blocked_by, scope)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (campaign_id, user_id) DO UPDATE
                SET blocked_by = EXCLUDED.blocked_by,
                    scope = EXCLUDED.scope
                """,
                campaign_id,
                user_id,
                blocked_by,
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


async def list_raffle_partners(
    campaign_id: int,
    *,
    page: int = 1,
    limit: int = 30,
    q: str | None = None,
) -> dict:
    offset = max(0, (page - 1) * limit)
    q = (q or "").strip()

    def _search_clause(param_idx: int) -> str:
        return (
            f"(LOWER(pa.username) LIKE ${param_idx} OR LOWER(pc.code) LIKE ${param_idx} "
            f"OR CAST(pa.telegram_user_id AS TEXT) LIKE ${param_idx} "
            f"OR LOWER(bu.username) LIKE ${param_idx})"
        )

    count_conditions = ["1=1"]
    count_params: list[Any] = []
    if q:
        count_conditions.append(_search_clause(1))
        count_params.append(f"%{q.lstrip('@').lower()}%")
    count_where = " AND ".join(count_conditions)

    row_conditions = ["1=1"]
    row_params: list[Any] = [campaign_id]
    row_idx = 2
    if q:
        row_conditions.append(_search_clause(row_idx))
        row_params.append(f"%{q.lstrip('@').lower()}%")
        row_idx += 1
    row_where = " AND ".join(row_conditions)

    pool = await get_pool()
    async with pool.acquire() as conn:
        pool_total = await pool_active_ticket_count(campaign_id, conn)
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*)::int
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            LEFT JOIN bot_users bu ON bu.user_id = pa.telegram_user_id
            WHERE {count_where}
            """,
            *count_params,
        )
        rows = await conn.fetch(
            f"""
            SELECT
                pa.id AS partner_account_id,
                pa.username AS partner_login,
                pa.display_name,
                pa.telegram_user_id,
                pa.is_active AS partner_is_active,
                pc.id AS promo_campaign_id,
                pc.code AS promo_code,
                pc.is_active AS promo_is_active,
                bu.username AS tg_username,
                rp.tickets_own,
                rp.tickets_referral,
                rp.tickets_total,
                rp.referral_volume_rub,
                bl.scope AS accrual_block_scope,
                (
                    SELECT COUNT(*)::int FROM user_referral_attributions a
                    WHERE a.referrer_user_id = pa.telegram_user_id
                ) AS uref_invited_count,
                (
                    SELECT COUNT(*)::int FROM promo_attributions pa2
                    WHERE pa2.promo_code = pc.code
                ) AS promo_attributed_count
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            LEFT JOIN bot_users bu ON bu.user_id = pa.telegram_user_id
            LEFT JOIN raffle_participants rp
                ON rp.campaign_id = $1 AND rp.user_id = pa.telegram_user_id
            LEFT JOIN raffle_accrual_blocks bl
                ON bl.campaign_id = $1 AND bl.user_id = pa.telegram_user_id
            WHERE {row_where}
            ORDER BY COALESCE(rp.tickets_referral, 0) DESC, pa.username ASC
            OFFSET ${row_idx} LIMIT ${row_idx + 1}
            """,
            *row_params,
            offset,
            limit,
        )

    items = []
    for row in rows:
        r = dict(row)
        uid = r.get("telegram_user_id")
        tickets = int(r["tickets_total"] or 0)
        scope = r.get("accrual_block_scope")
        items.append(
            {
                "partner_account_id": int(r["partner_account_id"]),
                "partner_login": r.get("partner_login"),
                "display_name": r.get("display_name"),
                "promo_code": r.get("promo_code"),
                "promo_campaign_id": int(r["promo_campaign_id"]),
                "telegram_user_id": int(uid) if uid else None,
                "tg_username": r.get("tg_username"),
                "partner_is_active": bool(r.get("partner_is_active")),
                "promo_is_active": bool(r.get("promo_is_active")),
                "tickets_own": int(r.get("tickets_own") or 0),
                "tickets_referral": int(r.get("tickets_referral") or 0),
                "tickets_total": tickets,
                "referral_volume_rub": float(r.get("referral_volume_rub") or 0),
                "win_chance_label": format_chance_pct(win_chance_pct(tickets, pool_total)),
                "uref_invited_count": int(r.get("uref_invited_count") or 0),
                "promo_attributed_count": int(r.get("promo_attributed_count") or 0),
                "referral_accrual_blocked": scope in ("all", "referral"),
                "accrual_blocked": scope == "all",
                "accrual_block_scope": scope,
                "telegram_bound": uid is not None,
            }
        )
    return {
        "items": items,
        "total": int(total or 0),
        "page": page,
        "limit": limit,
        "pool_total": pool_total,
        "q": q or None,
    }


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


async def start_new_campaign_without_draw(campaign_id: int) -> dict:
    """Close the latest campaign without winners or payouts and start a clean one."""
    starts_at, ends_at, draw_at, month_label, slug = next_cycle_times()

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            latest_id = await conn.fetchval(
                "SELECT id FROM raffle_campaigns ORDER BY id DESC LIMIT 1 FOR UPDATE"
            )
            if latest_id is None or int(latest_id) != int(campaign_id):
                raise ValueError("Кампания уже сменилась. Обновите страницу.")

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
            return _serialize_row(row)


async def start_next_campaign(campaign_id: int) -> dict:
    """Archive a finished draw in place and open a new editable cycle."""
    starts_at, ends_at, draw_at, month_label, slug = next_cycle_times()
    pool_rub = float(raffle_show.prize_pool_rub(DEFAULT_PRIZE_PLACES))

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            latest_id = await conn.fetchval(
                "SELECT id FROM raffle_campaigns ORDER BY id DESC LIMIT 1 FOR UPDATE"
            )
            if latest_id is None or int(latest_id) != int(campaign_id):
                raise ValueError("Кампания уже сменилась. Обновите страницу.")

            old = await conn.fetchrow(
                "SELECT * FROM raffle_campaigns WHERE id = $1",
                campaign_id,
            )
            if not old:
                raise ValueError("Кампания не найдена")
            old = dict(old)
            status = str(old["status"])
            if status == "drawing":
                raise ValueError("Дождитесь конца шоу")
            if status != "drawn":
                raise ValueError("Следующий цикл можно начать после проведённого розыгрыша")

            cols = [
                "slug",
                "title",
                "month_label",
                "starts_at",
                "ends_at",
                "draw_at",
                "status",
                "prize_places",
                "prize_pool_rub",
            ]
            placeholders = ["$1", "$2", "$3", "$4", "$5", "$6", "'draft'", "$7::jsonb", "$8"]
            vals: list[Any] = [
                slug,
                old.get("title") or "FocusLucky",
                month_label,
                starts_at,
                ends_at,
                draw_at,
                json.dumps(DEFAULT_PRIZE_PLACES),
                pool_rub,
            ]
            optional_defaults: dict[str, Any] = {
                "info_text": None,
                "how_to_text": None,
                "spin_interval_seconds": raffle_show.DEFAULT_SPIN_INTERVAL,
                "pre_show_seconds": raffle_show.DEFAULT_PRE_SHOW,
                "notify_minutes_before": raffle_show.DEFAULT_NOTIFY_MINUTES,
            }
            for name, default in optional_defaults.items():
                if name not in old:
                    continue
                raw = old.get(name)
                cols.append(name)
                if name in {
                    "spin_interval_seconds",
                    "pre_show_seconds",
                    "notify_minutes_before",
                }:
                    vals.append(int(raw if raw is not None else default))
                else:
                    vals.append(raw)
                placeholders.append(f"${len(vals)}")
            row = await conn.fetchrow(
                f"""
                INSERT INTO raffle_campaigns ({", ".join(cols)})
                VALUES ({", ".join(placeholders)})
                RETURNING *
                """,
                *vals,
            )
            return _serialize_row(row)


def merge_admin_campaign_history(
    campaigns: list[dict],
    winner_rows: list[dict],
    *,
    current_id: int | None = None,
) -> list[dict]:
    winners_by_id: dict[int, list[dict]] = {}
    for raw in winner_rows:
        row = dict(raw)
        cid = int(row["campaign_id"])
        winners_by_id.setdefault(cid, []).append(
            {
                "place": int(row["place"]),
                "user_id": int(row["user_id"]),
                "username": row.get("username"),
                "prize_rub": float(row.get("prize_rub") or 0),
                "payout_status": str(row.get("payout_status") or row.get("status") or "pending"),
            }
        )
    out: list[dict] = []
    for raw in campaigns:
        camp = dict(raw)
        cid = int(camp["id"] if "id" in camp else camp["campaign_id"])
        starts = camp.get("starts_at")
        draw = camp.get("draw_at")
        ends = camp.get("ends_at")
        out.append(
            {
                "campaign_id": cid,
                "title": camp.get("title") or "FocusLucky",
                "month_label": camp.get("month_label"),
                "kind": str(camp.get("kind") or "monthly"),
                "month_key": camp.get("month_key"),
                "status": str(camp.get("status") or ""),
                "starts_at": starts.isoformat() if isinstance(starts, datetime) else starts,
                "draw_at": draw.isoformat() if isinstance(draw, datetime) else draw,
                "ends_at": ends.isoformat() if isinstance(ends, datetime) else ends,
                "prize_pool_rub": float(camp.get("prize_pool_rub") or 0),
                "ticket_count": int(camp.get("ticket_count") or 0),
                "winner_count": len(winners_by_id.get(cid, [])),
                "winners": winners_by_id.get(cid, []),
                "is_current": current_id is not None and cid == int(current_id),
            }
        )
    return out


async def list_admin_campaigns(*, limit: int = 24) -> list[dict]:
    current = await get_campaign_for_admin()
    current_id = int(current["id"]) if current else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass('public.raffle_campaigns')")
        if not exists:
            return []
        try:
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.month_label, c.kind, c.month_key, c.status,
                       c.starts_at, c.draw_at, c.ends_at, c.prize_pool_rub,
                       COALESCE((
                           SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                           WHERE t.campaign_id = c.id AND t.status = 'active'
                       ), 0) AS ticket_count
                FROM raffle_campaigns c
                ORDER BY c.id DESC
                LIMIT $1
                """,
                int(limit),
            )
        except Exception:
            rows = await conn.fetch(
                """
                SELECT c.id, c.title, c.month_label, c.status,
                       c.starts_at, c.draw_at, c.ends_at, c.prize_pool_rub,
                       COALESCE((
                           SELECT sum(t.ticket_count) FROM raffle_ticket_ranges t
                           WHERE t.campaign_id = c.id AND t.status = 'active'
                       ), 0) AS ticket_count
                FROM raffle_campaigns c
                ORDER BY c.id DESC
                LIMIT $1
                """,
                int(limit),
            )
        ids = [int(row["id"]) for row in rows]
        winner_rows: list[dict] = []
        if ids:
            winners = await conn.fetch(
                """
                SELECT w.campaign_id, w.place, w.user_id, w.prize_rub,
                       w.status AS payout_status, bu.username
                FROM raffle_winners w
                LEFT JOIN bot_users bu ON bu.user_id = w.user_id
                WHERE w.campaign_id = ANY($1::int[])
                ORDER BY w.campaign_id, w.place
                """,
                ids,
            )
            winner_rows = [dict(row) for row in winners]
        return merge_admin_campaign_history(
            [dict(row) for row in rows],
            winner_rows,
            current_id=current_id,
        )


async def find_ticket_owner(
    campaign_id: int, ordinal: int, conn, *, exclude_users: set[int] | None = None
) -> tuple[int, int] | None:
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


async def run_draw(campaign_id: int) -> dict:
    raise ValueError(
        "Мгновенный розыгрыш отключён. Запустите живое шоу: POST /api/admin/raffle/start-show."
    )


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
                    raffle_show.payout_order_id(campaign_id, int(w["place"])),
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

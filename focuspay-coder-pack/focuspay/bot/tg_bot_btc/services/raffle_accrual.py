"""FocusLucky ticket accrual on PAID orders."""

from __future__ import annotations

import logging
from typing import Any

from services.db import get_pool
from services.raffle_constants import (
    KIND_OWN,
    KIND_REFERRAL,
    format_chance_pct,
    win_chance_pct,
)
from services.raffle_db import (
    get_active_campaign,
    is_accrual_blocked,
    pool_active_ticket_count,
)

logger = logging.getLogger("raffle_accrual")


def _tickets_for_volume(volume: float, rub_per_ticket: float) -> int:
    if rub_per_ticket <= 0:
        return 0
    return int(volume // rub_per_ticket)


async def _upsert_participant_volumes(
    conn,
    campaign_id: int,
    user_id: int,
    *,
    own_delta_rub: float = 0,
    referral_delta_rub: float = 0,
    rub_per_own: float,
    rub_per_referral: float,
    max_tickets: int | None,
) -> tuple[int, int, int, int]:
    """Returns (delta_own, delta_referral, new_total, old_total)."""
    row = await conn.fetchrow(
        """
        SELECT own_volume_rub, referral_volume_rub,
               tickets_own, tickets_referral, tickets_total
        FROM raffle_participants
        WHERE campaign_id = $1 AND user_id = $2
        FOR UPDATE
        """,
        campaign_id,
        user_id,
    )
    if row:
        own_vol = float(row["own_volume_rub"]) + own_delta_rub
        ref_vol = float(row["referral_volume_rub"]) + referral_delta_rub
        old_total = int(row["tickets_total"])
        prev_own = int(row["tickets_own"])
        prev_ref = int(row["tickets_referral"])
    else:
        own_vol = own_delta_rub
        ref_vol = referral_delta_rub
        old_total = 0
        prev_own = 0
        prev_ref = 0

    new_own = _tickets_for_volume(own_vol, rub_per_own)
    new_ref = _tickets_for_volume(ref_vol, rub_per_referral)
    new_total = new_own + new_ref

    if max_tickets is not None and new_total > max_tickets:
        overflow = new_total - max_tickets
        cut_ref = min(new_ref, overflow)
        new_ref -= cut_ref
        overflow -= cut_ref
        new_own = max(0, new_own - overflow)
        new_total = new_own + new_ref

    delta_own = max(0, new_own - prev_own)
    delta_ref = max(0, new_ref - prev_ref)

    if row:
        await conn.execute(
            """
            UPDATE raffle_participants
            SET own_volume_rub = $3,
                referral_volume_rub = $4,
                tickets_own = $5,
                tickets_referral = $6,
                tickets_total = $7,
                updated_at = now()
            WHERE campaign_id = $1 AND user_id = $2
            """,
            campaign_id,
            user_id,
            own_vol,
            ref_vol,
            new_own,
            new_ref,
            new_total,
        )
    else:
        await conn.execute(
            """
            INSERT INTO raffle_participants (
                campaign_id, user_id, own_volume_rub, referral_volume_rub,
                tickets_own, tickets_referral, tickets_total
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            campaign_id,
            user_id,
            own_vol,
            ref_vol,
            new_own,
            new_ref,
            new_total,
        )

    return delta_own, delta_ref, new_total, old_total


async def _allocate_ticket_range(
    conn,
    campaign_id: int,
    user_id: int,
    order_id: str,
    kind: str,
    fiat_amount: float,
    ticket_count: int,
) -> tuple[int, int] | None:
    if ticket_count <= 0:
        return None

    exists = await conn.fetchval(
        """
        SELECT 1 FROM raffle_ticket_ranges
        WHERE campaign_id = $1 AND order_id = $2 AND kind = $3 AND user_id = $4
        """,
        campaign_id,
        order_id,
        kind,
        user_id,
    )
    if exists:
        return None

    camp = await conn.fetchrow(
        "SELECT next_ticket_no FROM raffle_campaigns WHERE id = $1 FOR UPDATE",
        campaign_id,
    )
    if not camp:
        return None

    start_no = int(camp["next_ticket_no"])
    end_no = start_no + ticket_count - 1

    await conn.execute(
        """
        UPDATE raffle_campaigns
        SET next_ticket_no = $2,
            total_tickets_issued = total_tickets_issued + $3,
            updated_at = now()
        WHERE id = $1
        """,
        campaign_id,
        end_no + 1,
        ticket_count,
    )

    await conn.execute(
        """
        INSERT INTO raffle_ticket_ranges (
            campaign_id, user_id, order_id, kind, fiat_amount,
            ticket_no_from, ticket_no_to, ticket_count, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'active')
        """,
        campaign_id,
        user_id,
        order_id,
        kind,
        fiat_amount,
        start_no,
        end_no,
        ticket_count,
    )

    await conn.execute(
        """
        UPDATE raffle_participants
        SET ticket_no_first = COALESCE(ticket_no_first, $3),
            ticket_no_last = $4,
            updated_at = now()
        WHERE campaign_id = $1 AND user_id = $2
        """,
        campaign_id,
        user_id,
        start_no,
        end_no,
    )

    return start_no, end_no


async def _accrue_kind(
    conn,
    campaign: dict,
    user_id: int,
    order_id: str,
    kind: str,
    fiat_amount: float,
    *,
    own_delta_rub: float = 0,
    referral_delta_rub: float = 0,
) -> dict | None:
    if await is_accrual_blocked(campaign["id"], user_id, conn, kind=kind):
        return None

    rub_per_own = float(campaign["rub_per_own_ticket"])
    rub_per_referral = float(campaign["rub_per_referral_ticket"])
    max_tickets = campaign.get("max_tickets_per_user")
    if max_tickets is not None:
        max_tickets = int(max_tickets)

    delta_own, delta_ref, new_total, _old_total = await _upsert_participant_volumes(
        conn,
        campaign["id"],
        user_id,
        own_delta_rub=own_delta_rub,
        referral_delta_rub=referral_delta_rub,
        rub_per_own=rub_per_own,
        rub_per_referral=rub_per_referral,
        max_tickets=max_tickets,
    )

    delta = delta_own if kind == KIND_OWN else delta_ref
    if delta <= 0:
        return None

    allocated = await _allocate_ticket_range(
        conn,
        campaign["id"],
        user_id,
        order_id,
        kind,
        fiat_amount,
        delta,
    )
    if not allocated:
        return None

    start_no, end_no = allocated
    pool_total = await pool_active_ticket_count(campaign["id"], conn)
    pct = win_chance_pct(new_total, pool_total)
    return {
        "kind": kind,
        "delta": delta,
        "ticket_from": start_no,
        "ticket_to": end_no,
        "tickets_total": new_total,
        "win_chance_pct": pct,
        "win_chance_label": format_chance_pct(pct),
    }


async def _raffle_referrer_id(conn, user_id: int) -> int | None:
    """Who receives FocusLucky referral tickets for this buyer.

    Personal referral wins. If there is none, an active partner promo counts
    only when that partner is explicitly enabled (``focuslucky_referral_enabled``).
    A different personal referrer is not replaced and is not doubled.
    """
    attr = await conn.fetchrow(
        """
        SELECT referrer_user_id FROM user_referral_attributions
        WHERE user_id = $1
        """,
        user_id,
    )
    if attr and attr["referrer_user_id"]:
        referrer_id = int(attr["referrer_user_id"])
        if referrer_id != user_id:
            return referrer_id
        return None

    partner = await conn.fetchrow(
        """
        SELECT pa.telegram_user_id
        FROM promo_attributions pr
        JOIN promo_campaigns pc
          ON pc.code = pr.promo_code AND pc.is_active = TRUE
        JOIN partner_accounts pa
          ON pa.promo_campaign_id = pc.id AND pa.is_active = TRUE
        WHERE pr.user_id = $1
          AND pa.focuslucky_referral_enabled = TRUE
          AND pa.telegram_user_id IS NOT NULL
          AND pa.telegram_user_id <> pr.user_id
        LIMIT 1
        """,
        user_id,
    )
    if not partner or not partner["telegram_user_id"]:
        return None
    return int(partner["telegram_user_id"])


async def _accrue_raffle_tickets(
    conn,
    order_id: str,
    *,
    kinds: set[str] | None = None,
) -> list[dict]:
    order = await conn.fetchrow(
        """
        SELECT order_id, user_id, status, direction, fiat_amount,
               payout_confirmed_at, updated_at
        FROM orders WHERE order_id = $1
        """,
        order_id,
    )
    if not order or order["status"] != "PAID":
        return []

    from services.raffle_db import get_active_campaigns

    campaigns = await get_active_campaigns(conn)
    if not campaigns:
        return []
    fiat = float(order["fiat_amount"] or 0)
    results: list[dict] = []
    user_id = int(order["user_id"])
    oid = str(order["order_id"])
    referrer_id = await _raffle_referrer_id(conn, user_id)
    want_own = kinds is None or KIND_OWN in kinds
    want_ref = kinds is None or KIND_REFERRAL in kinds

    for campaign in campaigns:
        min_order = float(campaign.get("min_order_rub") or 0)
        if fiat < min_order:
            continue
        paid_at = order.get("payout_confirmed_at") or order.get("updated_at")
        if paid_at:
            if paid_at.tzinfo is None:
                from datetime import timezone

                paid_at = paid_at.replace(tzinfo=timezone.utc)
            starts = campaign["starts_at"]
            ends = campaign["ends_at"]
            if starts.tzinfo is None:
                starts = starts.replace(tzinfo=paid_at.tzinfo)
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=paid_at.tzinfo)
            if paid_at < starts or paid_at > ends:
                continue

        if want_own:
            own = await _accrue_kind(
                conn,
                campaign,
                user_id,
                oid,
                KIND_OWN,
                fiat,
                own_delta_rub=fiat,
            )
            if own:
                own["campaign_id"] = campaign["id"]
                results.append(own)

        if want_ref and referrer_id:
            ref = await _accrue_kind(
                conn,
                campaign,
                referrer_id,
                oid,
                KIND_REFERRAL,
                fiat,
                referral_delta_rub=fiat,
            )
            if ref:
                ref["campaign_id"] = campaign["id"]
                results.append(ref)

    return results


async def accrue_raffle_tickets(order_id: str, *, conn=None) -> list[dict]:
    if conn is not None:
        return await _accrue_raffle_tickets(conn, order_id)

    pool = await get_pool()
    async with pool.acquire() as acquired:
        async with acquired.transaction():
            return await _accrue_raffle_tickets(acquired, order_id)


async def void_raffle_tickets_for_order(order_id: str, *, conn) -> None:
    ranges = await conn.fetch(
        """
        SELECT id, campaign_id, user_id, kind, ticket_count
        FROM raffle_ticket_ranges
        WHERE order_id = $1 AND status = 'active'
        FOR UPDATE
        """,
        order_id,
    )
    if not ranges:
        return

    order_fiat = await conn.fetchval(
        "SELECT fiat_amount FROM orders WHERE order_id = $1",
        order_id,
    )
    fiat = float(order_fiat or 0)

    for row in ranges:
        r = dict(row)
        await conn.execute(
            "UPDATE raffle_ticket_ranges SET status = 'void' WHERE id = $1",
            r["id"],
        )
        await conn.execute(
            """
            UPDATE raffle_campaigns
            SET total_tickets_void = total_tickets_void + $2, updated_at = now()
            WHERE id = $1
            """,
            r["campaign_id"],
            r["ticket_count"],
        )

        participant = await conn.fetchrow(
            """
            SELECT own_volume_rub, referral_volume_rub
            FROM raffle_participants
            WHERE campaign_id = $1 AND user_id = $2
            FOR UPDATE
            """,
            r["campaign_id"],
            r["user_id"],
        )
        if not participant:
            continue

        own_vol = float(participant["own_volume_rub"])
        ref_vol = float(participant["referral_volume_rub"])
        if r["kind"] == KIND_OWN:
            own_vol = max(0.0, own_vol - fiat)
        else:
            ref_vol = max(0.0, ref_vol - fiat)

        camp = await conn.fetchrow(
            """
            SELECT rub_per_own_ticket, rub_per_referral_ticket
            FROM raffle_campaigns WHERE id = $1
            """,
            r["campaign_id"],
        )
        new_own = _tickets_for_volume(own_vol, float(camp["rub_per_own_ticket"]))
        new_ref = _tickets_for_volume(ref_vol, float(camp["rub_per_referral_ticket"]))

        await conn.execute(
            """
            UPDATE raffle_participants
            SET own_volume_rub = $3,
                referral_volume_rub = $4,
                tickets_own = $5,
                tickets_referral = $6,
                tickets_total = $7,
                updated_at = now()
            WHERE campaign_id = $1 AND user_id = $2
            """,
            r["campaign_id"],
            r["user_id"],
            own_vol,
            ref_vol,
            new_own,
            new_ref,
            new_own + new_ref,
        )


def format_accrual_message(accruals: list[dict]) -> str | None:
    """Message for order buyer after PAID."""
    own = next((a for a in accruals if a.get("kind") == KIND_OWN), None)
    if not own:
        return None
    delta = int(own["delta"])
    total = int(own["tickets_total"])
    chance = own.get("win_chance_label", "0%")
    if delta == 1:
        ticket_part = f"#{own['ticket_from']}"
    else:
        ticket_part = f"#{own['ticket_from']}–#{own['ticket_to']}"
    return (
        f"🎟 +{delta} билета ({ticket_part}) · "
        f"у вас {total} · шанс {chance} · FocusLucky"
    )

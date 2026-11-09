import logging
import secrets
import string
from datetime import date, datetime, timedelta, timezone

from admin_salary import today_moscow
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_partner
from config import settings
from db import get_pool
from partner_commission import (
    get_campaign_available_balance,
    get_campaign_balance,
    get_campaign_pending_withdrawals,
)
from partner_tier import resolve_tier_settings, tier_info
from partner_withdraw import (
    create_partner_withdrawal,
    format_partner_withdrawal_admin_message,
    has_pending_withdrawal as has_partner_pending_withdrawal,
    withdrawal_out,
)
from user_referral_withdraw import (
    create_withdrawal as create_unified_withdrawal,
    format_withdrawal_admin_message,
    withdrawal_admin_inline_keyboard,
    withdrawal_out as unified_withdrawal_out,
)
from user_unified_balance import get_unified_balance_stats
from referral_links import telegram_deep_link, web_onion_ref_link, web_ref_link
from runtime_settings import partner_tier_global, refresh_settings
from telegram_notify import send_admin_message

logger = logging.getLogger("partner_router")
router = APIRouter()


def _partner_public_note(note: object) -> str | None:
    text = str(note or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "от прибыли" in lowered or "(tier)" in lowered:
        return None
    return text


_BIND_ALPHABET = string.ascii_uppercase + string.digits


@router.post("/telegram/bind-token")
async def partner_telegram_bind_token(partner=Depends(get_current_partner)):
    """Одноразовый код для /partner_bind в Telegram-боте (15 мин)."""
    token = "".join(secrets.choice(_BIND_ALPHABET) for _ in range(12))
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE partner_accounts
            SET telegram_bind_token = $1, telegram_bind_expires_at = $2
            WHERE id = $3
            """,
            token,
            expires,
            partner["id"],
        )
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "hint": "В боте: /partner_bind " + token,
    }


@router.get("/link")
async def partner_link(partner=Depends(get_current_partner)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ref_token, code FROM promo_campaigns WHERE id = $1",
            partner["promo_campaign_id"],
        )
    token = row["ref_token"] if row else partner["campaign_code"]
    return {
        "code": partner["campaign_code"],
        "ref_token": token,
        "link": telegram_deep_link(token),
        "web_link": web_ref_link(token),
        "onion_web_link": web_onion_ref_link(token),
    }


@router.get("/dashboard")
async def partner_dashboard(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    partner=Depends(get_current_partner),
):
    today = today_moscow()
    try:
        d_from = date.fromisoformat(date_from) if date_from else None
        d_to = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        d_from = d_to = None

    cid = partner["promo_campaign_id"]
    code = partner["campaign_code"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        balance = await get_campaign_balance(conn, cid)

        attracted = await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
            code,
        )

        order_q = """
            SELECT COUNT(o.id)::int AS paid_count,
                   COALESCE(SUM(o.fiat_amount), 0)::float AS fiat_sum
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
            WHERE o.status IN ('PAID', 'COMPLETED')
        """
        order_params: list = [code]
        if d_from:
            order_q += f" AND o.created_at::date >= ${len(order_params)+1}"
            order_params.append(d_from)
        if d_to:
            order_q += f" AND o.created_at::date <= ${len(order_params)+1}"
            order_params.append(d_to)
        row = await conn.fetchrow(order_q, *order_params)

        period_filter = ""
        ledger_params: list = [cid]
        if d_from:
            period_filter += f" AND created_at::date >= ${len(ledger_params)+1}"
            ledger_params.append(d_from)
        if d_to:
            period_filter += f" AND created_at::date <= ${len(ledger_params)+1}"
            ledger_params.append(d_to)

        accrued = await conn.fetchval(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
            WHERE campaign_id = $1 AND type = 'accrual' {period_filter}
            """,
            *ledger_params,
        )
        paid_out = await conn.fetchval(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
            WHERE campaign_id = $1 AND type = 'payout' {period_filter}
            """,
            *ledger_params,
        )

        campaign = await conn.fetchrow(
            """
            SELECT bonus_percent, ad_spend_rub, partner_commission_percent, ref_token, code,
                   partner_tier_base_percent, partner_tier_step_percent,
                   partner_tier_every_n, partner_tier_max_percent
            FROM promo_campaigns WHERE id = $1
            """,
            cid,
        )
        available = await get_campaign_available_balance(conn, cid)
        pending_wd = await get_campaign_pending_withdrawals(conn, cid)

    await refresh_settings()
    global_tier = partner_tier_global()
    settings = resolve_tier_settings(global_tier, dict(campaign) if campaign else {})
    tier = tier_info(int(attracted or 0), settings)
    eff = tier["effective_percent"]
    every_n = settings["every_n"]
    until = tier["refs_until_next_tier"]
    progress_done = every_n - until if until else every_n

    return {
        "campaign": {
            "id": cid,
            "code": code,
            "name": partner.get("campaign_name"),
            "bonus_percent": float(campaign["bonus_percent"]) if campaign else 0,
            "partner_commission_percent": eff,
            "base_partner_commission_percent": float(campaign["partner_commission_percent"]) if campaign else 10,
            "ad_spend_rub": float(campaign["ad_spend_rub"]) if campaign else 0,
        },
        "tier": {
            "effective_percent": eff,
            "refs_until_next_tier": until,
            "next_tier_percent": tier.get("next_tier_percent"),
            "at_max_tier": tier["at_max_tier"],
            "tier_fixed": tier.get("tier_fixed", False),
            "step_percent": settings["step_percent"],
            "every_n": every_n,
            "max_percent": settings["max_percent"],
            "progress_current": progress_done,
            "progress_total": every_n,
        },
        "commission_basis": "net_profit",
        "commission_basis_label": f"{eff:g}% с чистой прибыли сервиса по каждой оплаченной сделке ваших клиентов",
        "balance_rub": round(balance, 2),
        "available_rub": round(available, 2),
        "pending_withdraw_rub": round(pending_wd, 2),
        "attracted_users": attracted or 0,
        "paid_orders_count": row["paid_count"] if row else 0,
        "paid_fiat_sum": round(float(row["fiat_sum"] if row else 0), 2),
        "period_accrued": round(float(accrued or 0), 2),
        "period_paid_out": round(abs(float(paid_out or 0)), 2),
        "ref_token": campaign["ref_token"] if campaign else code,
        "referral_link": telegram_deep_link(campaign["ref_token"] if campaign else code),
        "referral_web_link": web_ref_link(campaign["ref_token"] if campaign else code),
        "referral_onion_link": web_onion_ref_link(campaign["ref_token"] if campaign else code),
        "period": {
            "from": d_from.isoformat() if d_from else None,
            "to": d_to.isoformat() if d_to else None,
        },
    }


@router.get("/users")
async def partner_users(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    partner=Depends(get_current_partner),
):
    code = partner["campaign_code"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pa.user_id, pa.assigned_at, bu.username, bu.first_name,
                   COUNT(o.id)::int AS total_orders,
                   COUNT(CASE WHEN o.status IN ('PAID','COMPLETED') THEN 1 END)::int AS paid_orders
            FROM promo_attributions pa
            LEFT JOIN bot_users bu ON bu.user_id = pa.user_id
            LEFT JOIN orders o ON o.user_id = pa.user_id
            WHERE pa.promo_code = $1
            GROUP BY pa.user_id, pa.assigned_at, bu.username, bu.first_name
            ORDER BY pa.assigned_at DESC
            LIMIT $2 OFFSET $3
            """,
            code,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1", code
        )
    return {
        "users": [
            {
                "user_id": r["user_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "assigned_at": r["assigned_at"].isoformat() if r["assigned_at"] else None,
                "total_orders": r["total_orders"],
                "paid_orders": r["paid_orders"],
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/orders")
async def partner_orders(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    partner=Depends(get_current_partner),
):
    code = partner["campaign_code"]
    pool = await get_pool()
    conditions = ["pa.promo_code = $1"]
    params: list = [code]
    if status:
        conditions.append(f"o.status = ${len(params)+1}")
        params.append(status.upper())
    where = " AND ".join(conditions)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT o.order_id, o.status, o.direction, o.crypto, o.fiat_amount, o.crypto_amount, o.created_at
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id
            WHERE {where}
            ORDER BY o.created_at DESC
            LIMIT ${len(params)+1} OFFSET ${len(params)+2}
            """,
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*)::int FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id
            WHERE {where}
            """,
            *params,
        )
    return {
        "orders": [
            {
                "order_id": r["order_id"],
                "status": r["status"],
                "direction": r["direction"],
                "crypto": r["crypto"],
                "fiat_amount": r["fiat_amount"],
                "crypto_amount": r["crypto_amount"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/ledger")
async def partner_ledger(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    partner=Depends(get_current_partner),
):
    cid = partner["promo_campaign_id"]
    tg_id = partner.get("telegram_user_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM partner_ledger
            WHERE campaign_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            cid,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM partner_ledger WHERE campaign_id = $1", cid
        )
        balance = await get_campaign_balance(conn, cid)
        available = await get_campaign_available_balance(conn, cid)
        pending_wd = await get_campaign_pending_withdrawals(conn, cid)
        has_pending = await has_partner_pending_withdrawal(conn, cid)

    out = {
        "balance_rub": round(balance, 2),
        "available_rub": round(available, 2),
        "pending_withdraw_rub": round(pending_wd, 2),
        "has_pending_withdrawal": has_pending,
        "min_withdraw_card_rub": settings.partner_min_withdraw_card_rub,
        "entries": [
            {
                "id": r["id"],
                "type": r["type"],
                "amount_rub": float(r["amount_rub"]),
                "order_id": r["order_id"],
                "note": _partner_public_note(r["note"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
        "total": total,
        "unified_balance": False,
    }
    if tg_id:
        unified = await get_unified_balance_stats(int(tg_id))
        out.update(
            {
                "unified_balance": True,
                "balance_rub": unified["balance_rub"],
                "available_rub": unified["available_rub"],
                "client_balance_rub": unified.get("client_balance_rub"),
                "partner_balance_rub": unified.get("partner_balance_rub"),
                "has_pending_withdrawal": unified["has_pending_withdrawal"],
                "min_withdraw_card_rub": unified["min_withdraw_card_rub"],
            }
        )
    return out


class PartnerWithdrawBody(BaseModel):
    amount_rub: float = Field(gt=0)
    method: str = Field(pattern="^(card|crypto)$")
    requisites: str = Field(min_length=5, max_length=500)
    crypto: str | None = None
    network: str | None = None


@router.get("/withdrawals")
async def partner_withdrawals_list(
    limit: int = Query(20, ge=1, le=100),
    partner=Depends(get_current_partner),
):
    cid = partner["promo_campaign_id"]
    tg_id = partner.get("telegram_user_id")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, amount_rub, method, requisites, crypto, network,
                   status, network_fee_rub, payout_amount_rub,
                   payout_tx_hash, reject_reason, created_at, processed_at
            FROM partner_withdrawals
            WHERE campaign_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            cid,
            limit,
        )
        withdrawals = [withdrawal_out(dict(r)) for r in rows]
        if tg_id:
            user_rows = await conn.fetch(
                """
                SELECT id, amount_rub, method, requisites, crypto, network,
                       status, payout_tx_hash, created_at, processed_at
                FROM user_referral_withdrawals
                WHERE referrer_user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                int(tg_id),
                limit,
            )
            unified = [unified_withdrawal_out(dict(r)) for r in user_rows]
            withdrawals = sorted(
                withdrawals + unified,
                key=lambda w: w.get("created_at") or "",
                reverse=True,
            )[:limit]
    return {"withdrawals": withdrawals, "unified_balance": bool(tg_id)}


@router.post("/withdrawals", status_code=201)
async def partner_withdrawals_create(
    body: PartnerWithdrawBody,
    partner=Depends(get_current_partner),
):
    tg_id = partner.get("telegram_user_id")
    if tg_id:
        try:
            row = await create_unified_withdrawal(
                referrer_user_id=int(tg_id),
                amount_rub=body.amount_rub,
                method=body.method,
                requisites=body.requisites,
                crypto=body.crypto,
                network=body.network,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # Notify must not fail the request after the row is committed.
        try:
            msg_id = await send_admin_message(
                format_withdrawal_admin_message(row, partner.get("username")),
                reply_markup=withdrawal_admin_inline_keyboard(int(row["id"])),
            )
            if msg_id:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE user_referral_withdrawals SET admin_message_id = $1 WHERE id = $2",
                        msg_id,
                        row["id"],
                    )
        except Exception as e:
            logger.warning(
                "ops notify failed for unified withdrawal #%s: %s",
                row.get("id"),
                e,
            )
        return unified_withdrawal_out(row)

    cid = partner["promo_campaign_id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        if await has_partner_pending_withdrawal(conn, cid):
            raise HTTPException(
                status_code=400,
                detail="У вас уже есть заявка на вывод в обработке",
            )
    try:
        row = await create_partner_withdrawal(
            campaign_id=cid,
            partner_account_id=int(partner["id"]),
            amount_rub=body.amount_rub,
            method=body.method,
            requisites=body.requisites,
            crypto=body.crypto,
            network=body.network,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        msg_id = await send_admin_message(
            format_partner_withdrawal_admin_message(
                row, username=partner.get("username")
            ),
        )
        if msg_id:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE partner_withdrawals SET admin_message_id = $1 WHERE id = $2",
                    msg_id,
                    row["id"],
                )
    except Exception as e:
        logger.warning(
            "ops notify failed for partner withdrawal #%s: %s",
            row.get("id"),
            e,
        )
    return withdrawal_out(row)

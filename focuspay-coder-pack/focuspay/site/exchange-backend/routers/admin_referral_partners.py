"""Реферальные админы (партнёры с % от прибыли по реф-ссылке)."""

import json
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin, hash_password
from db import get_pool
from partner_commission import get_campaign_available_balance, get_campaign_balance
from partner_referral_profit import (
    fetch_partner_referred_orders,
    partner_service_profit_metrics,
    profit_by_campaign_id,
)
from partner_withdraw import (
    notify_partner_withdrawal_status,
    process_partner_withdrawal_paid,
    reject_partner_withdrawal,
    withdrawal_out,
)
from partner_telegram_notify import notify_partner_rate_change
from partner_tier import (
    partner_effective_percent,
    partner_tier_overrides_for_rate,
    resolve_tier_settings,
    tier_info,
)
from promo_campaigns import effective_promo_status
from referral_links import telegram_deep_link, web_ref_link
from runtime_settings import (
    BUSINESS_KEY,
    _SETTING_KEYS,
    get_settings,
    invalidate_cache,
    partner_tier_global,
    refresh_settings,
)

router = APIRouter()


class PartnerPatch(BaseModel):
    partner_commission_percent: Optional[float] = None
    partner_tier_base_percent: Optional[float] = None
    partner_tier_step_percent: Optional[float] = None
    partner_tier_every_n: Optional[int] = None
    partner_tier_max_percent: Optional[float] = None
    is_active: Optional[bool] = None
    partner_is_active: Optional[bool] = None
    display_name: Optional[str] = None
    ad_spend_rub: Optional[float] = None


class TierSettingsPatch(BaseModel):
    partner_tier_base_percent: Optional[float] = Field(None, ge=0, le=100)
    partner_tier_step_percent: Optional[float] = Field(None, ge=0, le=100)
    partner_tier_every_n: Optional[int] = Field(None, ge=1, le=100)
    partner_tier_max_percent: Optional[float] = Field(None, ge=0, le=100)


class PayoutBody(BaseModel):
    amount_rub: float
    note: Optional[str] = None


class PartnerWithdrawPaidBody(BaseModel):
    payout_tx_hash: Optional[str] = None


class PartnerWithdrawRejectBody(BaseModel):
    reason: Optional[str] = None


def _tier_preview(global_tier: dict[str, Any]) -> list[dict[str, float | int]]:
    every_n = int(global_tier["every_n"])
    refs_samples = [0, every_n, every_n * 2, every_n * 3]
    return [
        {
            "refs": r,
            "effective_percent": partner_effective_percent(
                r,
                base_percent=float(global_tier["base_percent"]),
                step_percent=float(global_tier["step_percent"]),
                every_n=every_n,
                max_percent=float(global_tier["max_percent"]),
            ),
        }
        for r in refs_samples
    ]


async def _partner_tier_fields(conn, row: dict, refs: int) -> dict:
    await refresh_settings()
    global_tier = partner_tier_global()
    settings = resolve_tier_settings(global_tier, dict(row))
    info = tier_info(refs, settings)
    return {
        "effective_percent": info["effective_percent"],
        "refs_until_next_tier": info["refs_until_next_tier"],
        "next_tier_percent": info.get("next_tier_percent"),
        "at_max_tier": info["at_max_tier"],
        "tier_fixed": info.get("tier_fixed", False),
        "tier_base_percent": settings["base_percent"],
        "tier_step_percent": settings["step_percent"],
        "tier_every_n": settings["every_n"],
        "tier_max_percent": settings["max_percent"],
        "partner_tier_base_percent": row.get("partner_tier_base_percent"),
        "partner_tier_step_percent": row.get("partner_tier_step_percent"),
        "partner_tier_every_n": row.get("partner_tier_every_n"),
        "partner_tier_max_percent": row.get("partner_tier_max_percent"),
    }


def _partner_out(row, *, balance: float, activations_used: int, metrics: dict, tier: dict) -> dict:
    token = row.get("ref_token") or row["code"]
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "partner_commission_percent": float(row.get("partner_commission_percent") or 10),
        "effective_percent": tier["effective_percent"],
        "refs_until_next_tier": tier["refs_until_next_tier"],
        "next_tier_percent": tier.get("next_tier_percent"),
        "at_max_tier": tier["at_max_tier"],
        "tier_base_percent": tier["tier_base_percent"],
        "tier_step_percent": tier["tier_step_percent"],
        "tier_every_n": tier["tier_every_n"],
        "tier_max_percent": tier["tier_max_percent"],
        "ad_spend_rub": float(row.get("ad_spend_rub") or 0),
        "campaign_kind": "partner",
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "partner_account_id": row.get("partner_account_id"),
        "partner_username": row.get("partner_username"),
        "partner_display_name": row.get("partner_display_name"),
        "partner_is_active": bool(row.get("partner_is_active", True)),
        "telegram_user_id": row.get("telegram_user_id"),
        "balance_rub": round(balance, 2),
        "attracted_users": activations_used,
        "status": effective_promo_status(
            is_active=bool(row["is_active"]),
            activations_used=activations_used,
            max_activations=0,
            campaign_kind="partner",
        ),
        "referral_link": telegram_deep_link(token),
        "referral_web_link": web_ref_link(token),
        "ref_token": token,
        **metrics,
        **{k: tier[k] for k in (
            "partner_tier_base_percent",
            "partner_tier_step_percent",
            "partner_tier_every_n",
            "partner_tier_max_percent",
        ) if k in tier},
    }


async def _count_activations(conn, promo_code: str) -> int:
    return int(
        await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
            promo_code,
        )
        or 0
    )


async def _partner_metrics(
    conn,
    promo_id: int,
    promo_code: str,
    *,
    profit_gross_rub: float | None = None,
) -> dict:
    attracted = await conn.fetchval(
        "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
        promo_code,
    )
    paid = await conn.fetchrow(
        """
        SELECT COUNT(o.id)::int AS cnt, COALESCE(SUM(o.fiat_amount), 0)::float AS fiat
        FROM orders o
        JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
        WHERE o.status IN ('PAID', 'COMPLETED')
        """,
        promo_code,
    )
    accrued = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
        WHERE campaign_id = $1 AND type = 'accrual'
        """,
        promo_id,
    )
    paid_out = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float FROM partner_ledger
        WHERE campaign_id = $1 AND type = 'payout'
        """,
        promo_id,
    )
    total_accrued = round(float(accrued or 0), 2)
    profit = partner_service_profit_metrics(
        gross=profit_gross_rub if profit_gross_rub is not None else 0.0,
        accrued=total_accrued,
    )
    return {
        "attracted_users": attracted or 0,
        "paid_orders_count": paid["cnt"] if paid else 0,
        "paid_fiat_sum": round(float(paid["fiat"] if paid else 0), 2),
        "total_accrued": total_accrued,
        "total_paid_out": round(abs(float(paid_out or 0)), 2),
        **profit,
    }


@router.get("/referral-partners/tier-settings")
async def get_partner_tier_settings(admin=Depends(get_current_admin)):
    await refresh_settings()
    tier = partner_tier_global()
    settings = await get_settings()
    return {
        "settings": {
            "partner_tier_base_percent": tier["base_percent"],
            "partner_tier_step_percent": tier["step_percent"],
            "partner_tier_every_n": tier["every_n"],
            "partner_tier_max_percent": tier["max_percent"],
            "user_referral_pct": float(settings.get("user_referral_pct", 5)),
        },
        "preview": _tier_preview(tier),
    }


@router.patch("/referral-partners/tier-settings")
async def patch_partner_tier_settings(
    body: TierSettingsPatch, admin=Depends(get_current_admin)
):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No fields to update")

    current = await get_settings()
    merged = {**current, **patch}
    if float(merged["partner_tier_max_percent"]) < float(merged["partner_tier_base_percent"]):
        raise HTTPException(
            status_code=400,
            detail="partner_tier_max_percent must be >= partner_tier_base_percent",
        )
    if int(merged["partner_tier_every_n"]) < 1:
        raise HTTPException(status_code=400, detail="partner_tier_every_n must be >= 1")

    stored = {k: merged[k] for k in _SETTING_KEYS}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
            """,
            BUSINESS_KEY,
            json.dumps(stored),
        )

    invalidate_cache()
    await refresh_settings(force=True)
    tier = partner_tier_global()
    return {
        "settings": {
            "partner_tier_base_percent": tier["base_percent"],
            "partner_tier_step_percent": tier["step_percent"],
            "partner_tier_every_n": tier["every_n"],
            "partner_tier_max_percent": tier["max_percent"],
            "user_referral_pct": float((await get_settings()).get("user_referral_pct", 5)),
        },
        "preview": _tier_preview(tier),
    }


@router.get("/referral-partners")
async def list_referral_partners(admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pc.*,
                   pa.id AS partner_account_id,
                   pa.username AS partner_username,
                   pa.display_name AS partner_display_name,
                   pa.is_active AS partner_is_active,
                   pa.telegram_user_id
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            ORDER BY pc.created_at DESC
            """
        )
        partners = []
        summary = {
            "count": 0,
            "active_count": 0,
            "total_balance_rub": 0.0,
            "total_accrued_rub": 0.0,
            "total_paid_out_rub": 0.0,
            "total_turnover_rub": 0.0,
            "total_service_profit_gross_rub": 0.0,
            "total_service_profit_net_rub": 0.0,
        }
        referred_orders = await fetch_partner_referred_orders(conn)
        gross_by_campaign = profit_by_campaign_id(referred_orders)
        for r in rows:
            balance = await get_campaign_balance(conn, r["id"])
            used = await _count_activations(conn, r["code"])
            metrics = await _partner_metrics(
                conn,
                r["id"],
                r["code"],
                profit_gross_rub=gross_by_campaign.get(r["id"], 0.0),
            )
            tier = await _partner_tier_fields(conn, dict(r), used)
            item = _partner_out(r, balance=balance, activations_used=used, metrics=metrics, tier=tier)
            partners.append(item)
            summary["count"] += 1
            if item["is_active"] and item["partner_is_active"]:
                summary["active_count"] += 1
            summary["total_balance_rub"] += item["balance_rub"]
            summary["total_accrued_rub"] += item["total_accrued"]
            summary["total_paid_out_rub"] += item["total_paid_out"]
            summary["total_turnover_rub"] += item["paid_fiat_sum"]
            summary["total_service_profit_gross_rub"] += item["service_profit_gross_rub"]
            summary["total_service_profit_net_rub"] += item["service_profit_net_rub"]

        summary["total_balance_rub"] = round(summary["total_balance_rub"], 2)
        summary["total_accrued_rub"] = round(summary["total_accrued_rub"], 2)
        summary["total_paid_out_rub"] = round(summary["total_paid_out_rub"], 2)
        summary["total_turnover_rub"] = round(summary["total_turnover_rub"], 2)
        summary["total_service_profit_gross_rub"] = round(
            summary["total_service_profit_gross_rub"], 2
        )
        summary["total_service_profit_net_rub"] = round(
            summary["total_service_profit_net_rub"], 2
        )

    return {"partners": partners, "summary": summary}


@router.patch("/referral-partners/{promo_id}")
async def patch_referral_partner(
    promo_id: int, body: PartnerPatch, admin=Depends(get_current_admin)
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pc.*, pa.id AS partner_account_id
            FROM promo_campaigns pc
            JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            WHERE pc.id = $1
            """,
            promo_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Referral partner not found")

        used_before = await _count_activations(conn, row["code"])
        tier_before = await _partner_tier_fields(conn, dict(row), used_before)
        tg_id = row.get("telegram_user_id")

        pc_updates = {}
        if body.partner_commission_percent is not None:
            if body.partner_commission_percent < 0 or body.partner_commission_percent > 100:
                raise HTTPException(status_code=400, detail="percent must be 0–100")
            pc_updates["partner_commission_percent"] = body.partner_commission_percent
            await refresh_settings()
            global_tier = partner_tier_global()
            tier_overrides = partner_tier_overrides_for_rate(
                body.partner_commission_percent, global_tier
            )
            pc_updates.update(tier_overrides)
        if body.partner_tier_base_percent is not None:
            pc_updates["partner_tier_base_percent"] = body.partner_tier_base_percent
        if body.partner_tier_step_percent is not None:
            pc_updates["partner_tier_step_percent"] = body.partner_tier_step_percent
        if body.partner_tier_every_n is not None:
            pc_updates["partner_tier_every_n"] = body.partner_tier_every_n
        if body.partner_tier_max_percent is not None:
            pc_updates["partner_tier_max_percent"] = body.partner_tier_max_percent
        if body.is_active is not None:
            pc_updates["is_active"] = body.is_active
        if body.ad_spend_rub is not None:
            pc_updates["ad_spend_rub"] = body.ad_spend_rub

        if pc_updates:
            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(pc_updates.keys()))
            row = await conn.fetchrow(
                f"UPDATE promo_campaigns SET {set_clauses}, updated_at = now() WHERE id = $1 RETURNING *",
                promo_id,
                *pc_updates.values(),
            )

        pa_updates = []
        pa_vals = []
        if body.partner_is_active is not None:
            pa_updates.append(f"is_active = ${len(pa_vals)+2}")
            pa_vals.append(body.partner_is_active)
        if body.display_name is not None:
            pa_updates.append(f"display_name = ${len(pa_vals)+2}")
            pa_vals.append(body.display_name)
        if pa_updates:
            await conn.execute(
                f"UPDATE partner_accounts SET {', '.join(pa_updates)} WHERE promo_campaign_id = $1",
                promo_id,
                *pa_vals,
            )

        full = await conn.fetchrow(
            """
            SELECT pc.*,
                   pa.id AS partner_account_id,
                   pa.username AS partner_username,
                   pa.display_name AS partner_display_name,
                   pa.is_active AS partner_is_active,
                   pa.telegram_user_id
            FROM promo_campaigns pc
            JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            WHERE pc.id = $1
            """,
            promo_id,
        )
        balance = await get_campaign_balance(conn, promo_id)
        used = await _count_activations(conn, full["code"])
        referred_orders = await fetch_partner_referred_orders(conn, promo_code=full["code"])
        gross_by_campaign = profit_by_campaign_id(referred_orders)
        metrics = await _partner_metrics(
            conn,
            promo_id,
            full["code"],
            profit_gross_rub=gross_by_campaign.get(promo_id, 0.0),
        )
        tier = await _partner_tier_fields(conn, dict(full), used)

    if tg_id and tier["effective_percent"] != tier_before["effective_percent"]:
        import asyncio

        asyncio.create_task(
            notify_partner_rate_change(
                int(tg_id),
                old_percent=float(tier_before["effective_percent"]),
                new_percent=float(tier["effective_percent"]),
                refs=used,
                tier_after=tier,
                reason="admin",
            )
        )

    return _partner_out(full, balance=balance, activations_used=used, metrics=metrics, tier=tier)


@router.post("/referral-partners/{promo_id}/reset-password")
async def reset_referral_partner_password(promo_id: int, admin=Depends(get_current_admin)):
    password_plain = secrets.token_urlsafe(10)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pa.username
            FROM partner_accounts pa
            WHERE pa.promo_campaign_id = $1
            """,
            promo_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Referral partner not found")
        await conn.execute(
            "UPDATE partner_accounts SET password_hash = $1 WHERE promo_campaign_id = $2",
            hash_password(password_plain),
            promo_id,
        )
    return {
        "username": row["username"],
        "password": password_plain,
        "login_url": "/partner/login",
    }


@router.post("/referral-partners/{promo_id}/payout", status_code=201)
async def referral_partner_payout(
    promo_id: int, body: PayoutBody, admin=Depends(get_current_admin)
):
    if body.amount_rub <= 0:
        raise HTTPException(status_code=400, detail="amount_rub must be positive")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            campaign = await conn.fetchrow(
                """
                SELECT pc.id, pc.code, pa.username
                FROM promo_campaigns pc
                JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
                WHERE pc.id = $1
                FOR UPDATE OF pc
                """,
                promo_id,
            )
            if not campaign:
                raise HTTPException(status_code=404, detail="Referral partner not found")

            balance = await get_campaign_balance(conn, promo_id)
            available = await get_campaign_available_balance(conn, promo_id)
            if body.amount_rub > available + 0.01:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient available balance ({available:.2f} ₽)",
                )

            note = body.note or f"Выплата @{campaign['username']}"
            row = await conn.fetchrow(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, note, created_by_web_user_id)
                VALUES ($1, 'payout', $2, $3, $4)
                RETURNING *
                """,
                promo_id,
                -round(body.amount_rub, 2),
                note,
                admin["id"],
            )
            new_balance = await get_campaign_balance(conn, promo_id)

    return {
        "entry": {
            "id": row["id"],
            "type": row["type"],
            "amount_rub": float(row["amount_rub"]),
            "note": row["note"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        },
        "balance_rub": round(new_balance, 2),
    }


@router.get("/referral-partners/{promo_id}/withdrawals")
async def list_partner_withdrawals(promo_id: int, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        partner = await conn.fetchrow(
            """
            SELECT pa.username, pa.telegram_user_id
            FROM promo_campaigns pc
            JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            WHERE pc.id = $1
            """,
            promo_id,
        )
        if not partner:
            raise HTTPException(status_code=404, detail="Referral partner not found")
        rows = await conn.fetch(
            """
            SELECT w.*, pa.username
            FROM partner_withdrawals w
            JOIN partner_accounts pa ON pa.id = w.partner_account_id
            WHERE w.campaign_id = $1
            ORDER BY w.created_at DESC
            LIMIT 50
            """,
            promo_id,
        )
        out = []
        for r in rows:
            item = withdrawal_out(dict(r))
            item["source"] = "partner"
            out.append(item)

        tg_id = partner["telegram_user_id"]
        if tg_id:
            from user_referral_withdraw import withdrawal_out as unified_out

            urows = await conn.fetch(
                """
                SELECT *
                FROM user_referral_withdrawals
                WHERE referrer_user_id = $1
                ORDER BY created_at DESC
                LIMIT 50
                """,
                int(tg_id),
            )
            for r in urows:
                item = unified_out(dict(r))
                item["amount_rub"] = float(item["amount_rub"])
                item["username"] = partner["username"]
                item["source"] = "unified"
                out.append(item)

        out.sort(key=lambda w: w.get("created_at") or "", reverse=True)
    return {"withdrawals": out[:50]}


@router.post("/referral-partners/withdrawals/{withdrawal_id}/paid")
async def approve_partner_withdrawal(
    withdrawal_id: int,
    body: PartnerWithdrawPaidBody,
    admin=Depends(get_current_admin),
    source: str = "partner",
):
    if source == "unified":
        from user_referral_withdraw import (
            notify_withdrawal_completed,
            process_withdrawal_paid,
            withdrawal_out as unified_out,
        )

        wd, err = await process_withdrawal_paid(
            withdrawal_id,
            payout_tx_hash=(body.payout_tx_hash or "").strip() or None,
        )
        if err == "insufficient_balance":
            raise HTTPException(status_code=400, detail="Недостаточно средств на балансе")
        if not wd:
            raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
        await notify_withdrawal_completed(
            wd, tx_hash=(body.payout_tx_hash or "").strip() or None
        )
        item = unified_out(wd)
        item["source"] = "unified"
        return {"withdrawal": item}

    wd, err = await process_partner_withdrawal_paid(
        withdrawal_id,
        admin_web_user_id=admin["id"],
        payout_tx_hash=(body.payout_tx_hash or "").strip() or None,
    )
    if err == "insufficient_balance":
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе партнёра")
    if not wd:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
    await notify_partner_withdrawal_status(wd, paid=True)
    item = withdrawal_out(wd)
    item["source"] = "partner"
    return {"withdrawal": item}


@router.post("/referral-partners/withdrawals/{withdrawal_id}/reject")
async def reject_partner_withdrawal_admin(
    withdrawal_id: int,
    body: PartnerWithdrawRejectBody,
    admin=Depends(get_current_admin),
    source: str = "partner",
):
    if source == "unified":
        from telegram_notify import send_user_message
        from user_referral_withdraw import (
            WithdrawalCancelError,
            release_empty_withdrawal_triangle,
            withdrawal_out as unified_out,
        )

        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                try:
                    await release_empty_withdrawal_triangle(conn, withdrawal_id)
                except WithdrawalCancelError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                wd = await conn.fetchrow(
                    """
                    UPDATE user_referral_withdrawals
                    SET status = 'rejected', processed_at = now()
                    WHERE id = $1 AND status = 'pending'
                    RETURNING *
                    """,
                    withdrawal_id,
                )
        if not wd:
            raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
        reason = (body.reason or "").strip()
        text = (
            f"❌ Заявка на вывод #{withdrawal_id} отклонена."
            + (f"\nПричина: {reason}" if reason else "")
        )
        await send_user_message(int(wd["referrer_user_id"]), text)
        item = unified_out(dict(wd))
        item["source"] = "unified"
        return {"withdrawal": item}

    wd = await reject_partner_withdrawal(
        withdrawal_id,
        admin_web_user_id=admin["id"],
        reason=body.reason,
    )
    if not wd:
        raise HTTPException(status_code=404, detail="Заявка не найдена или уже обработана")
    await notify_partner_withdrawal_status(wd, paid=False)
    item = withdrawal_out(wd)
    item["source"] = "partner"
    return {"withdrawal": item}

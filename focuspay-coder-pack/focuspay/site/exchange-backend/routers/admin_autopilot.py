"""Админка: автопилот реквизитов и выплат."""
from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_finance_owner, get_current_finance_viewer
from db import get_pool
from runtime_settings import (
    BUSINESS_KEY,
    _SETTING_KEYS,
    get_settings,
    invalidate_cache,
    merge_settings,
    refresh_settings,
    settings_updated_at,
)
from signer_client import fetch_signer_balances, fetch_signer_health, signer_configured

router = APIRouter()
logger = logging.getLogger(__name__)

_AUTO_KEYS = (
    "auto_mode_enabled",
    "auto_no_shift_shadow_mode",
    "auto_no_shift_enabled",
    "auto_no_shift_min_buy_paid",
    "auto_no_shift_max_rub",
    "auto_payout_enabled",
    "auto_payout_max_rub",
    "auto_payout_daily_cap_rub",
    "auto_withdraw_enabled",
    "auto_withdraw_max_rub",
    "auto_min_hot_balance_rub",
    "auto_payout_trusted_topups",
    "auto_payout_wait_funds_max_min",
    "auto_whitelist_user_ids",
    "manual_payout_wallet",
    "manual_wallet_payout_max_rub",
    "manual_wallet_payout_operator_daily_rub",
    "signer_max_tx_btc",
    "signer_max_tx_ltc",
    "signer_daily_cap_btc",
    "signer_daily_cap_ltc",
)


class AutopilotPatch(BaseModel):
    auto_mode_enabled: Optional[bool] = None
    auto_no_shift_shadow_mode: Optional[bool] = None
    auto_no_shift_enabled: Optional[bool] = None
    auto_no_shift_min_buy_paid: Optional[int] = Field(None, ge=0, le=100)
    auto_no_shift_max_rub: Optional[int] = Field(None, ge=0, le=500_000)
    auto_payout_enabled: Optional[bool] = None
    auto_payout_max_rub: Optional[int] = Field(None, ge=0, le=500_000)
    auto_payout_daily_cap_rub: Optional[int] = Field(None, ge=0, le=5_000_000)
    auto_withdraw_enabled: Optional[bool] = None
    auto_withdraw_max_rub: Optional[int] = Field(None, ge=0, le=500_000)
    auto_min_hot_balance_rub: Optional[float] = Field(None, ge=0, le=5_000_000)
    auto_payout_trusted_topups: Optional[bool] = None
    auto_payout_wait_funds_max_min: Optional[int] = Field(None, ge=0, le=1440)
    auto_whitelist_user_ids: Optional[list[int]] = None
    manual_payout_wallet: Optional[Literal["operator", "project"]] = None
    manual_wallet_payout_max_rub: Optional[int] = Field(None, ge=0, le=500_000)
    manual_wallet_payout_operator_daily_rub: Optional[int] = Field(None, ge=0, le=5_000_000)
    signer_max_tx_btc: Optional[float] = Field(None, gt=0, le=50)
    signer_max_tx_ltc: Optional[float] = Field(None, gt=0, le=500)
    signer_daily_cap_btc: Optional[float] = Field(None, gt=0, le=200)
    signer_daily_cap_ltc: Optional[float] = Field(None, gt=0, le=5_000)


def _autopilot_slice(settings: dict[str, Any]) -> dict[str, Any]:
    return {k: settings.get(k) for k in _AUTO_KEYS if k in settings}


@router.get("/autopilot-settings")
async def get_autopilot_settings(_admin=Depends(get_current_finance_viewer)):
    merged = await get_settings()
    status = await _live_status()
    return {
        "settings": _autopilot_slice(merged),
        "updated_at": settings_updated_at(),
        "status": status,
    }


@router.patch("/autopilot-settings")
async def patch_autopilot_settings(
    body: AutopilotPatch,
    _admin=Depends(get_current_finance_viewer),
):
    merged = await get_settings()
    patch = body.model_dump(exclude_unset=True)
    for key, val in patch.items():
        if key not in _AUTO_KEYS:
            continue
        merged[key] = val
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
    try:
        from signer_client import push_signer_policy

        await push_signer_policy()
    except Exception:
        logger.warning("signer policy push after autopilot save failed", exc_info=True)
    return await get_autopilot_settings()


@router.get("/autopilot/recon/{shift_id}")
async def get_autopilot_recon(shift_id: int, _admin=Depends(get_current_finance_viewer)):
    from auto_recon import list_recon_for_shift

    return {"items": await list_recon_for_shift(int(shift_id))}


class TrustTopupBody(BaseModel):
    txid: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    note: str = Field("", max_length=200)


@router.get("/autopilot/funds")
async def get_autopilot_funds(_admin=Depends(get_current_finance_viewer)):
    """Ожидающие пополнения выплаты, отказы по нехватке денег и доверенные пополнения."""
    from auto_settings import auto_payout_trusted_topups, auto_payout_wait_funds_max_min
    from hot_wallet_topups import list_funds_failures, waiting_snapshot
    from signer_client import fetch_signer_topups

    pool = await get_pool()
    async with pool.acquire() as conn:
        stuck = await list_funds_failures(conn)
    topups: dict[str, Any] = {"ok": False, "items": []}
    if signer_configured():
        topups = await fetch_signer_topups("btc")
    return {
        "trusted_topups": auto_payout_trusted_topups(),
        "wait_max_min": auto_payout_wait_funds_max_min(),
        "waiting": waiting_snapshot(),
        "stuck": stuck,
        "topups": {
            "ok": bool(topups.get("ok")),
            "signer_enabled": bool(topups.get("enabled")),
            "max_pending": topups.get("max_pending"),
            "items": topups.get("items") or [],
        },
    }


@router.post("/autopilot/topups")
async def post_trust_topup(body: TrustTopupBody, admin=Depends(get_current_finance_owner)):
    from signer_client import trust_signer_topup

    if not signer_configured():
        raise HTTPException(status_code=503, detail="signer_not_configured")
    who = str((admin or {}).get("username") or (admin or {}).get("id") or "admin")
    note = f"{who}: {body.note.strip()}"[:200] if body.note.strip() else who
    res = await trust_signer_topup("btc", body.txid.lower(), note)
    if not res.get("ok"):
        raise HTTPException(status_code=409, detail=str(res.get("reason") or "rejected"))
    logger.info("trusted topup %s by %s", body.txid, who)
    return res


class RotateDepositBody(BaseModel):
    coin: Literal["btc", "ltc"]


@router.post("/autopilot/deposit-address")
async def post_rotate_deposit_address(
    body: RotateDepositBody,
    admin=Depends(get_current_finance_owner),
):
    """Следующий адрес пополнения. Прежний остаётся в том же кошельке."""
    from project_wallet_archive import record_live_project_addresses
    from signer_client import rotate_signer_deposit_address

    if not signer_configured():
        raise HTTPException(status_code=503, detail="Кошелёк не подключён")
    res = await rotate_signer_deposit_address(body.coin)
    if not res.get("ok"):
        reason = str(res.get("reason") or "rotate_failed")
        who = str((admin or {}).get("username") or (admin or {}).get("id") or "admin")
        logger.warning("deposit rotate %s by %s failed: %s", body.coin, who, reason)
        if reason == "signer_outdated":
            raise HTTPException(status_code=503, detail="Подписант ещё не умеет менять адрес")
        raise HTTPException(status_code=409, detail="Не удалось получить новый адрес")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            known = res.get("known")
            await record_live_project_addresses(
                conn,
                {body.coin: res.get("address")},
                known if isinstance(known, list) else None,
            )
        except Exception:
            logger.warning("rotated address archive skipped", exc_info=True)
    return {"ok": True, "coin": body.coin, "address": res.get("address")}


@router.post("/autopilot/orders/{order_id}/requeue")
async def post_requeue_order(order_id: str, _admin=Depends(get_current_finance_owner)):
    from auto_payout_audit_log import audit_payout_event
    from hot_wallet_topups import requeue_buy_order

    pool = await get_pool()
    async with pool.acquire() as conn:
        reason = await requeue_buy_order(conn, order_id)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    await audit_payout_event(f"order:{order_id}", "requeued", {"by": "admin"})
    return {"ok": True, "order_id": order_id}


@router.patch("/users/{user_id}/auto-override")
async def patch_user_auto_override(
    user_id: int,
    body: dict[str, Any],
    _admin=Depends(get_current_finance_viewer),
):
    raw = body.get("auto_service_override")
    if raw is not None and not isinstance(raw, bool):
        raise HTTPException(status_code=400, detail="auto_service_override must be bool or null")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE bot_users SET auto_service_override = $2 WHERE user_id = $1
            """,
            int(user_id),
            raw,
        )
    return {"user_id": user_id, "auto_service_override": raw}


async def _raw_usdt_rub() -> float:
    """USDT/RUB без buy-пада. Публичный market сдвинут на +2 ₽, для долларов он не годится."""
    try:
        from routers.public import get_exchanger_rates_cached

        raw = await get_exchanger_rates_cached()
        rate = float((raw or {}).get("usdt") or 0)
    except Exception:
        logger.warning("raw usdt rate unavailable", exc_info=True)
        return 0.0
    return rate if rate > 0 else 0.0


@router.get("/autopilot/overview")
async def get_autopilot_overview(_admin=Depends(get_current_finance_viewer)):
    """Всё для страницы автопилота одним запросом: статус, кошелёк, итоги дня, история."""
    import asyncio

    from auto_payout_guard import signer_circuit_closed
    from auto_payout_worker import daily_cap_room
    from hot_wallet_monitor import _coin_rates
    from signer_client import fetch_signer_deposit_addresses

    merged = await get_settings()
    usd_rate_rub = await _raw_usdt_rub()
    configured = signer_configured()
    if configured:
        health, balances, addresses, rates = await asyncio.gather(
            fetch_signer_health(),
            fetch_signer_balances(),
            fetch_signer_deposit_addresses(),
            _coin_rates(),
        )
    else:
        health, balances, addresses, rates = {}, {"coins": {}}, {"addresses": {}}, {}

    coins: list[dict[str, Any]] = []
    total_rub = 0.0
    raw_coins = balances.get("coins") if isinstance(balances.get("coins"), dict) else {}
    addr_map = addresses.get("addresses") if isinstance(addresses.get("addresses"), dict) else {}
    nodes = health.get("nodes") if isinstance(health.get("nodes"), dict) else {}
    for coin in ("btc", "ltc"):
        row = raw_coins.get(coin) if isinstance(raw_coins.get(coin), dict) else {}
        try:
            rate = float(rates.get(coin) or 0)
        except (TypeError, ValueError):
            rate = 0.0
        from hot_wallet_topups import effective_spendable

        spendable = effective_spendable(row)
        value_rub = round(spendable * rate, 2)
        total_rub += value_rub
        coins.append(
            {
                "coin": coin,
                "available": bool(row),
                "confirmed": float(row.get("confirmed") or 0),
                "unconfirmed": float(row.get("unconfirmed") or 0),
                "spendable": spendable,
                "spendable_fast": float(row.get("spendable_fast") or row.get("spendable") or 0),
                "fast_enabled": bool(row.get("fast_enabled")),
                "rate_rub": rate,
                "value_rub": value_rub,
                "deposit_address": addr_map.get(coin),
                "node": nodes.get(coin),
            }
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        circuit = await signer_circuit_closed(conn)
        today = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE status IN ('sent','confirmed'))::int AS sent_count,
              COALESCE(SUM(amount_rub) FILTER (WHERE status IN ('sent','confirmed')), 0)::float
                AS sent_rub,
              COUNT(*) FILTER (WHERE status = 'queued')::int AS queued_count,
              COALESCE(SUM(amount_rub) FILTER (WHERE status = 'queued'), 0)::float AS queued_rub,
              COUNT(*) FILTER (WHERE status = 'failed')::int AS failed_count
            FROM payout_requests
            WHERE created_at >= date_trunc('day', now())
            """
        )
        room = await daily_cap_room(conn)
        payouts = await conn.fetch(
            """
            SELECT pr.request_id, pr.kind, pr.ref_id, pr.user_id, pr.coin, pr.address,
                   pr.amount_crypto, pr.amount_rub, pr.status, pr.txid, pr.reject_reason,
                   pr.created_at, pr.sent_at,
                   bu.username, bu.first_name
            FROM payout_requests pr
            LEFT JOIN bot_users bu ON bu.user_id = pr.user_id
            ORDER BY pr.created_at DESC
            LIMIT 30
            """
        )
        decisions = await conn.fetch(
            """
            SELECT g.user_id, g.direction, g.fiat_amount, g.decision, g.reason,
                   g.shadow_mode, g.created_at, bu.username, bu.first_name
            FROM auto_service_gate_log g
            LEFT JOIN bot_users bu ON bu.user_id = g.user_id
            ORDER BY g.created_at DESC
            LIMIT 30
            """
        )
        shadow = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE reason = 'shadow_would_auto')::int AS would_auto_24h,
              COUNT(*) FILTER (
                WHERE decision = 'block' AND reason <> 'shadow_would_auto'
              )::int AS blocked_24h
            FROM auto_service_gate_log
            WHERE created_at > now() - interval '24 hours'
            """
        )
        queue = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'reserved')::int AS withdrawals_reserved,
              COUNT(*) FILTER (WHERE status = 'sending')::int AS withdrawals_sending
            FROM user_referral_withdrawals
            WHERE status IN ('reserved', 'sending')
            """
        )
        try:
            from network_fees import fees_summary

            fees = await fees_summary(conn)
        except Exception:
            logger.warning("network fees summary unavailable", exc_info=True)
            fees = None
        try:
            from auto_preview import payout_shadow_report

            payout_shadow = await payout_shadow_report(conn)
        except Exception:
            logger.warning("payout shadow report failed", exc_info=True)
            payout_shadow = []
        try:
            from hot_wallet_runway import load_coin_outflow

            outflow = await load_coin_outflow(conn)
        except Exception:
            logger.warning("hot wallet outflow unavailable", exc_info=True)
            outflow = {}
        try:
            from autopilot_savings import build_autopilot_savings

            savings = await build_autopilot_savings(conn)
        except Exception:
            logger.warning("autopilot savings unavailable", exc_info=True)
            from autopilot_savings import empty_savings

            savings = empty_savings()
        try:
            from project_wallet_archive import list_project_addresses, record_live_project_addresses

            known = addresses.get("known") if isinstance(addresses, dict) else None
            await record_live_project_addresses(
                conn,
                addr_map if isinstance(addr_map, dict) else {},
                known if isinstance(known, list) else None,
            )
            wallet_addresses = await list_project_addresses(conn)
        except Exception:
            logger.warning("project wallet address list unavailable", exc_info=True)
            wallet_addresses = []

    from hot_wallet_runway import assemble_runway

    runway = assemble_runway(
        coins=[
            {"coin": c["coin"], "spendable": c["spendable"], "rate_rub": c["rate_rub"]}
            for c in coins
        ],
        outflow=outflow,
        min_hot_balance_rub=float(merged.get("auto_min_hot_balance_rub") or 0),
        signer_ok=bool(configured and health.get("http_status") == 200),
    )

    def _iso(v):
        return v.isoformat() if v else None

    def _who(r) -> dict[str, Any]:
        name = r["username"]
        return {
            "user_id": r["user_id"],
            "username": f"@{name}" if name and not str(name).startswith("@") else name,
            "first_name": r["first_name"],
        }

    return {
        "settings": _autopilot_slice(merged),
        "updated_at": settings_updated_at(),
        "usd_rate_rub": round(usd_rate_rub, 4),
        "signer": {
            "configured": configured,
            "reachable": health.get("http_status") == 200,
            "dry_run": health.get("dry_run"),
            "circuit_closed": circuit,
            "error": health.get("error"),
        },
        "wallet": {
            "coins": coins,
            "total_rub": round(total_rub, 2),
            "min_hot_balance_rub": float(merged.get("auto_min_hot_balance_rub") or 0),
        },
        "runway": runway,
        "savings": savings,
        "wallet_addresses": wallet_addresses,
        "today": {
            **dict(today),
            "daily_cap_rub": float(merged.get("auto_payout_daily_cap_rub") or 0),
            "daily_room_rub": room,
        },
        "queue": dict(queue),
        "shadow": dict(shadow),
        "recent_payouts": [
            {
                "request_id": r["request_id"],
                "kind": r["kind"],
                "ref_id": r["ref_id"],
                **_who(r),
                "coin": r["coin"],
                "address": r["address"],
                "amount_crypto": float(r["amount_crypto"]) if r["amount_crypto"] is not None else None,
                "amount_rub": float(r["amount_rub"] or 0),
                "status": r["status"],
                "txid": r["txid"],
                "reject_reason": r["reject_reason"],
                "created_at": _iso(r["created_at"]),
                "sent_at": _iso(r["sent_at"]),
            }
            for r in payouts
        ],
        "recent_decisions": [
            {
                **_who(r),
                "direction": r["direction"],
                "fiat_amount": float(r["fiat_amount"] or 0),
                "decision": r["decision"],
                "reason": r["reason"],
                "shadow_mode": r["shadow_mode"],
                "created_at": _iso(r["created_at"]),
            }
            for r in decisions
        ],
        "fees": fees,
        "payout_shadow": payout_shadow,
    }


async def _live_status() -> dict[str, Any]:
    from auto_payout_guard import signer_circuit_closed

    circuit = await signer_circuit_closed()
    signer = {
        "configured": signer_configured(),
        "circuit_closed": circuit,
    }
    if signer_configured():
        signer["health"] = await fetch_signer_health()
        signer["balances"] = await fetch_signer_balances()

    pool = await get_pool()
    shadow_stats = {"would_auto_24h": 0, "blocked_24h": 0}
    try:
        async with pool.acquire() as conn:
            shadow_stats["would_auto_24h"] = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*)::int FROM auto_service_gate_log
                    WHERE created_at > now() - interval '24 hours'
                      AND reason = 'shadow_would_auto'
                    """
                )
                or 0
            )
            shadow_stats["blocked_24h"] = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*)::int FROM auto_service_gate_log
                    WHERE created_at > now() - interval '24 hours'
                      AND decision = 'block'
                    """
                )
                or 0
            )
    except Exception:
        pass

    return {"signer": signer, "shadow": shadow_stats}

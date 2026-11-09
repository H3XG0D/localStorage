"""Очередь выплат FocusBet: только source=casino, право casino.payout."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_operator
from db import get_pool
from permissions import PERM_CASINO_PAYOUT, enrich_operator_permissions, require_permission
from routers.operator import (
    BuyPayoutRequest,
    _claimed_by,
    _require_active_shift,
    _withdrawal_out,
)
from user_referral_withdraw import (
    SOURCE_CASINO,
    confirm_withdrawal_crypto_payout,
    get_withdrawal,
    is_casino_withdrawal,
    notify_withdrawal_completed,
    WithdrawalCancelError,
    manual_triangle_payout_error,
    notify_withdrawal_rejected,
    process_withdrawal_paid,
    process_withdrawal_rejected,
    withdrawal_out,
)

router = APIRouter()

_CASINO_WD_SQL = """
    SELECT w.*, oa.username AS operator_username, oa.display_name AS operator_display_name,
           bu.username AS player_username, bu.first_name AS player_first_name
    FROM user_referral_withdrawals w
    LEFT JOIN operator_accounts oa ON oa.id = w.operator_id
    LEFT JOIN bot_users bu ON bu.user_id = w.referrer_user_id
    WHERE COALESCE(w.source, 'balance') = 'casino'
"""


async def _require_casino_payout(op: dict) -> dict:
    enriched = await enrich_operator_permissions(op)
    return require_permission(enriched, PERM_CASINO_PAYOUT)


async def _player_snapshot(conn, user_id: int) -> dict[str, object]:
    from casino_client_profile import (
        SCOPE_OPERATOR,
        build_casino_client_profile,
        payout_player_snapshot,
    )

    uid = int(user_id)
    try:
        profile = await build_casino_client_profile(
            conn,
            uid,
            scope=SCOPE_OPERATOR,
            history_limit=5,
            include_withdrawals=False,
            raise_if_missing=False,
        )
        return payout_player_snapshot(profile)
    except Exception:
        return {
            "user_id": uid,
            "display_name": None,
            "avatar_url": None,
            "available_rub": 0.0,
            "wagering": {},
            "payout_rail": {},
            "raffle_campaign_id": None,
            "raffle_tickets": 0,
            "recent_games": [],
        }


def _payout_out(row: dict, *, current_operator_id: int | None, player: dict | None) -> dict:
    payload = _withdrawal_out(row, current_operator_id=current_operator_id)
    payload["source"] = str(row.get("source") or SOURCE_CASINO)
    payload["player"] = player
    payload["player_username"] = row.get("player_username")
    payload["player_first_name"] = row.get("player_first_name")
    return payload


async def _require_casino_row(withdrawal_id: int):
    wd = await get_withdrawal(withdrawal_id)
    if not wd or not is_casino_withdrawal(dict(wd)):
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return wd


@router.get("/casino/payouts")
async def list_casino_payouts(
    op: dict = Depends(get_current_operator),
):
    op = await _require_casino_payout(op)
    op_id = int(op["id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        incoming = await conn.fetch(
            f"""
            {_CASINO_WD_SQL}
              AND w.status = 'pending' AND w.operator_id IS NULL
            ORDER BY w.created_at ASC
            LIMIT 80
            """
        )
        mine = await conn.fetch(
            f"""
            {_CASINO_WD_SQL}
              AND w.status = 'pending' AND w.operator_id = $1
            ORDER BY w.created_at DESC
            LIMIT 80
            """,
            op_id,
        )
        team = await conn.fetch(
            f"""
            {_CASINO_WD_SQL}
              AND w.status = 'pending'
              AND w.operator_id IS NOT NULL
              AND w.operator_id != $1
            ORDER BY w.created_at DESC
            LIMIT 80
            """,
            op_id,
        )
        snapshots: dict[int, dict[str, object]] = {}
        user_ids = {int(row["referrer_user_id"]) for row in [*incoming, *mine, *team]}
        for uid in user_ids:
            snapshots[uid] = await _player_snapshot(conn, uid)

    def pack(rows):
        return [
            _payout_out(
                dict(row),
                current_operator_id=op_id,
                player=snapshots.get(int(row["referrer_user_id"])),
            )
            for row in rows
        ]

    return {
        "incoming": pack(incoming),
        "mine": pack(mine),
        "team": pack(team),
        "incoming_count": len(incoming),
    }


@router.post("/casino/payouts/{withdrawal_id}/claim")
async def claim_casino_payout(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_active_shift(conn, op["id"])
            existing = await conn.fetchrow(
                """
                SELECT * FROM user_referral_withdrawals
                WHERE id = $1 FOR UPDATE
                """,
                withdrawal_id,
            )
            if not existing or not is_casino_withdrawal(dict(existing)):
                raise HTTPException(status_code=404, detail="Заявка не найдена")
            if existing["status"] != "pending":
                raise HTTPException(status_code=404, detail="Заявка уже обработана")
            if existing["operator_id"] is not None:
                if existing["operator_id"] == op["id"]:
                    return {
                        "withdrawal": withdrawal_out(dict(existing)),
                        "claimed_by": _claimed_by(op),
                    }
                raise HTTPException(status_code=409, detail="Заявка уже у другого оператора")
            row = await conn.fetchrow(
                """
                UPDATE user_referral_withdrawals
                SET operator_id = $2
                WHERE id = $1
                  AND status = 'pending'
                  AND operator_id IS NULL
                  AND COALESCE(source, 'balance') = 'casino'
                RETURNING *
                """,
                withdrawal_id,
                op["id"],
            )
    if not row:
        raise HTTPException(status_code=409, detail="Не удалось принять заявку")
    return {"withdrawal": withdrawal_out(dict(row)), "claimed_by": _claimed_by(op)}


@router.post("/casino/payouts/{withdrawal_id}/payout")
async def payout_casino_crypto(
    withdrawal_id: int,
    body: BuyPayoutRequest,
    op: dict = Depends(get_current_operator),
):
    op = await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
    wd_row = await _require_casino_row(withdrawal_id)
    if wd_row["operator_id"] != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала примите заявку")
    if (wd_row["method"] or "").lower() != "crypto":
        raise HTTPException(status_code=400, detail="Только для крипто-вывода")
    ok, err, wd = await confirm_withdrawal_crypto_payout(withdrawal_id, body.tx_hash)
    if err == "invalid_tx":
        raise HTTPException(status_code=400, detail="Некорректный hash транзакции")
    if err == "already_processed":
        raise HTTPException(status_code=409, detail="Заявка уже обработана")
    if err == "insufficient_balance":
        raise HTTPException(status_code=409, detail="Недостаточно средств на балансе клиента")
    if not ok or not wd:
        raise HTTPException(status_code=409, detail="Не удалось подтвердить выплату")
    await notify_withdrawal_completed(wd, tx_hash=body.tx_hash)
    return {"withdrawal": withdrawal_out(wd)}


@router.post("/casino/payouts/{withdrawal_id}/paid")
async def payout_casino_card(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
        block = await manual_triangle_payout_error(conn, withdrawal_id)
    if block:
        raise HTTPException(status_code=409, detail=block)
    wd_row = await _require_casino_row(withdrawal_id)
    if wd_row["operator_id"] != op["id"]:
        raise HTTPException(status_code=403, detail="Сначала примите заявку")
    if (wd_row["method"] or "").lower() != "card":
        raise HTTPException(status_code=400, detail="Только для вывода на карту")
    wd, err = await process_withdrawal_paid(withdrawal_id)
    if err == "insufficient_balance":
        raise HTTPException(status_code=409, detail="Недостаточно средств на балансе клиента")
    if not wd:
        raise HTTPException(status_code=409, detail="Заявка уже обработана или недостаточно средств")
    await notify_withdrawal_completed(wd)
    return {"withdrawal": withdrawal_out(wd)}


@router.post("/casino/payouts/{withdrawal_id}/reject")
async def reject_casino_payout(
    withdrawal_id: int,
    op: dict = Depends(get_current_operator),
):
    op = await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _require_active_shift(conn, op["id"])
    wd_row = await _require_casino_row(withdrawal_id)
    if wd_row["operator_id"] not in (None, op["id"]):
        raise HTTPException(status_code=403, detail="Заявка у другого оператора")
    try:
        wd = await process_withdrawal_rejected(withdrawal_id)
    except WithdrawalCancelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not wd:
        raise HTTPException(status_code=409, detail="Заявка уже обработана")
    await notify_withdrawal_rejected(wd)
    return {"withdrawal": withdrawal_out(wd)}


@router.get("/users/{user_id}/casino")
async def get_user_casino_profile(
    user_id: int,
    op: dict = Depends(get_current_operator),
):
    from casino_client_profile import SCOPE_OPERATOR, build_casino_client_profile

    await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await build_casino_client_profile(conn, user_id, scope=SCOPE_OPERATOR)


@router.get("/users/{user_id}/casino/history")
async def get_user_casino_history(
    user_id: int,
    op: dict = Depends(get_current_operator),
    before: str | None = Query(None),
    game_type: str | None = Query(None),
):
    from casino_client_profile import load_casino_client_history

    await _require_casino_payout(op)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_casino_client_history(
            conn,
            user_id,
            before=before,
            game_type=game_type,
        )

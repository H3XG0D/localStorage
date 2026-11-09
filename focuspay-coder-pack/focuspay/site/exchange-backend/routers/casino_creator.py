"""Роутер кабинета создателя казино."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import get_current_user
from casino_finance import money
from db import get_pool
from referral_links import web_ref_link

router = APIRouter()


class CreatorPrincipal(BaseModel):
    account_id: int
    web_user_id: int
    ref_token: str


class CreatorProfile(BaseModel):
    account_id: int
    ref_link: str
    balance_rub: float
    total_earned_rub: float
    total_withdrawn_rub: float
    min_withdrawal_rub: float
    games_count: int
    last_game_at: Optional[datetime]


class CreatorStats(BaseModel):
    total_games: int
    total_commission: float
    games_today: int
    commission_today: float
    games_week: int
    commission_week: float
    games_month: int
    commission_month: float


class CreatorGame(BaseModel):
    id: int
    game_id: str
    game_type: str
    bet_rub: float
    commission_rub: float
    my_commission: float
    winner_id: Optional[int]
    status: str
    created_at: datetime
    finished_at: Optional[datetime]


class CreatorWithdrawal(BaseModel):
    id: int
    amount_rub: float
    method: str
    requisites: str
    crypto: Optional[str]
    network: Optional[str]
    status: str
    tx_hash: Optional[str]
    receipt_file: Optional[str]
    reject_reason: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]


class CreateWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount_rub: Decimal = Field(..., gt=Decimal("0"), max_digits=14, decimal_places=2)
    method: str = Field(..., pattern="^(crypto|card|sbp)$")
    requisites: str = Field(..., min_length=1)
    crypto: Optional[str] = None
    network: Optional[str] = None


def _minimum_withdrawal(value: object) -> Decimal:
    if not isinstance(value, dict):
        return Decimal("100.00")
    amount = value.get("amount")
    if isinstance(amount, bool) or amount is None:
        return Decimal("100.00")
    try:
        normalized = money(amount)
    except ValueError:
        return Decimal("100.00")
    return normalized if normalized > 0 else Decimal("100.00")


async def get_creator_account(web_user: dict = Depends(get_current_user)) -> CreatorPrincipal:
    """Resolve an active creator account from the authenticated web user only."""
    web_user_id = web_user.get("id")
    if web_user_id is None:
        raise HTTPException(status_code=401, detail="Invalid user principal")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT cca.id AS account_id, cca.web_user_id, cca.ref_token
            FROM casino_creator_accounts cca
            WHERE cca.web_user_id = $1 AND cca.is_active = TRUE
            """,
            int(web_user_id),
        )
    if not row:
        raise HTTPException(status_code=403, detail="Access denied: not a casino creator")
    return CreatorPrincipal(**dict(row))


@router.get("/me", response_model=CreatorProfile)
async def get_creator_profile(creator: CreatorPrincipal = Depends(get_creator_account)):
    """Получить профиль и баланс назначенного creator account."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT balance_rub, total_earned_rub, total_withdrawn_rub,
                   games_count, last_game_at
            FROM casino_creator_balance
            WHERE creator_account_id = $1
            """,
            creator.account_id,
        )
        minimum = await conn.fetchrow(
            "SELECT value FROM casino_settings WHERE key = 'min_withdrawal_rub'"
        )
        min_withdrawal = _minimum_withdrawal(minimum["value"] if minimum else None)
        if not row:
            await conn.execute(
                """
                INSERT INTO casino_creator_balance (
                    creator_account_id, balance_rub, total_earned_rub,
                    total_withdrawn_rub, games_count
                ) VALUES ($1, 0, 0, 0, 0)
                """,
                creator.account_id,
            )
            row = {
                "balance_rub": 0,
                "total_earned_rub": 0,
                "total_withdrawn_rub": 0,
                "games_count": 0,
                "last_game_at": None,
            }
    return CreatorProfile(
        account_id=creator.account_id,
        ref_link=web_ref_link(creator.ref_token),
        min_withdrawal_rub=float(min_withdrawal),
        **dict(row),
    )


async def _creator_stats(conn, account_id: int, period: timedelta | None = None):
    clause = "" if period is None else " AND created_at >= CURRENT_DATE - $2::interval"
    args = (account_id,) if period is None else (account_id, period)
    return await conn.fetchrow(
        """
        SELECT COUNT(DISTINCT game_id) AS games,
               COALESCE(SUM(amount_rub), 0)::float AS commission
        FROM casino_commission_ledger
        WHERE recipient_type = 'creator'
          AND creator_account_id = $1
          AND status IN ('accrued', 'paid')
        """ + clause,
        *args,
    )


@router.get("/stats", response_model=CreatorStats)
async def get_creator_stats(creator: CreatorPrincipal = Depends(get_creator_account)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await _creator_stats(conn, creator.account_id)
        today = await _creator_stats(conn, creator.account_id, timedelta(days=0))
        week = await _creator_stats(conn, creator.account_id, timedelta(days=7))
        month = await _creator_stats(conn, creator.account_id, timedelta(days=30))
    return CreatorStats(
        total_games=int(total["games"]), total_commission=float(total["commission"]),
        games_today=int(today["games"]), commission_today=float(today["commission"]),
        games_week=int(week["games"]), commission_week=float(week["commission"]),
        games_month=int(month["games"]), commission_month=float(month["commission"]),
    )


@router.get("/games", response_model=list[CreatorGame])
async def get_creator_games(
    creator: CreatorPrincipal = Depends(get_creator_account),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT g.id, g.game_id, g.game_type, g.bet_rub, g.commission_rub,
                   g.winner_id, g.status, g.created_at, g.finished_at,
                   c.amount_rub AS my_commission
            FROM casino_games g
            JOIN casino_commission_ledger c ON c.game_id = g.id
            WHERE c.recipient_type = 'creator'
              AND c.creator_account_id = $1
              AND c.status IN ('accrued', 'paid')
            ORDER BY g.created_at DESC LIMIT $2 OFFSET $3
            """,
            creator.account_id, limit, offset,
        )
    return [CreatorGame(**dict(row)) for row in rows]


@router.get("/withdrawals", response_model=list[CreatorWithdrawal])
async def get_creator_withdrawals(
    creator: CreatorPrincipal = Depends(get_creator_account),
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT id, amount_rub, method, requisites, crypto, network, status,
                   tx_hash, receipt_file, reject_reason, created_at, processed_at
            FROM casino_creator_withdrawals
            WHERE creator_account_id = $1
        """
        rows = await conn.fetch(
            query + (" AND status = $2" if status else "") + " ORDER BY created_at DESC",
            creator.account_id, *([status] if status else []),
        )
    return [CreatorWithdrawal(**dict(row)) for row in rows]


@router.post("/withdrawals", response_model=CreatorWithdrawal)
async def create_withdrawal(
    body: CreateWithdrawalRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    creator: CreatorPrincipal = Depends(get_creator_account),
):
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise HTTPException(status_code=422, detail="Idempotency-Key must not be blank")
    amount = money(body.amount_rub)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT id, amount_rub, method, requisites, crypto, network, status,
                       tx_hash, receipt_file, reject_reason, created_at, processed_at
                FROM casino_creator_withdrawals
                WHERE creator_account_id = $1 AND idempotency_key = $2
                FOR UPDATE
                """,
                creator.account_id,
                normalized_key,
            )
            if existing:
                same_request = (
                    money(existing["amount_rub"]) == amount
                    and existing["method"] == body.method
                    and existing["requisites"] == body.requisites
                    and existing["crypto"] == body.crypto
                    and existing["network"] == body.network
                )
                if not same_request:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key is already bound to another withdrawal request",
                    )
                return CreatorWithdrawal(**dict(existing))

            minimum = await conn.fetchrow(
                "SELECT value FROM casino_settings WHERE key = 'min_withdrawal_rub'"
            )
            min_withdrawal = _minimum_withdrawal(minimum["value"] if minimum else None)
            if amount < min_withdrawal:
                raise HTTPException(
                    status_code=400,
                    detail=f"Minimum withdrawal: {min_withdrawal:.2f} RUB",
                )
            balance = await conn.fetchrow(
                "SELECT balance_rub FROM casino_creator_balance WHERE creator_account_id = $1 FOR UPDATE",
                creator.account_id,
            )
            if not balance or money(balance["balance_rub"]) < amount:
                raise HTTPException(status_code=400, detail="Insufficient balance")
            await conn.execute(
                "UPDATE casino_creator_balance SET balance_rub = balance_rub - $1, updated_at = now() WHERE creator_account_id = $2",
                amount,
                creator.account_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO casino_creator_withdrawals (
                    creator_account_id, idempotency_key, amount_rub,
                    method, requisites, crypto, network, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
                RETURNING id, amount_rub, method, requisites, crypto, network, status,
                          tx_hash, receipt_file, reject_reason, created_at, processed_at
                """,
                creator.account_id,
                normalized_key,
                amount,
                body.method,
                body.requisites,
                body.crypto,
                body.network,
            )
    return CreatorWithdrawal(**dict(row))


@router.post("/withdrawals/{withdrawal_id}/cancel", response_model=CreatorWithdrawal)
async def cancel_withdrawal(
    withdrawal_id: int,
    creator: CreatorPrincipal = Depends(get_creator_account),
):
    """Отменить только не обработанную заявку и вернуть резерв на баланс."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, amount_rub, method, requisites, crypto, network,
                       status, tx_hash, receipt_file, reject_reason, created_at, processed_at
                FROM casino_creator_withdrawals
                WHERE id = $1 AND creator_account_id = $2
                FOR UPDATE
                """,
                withdrawal_id,
                creator.account_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"Withdrawal already {row['status']}")
            await conn.execute(
                """
                UPDATE casino_creator_balance
                SET balance_rub = balance_rub + $1, updated_at = now()
                WHERE creator_account_id = $2
                """,
                row["amount_rub"],
                creator.account_id,
            )
            cancelled = await conn.fetchrow(
                """
                UPDATE casino_creator_withdrawals
                SET status = 'cancelled', processed_at = now()
                WHERE id = $1
                RETURNING id, amount_rub, method, requisites, crypto, network, status,
                          tx_hash, receipt_file, reject_reason, created_at, processed_at
                """,
                withdrawal_id,
            )
    return CreatorWithdrawal(**dict(cancelled))


@router.get("/chart")
async def get_creator_chart(
    creator: CreatorPrincipal = Depends(get_creator_account),
    days: int = Query(30, ge=1, le=365),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DATE(created_at) AS date, COUNT(DISTINCT game_id) AS games,
                   COALESCE(SUM(amount_rub), 0)::float AS commission
            FROM casino_commission_ledger
            WHERE recipient_type = 'creator'
              AND creator_account_id = $1
              AND status IN ('accrued', 'paid')
              AND created_at >= CURRENT_DATE - $2::interval
            GROUP BY DATE(created_at) ORDER BY date DESC
            """,
            creator.account_id, timedelta(days=days),
        )
    return {"days": days, "data": [
        {"date": row["date"].isoformat(), "games": int(row["games"]), "commission": float(row["commission"])}
        for row in rows
    ]}

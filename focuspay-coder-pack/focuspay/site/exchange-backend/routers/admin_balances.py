"""Сводка балансов пользователей и партнёров для админки."""

from fastapi import APIRouter, Depends, Query

from auth import get_current_admin
from db import get_pool
from partner_commission import get_campaign_balance

router = APIRouter()


@router.get("/balances")
async def balances_overview(
    min_rub: float = Query(1.0, ge=0, description="Минимальный баланс для списка"),
    user_limit: int = Query(100, ge=1, le=500),
    _admin=Depends(get_current_admin),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_rows = await conn.fetch(
            """
            WITH cb AS (
                SELECT user_id, COALESCE(SUM(amount_rub), 0)::float AS rub
                FROM user_cashback_ledger
                GROUP BY user_id
            ),
            ref AS (
                SELECT referrer_user_id AS user_id,
                       COALESCE(SUM(amount_rub), 0)::float AS rub
                FROM user_referral_ledger
                GROUP BY referrer_user_id
            ),
            pend AS (
                SELECT referrer_user_id AS user_id,
                       COALESCE(SUM(amount_rub), 0)::float AS rub
                FROM user_referral_withdrawals
                WHERE status = 'pending'
                GROUP BY referrer_user_id
            )
            SELECT
                u.user_id,
                u.username,
                u.first_name,
                COALESCE(cb.rub, 0) AS cashback_rub,
                COALESCE(ref.rub, 0) AS referral_rub,
                COALESCE(pend.rub, 0) AS pending_withdraw_rub,
                COALESCE(cb.rub, 0) + COALESCE(ref.rub, 0) AS balance_rub,
                GREATEST(
                    0,
                    COALESCE(cb.rub, 0) + COALESCE(ref.rub, 0) - COALESCE(pend.rub, 0)
                ) AS available_rub
            FROM bot_users u
            LEFT JOIN cb ON cb.user_id = u.user_id
            LEFT JOIN ref ON ref.user_id = u.user_id
            LEFT JOIN pend ON pend.user_id = u.user_id
            WHERE COALESCE(cb.rub, 0) + COALESCE(ref.rub, 0) >= $1
            ORDER BY balance_rub DESC
            LIMIT $2
            """,
            min_rub,
            user_limit,
        )

        totals_row = await conn.fetchrow(
            """
            SELECT
                (SELECT COALESCE(SUM(amount_rub), 0)::float
                 FROM user_cashback_ledger) AS cashback_total,
                (SELECT COALESCE(SUM(amount_rub), 0)::float
                 FROM user_referral_ledger) AS referral_total,
                (SELECT COALESCE(SUM(amount_rub), 0)::float
                 FROM user_referral_withdrawals WHERE status = 'pending') AS pending_withdrawals
            """
        )

        campaigns = await conn.fetch(
            """
            SELECT id, code, name, is_active
            FROM promo_campaigns
            WHERE partner_commission_percent IS NOT NULL
               OR id IN (SELECT DISTINCT campaign_id FROM partner_ledger)
            ORDER BY code
            """
        )

        partners = []
        partner_balance_sum = 0.0
        for c in campaigns:
            bal = await get_campaign_balance(conn, c["id"])
            if bal < min_rub:
                continue
            partner_balance_sum += bal
            partners.append(
                {
                    "campaign_id": c["id"],
                    "code": c["code"],
                    "name": c["name"],
                    "is_active": c["is_active"],
                    "balance_rub": round(bal, 2),
                }
            )
        partners.sort(key=lambda x: x["balance_rub"], reverse=True)

    cb_total = float(totals_row["cashback_total"] or 0)
    ref_total = float(totals_row["referral_total"] or 0)
    pending = float(totals_row["pending_withdrawals"] or 0)

    users = [
        {
            "user_id": r["user_id"],
            "username": r["username"],
            "first_name": r["first_name"],
            "cashback_rub": round(float(r["cashback_rub"]), 2),
            "referral_rub": round(float(r["referral_rub"]), 2),
            "balance_rub": round(float(r["balance_rub"]), 2),
            "available_rub": round(float(r["available_rub"]), 2),
            "pending_withdraw_rub": round(float(r["pending_withdraw_rub"]), 2),
        }
        for r in user_rows
    ]

    user_balance_sum = sum(u["balance_rub"] for u in users)

    return {
        "totals": {
            "users_cashback_rub": round(cb_total, 2),
            "users_referral_rub": round(ref_total, 2),
            "users_balance_rub": round(cb_total + ref_total, 2),
            "users_available_rub": round(max(0, cb_total + ref_total - pending), 2),
            "pending_withdrawals_rub": round(pending, 2),
            "partners_balance_rub": round(partner_balance_sum, 2),
            "liabilities_rub": round(cb_total + ref_total + partner_balance_sum, 2),
        },
        "users": users,
        "users_listed_balance_rub": round(user_balance_sum, 2),
        "partners": partners,
    }

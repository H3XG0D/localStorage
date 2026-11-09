import secrets
import string
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from author_promo import author_discount_order_stats
from auth import get_current_admin, hash_password, normalize_username, validate_username
from db import get_pool
from partner_commission import get_campaign_available_balance, get_campaign_balance
from partner_referral_profit import (
    fetch_partner_referred_orders,
    partner_service_profit_metrics,
    profit_by_campaign_id,
)
from partner_tier import partner_tier_overrides_for_rate
from promo_campaigns import (
    create_exchange_discount_campaign,
    create_fixed_rub_campaign,
    effective_promo_status,
)
from referral_links import generate_ref_token, telegram_deep_link, web_ref_link
from runtime_settings import partner_tier_global, refresh_settings

router = APIRouter()

_CODE_ALPHABET = string.ascii_uppercase + string.digits


class PromoCreate(BaseModel):
    code: str
    name: str
    bonus_percent: float
    ad_spend_rub: float = 0.0
    partner_commission_percent: float = 10.0
    partner_username: Optional[str] = None
    partner_password: Optional[str] = None
    partner_display_name: Optional[str] = None

    @field_validator("partner_username")
    @classmethod
    def _partner_username(cls, v: Optional[str]) -> Optional[str]:
        return validate_username(v) if v else None


class PromoUpdate(BaseModel):
    name: str | None = None
    bonus_percent: float | None = None
    ad_spend_rub: float | None = None
    partner_commission_percent: float | None = None
    is_active: bool | None = None
    max_activations: int | None = None
    partner_username: Optional[str] = None
    partner_password: Optional[str] = None
    partner_display_name: Optional[str] = None
    partner_is_active: bool | None = None

    @field_validator("partner_username")
    @classmethod
    def _partner_username(cls, v: Optional[str]) -> Optional[str]:
        return validate_username(v) if v else None


class PayoutBody(BaseModel):
    amount_rub: float
    note: Optional[str] = None


class PartnerQuickCreate(BaseModel):
    partner_username: str
    partner_commission_percent: float = Field(default=10.0, ge=0, le=100)
    telegram_user_id: Optional[int] = None

    @field_validator("partner_username")
    @classmethod
    def _partner_username(cls, v: str) -> str:
        return validate_username(v)


class FixedRubPromoCreate(BaseModel):
    client_fixed_bonus_rub: float
    name: Optional[str] = None
    max_activations: int = 5
    min_order_rub: float = 0  # для скидки на обмен: мин. сумма заказа

    @field_validator("max_activations")
    @classmethod
    def _max_act(cls, v: int) -> int:
        if v < 1 or v > 1000:
            raise ValueError("max_activations must be between 1 and 1000")
        return v

    @field_validator("min_order_rub")
    @classmethod
    def _min_order(cls, v: float) -> float:
        if v < 0:
            raise ValueError("min_order_rub must be >= 0")
        return v


def _generate_campaign_code(prefix: str = "P") -> str:
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"{prefix}{suffix}"


def _referral_links(row) -> dict:
    kind = row.get("campaign_kind") or "generic"
    if kind == "fixed_rub":
        return {"ref_token": None, "referral_link": None, "referral_web_link": None}
    if kind == "exchange_discount":
        return {"ref_token": None, "referral_link": None, "referral_web_link": None}
    token = row.get("ref_token") or row["code"]
    return {
        "ref_token": token,
        "referral_link": telegram_deep_link(token),
        "referral_web_link": web_ref_link(token),
    }


def _promo_out(
    row,
    balance: float | None = None,
    partner_username: str | None = None,
    activations_used: int | None = None,
) -> dict:
    r = dict(row)
    out = {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "bonus_percent": float(r["bonus_percent"]),
        "ad_spend_rub": float(r["ad_spend_rub"]),
        "partner_commission_percent": float(r.get("partner_commission_percent") or 10),
        "campaign_kind": r.get("campaign_kind") or "generic",
        "client_fixed_bonus_rub": float(r["client_fixed_bonus_rub"])
        if r.get("client_fixed_bonus_rub") is not None
        else None,
        "min_order_rub": float(r.get("exchange_discount_min_order_rub") or 0),
        "max_activations": int(r.get("max_activations") or 5),
        "is_active": r["is_active"],
        "author_telegram_id": int(r["author_telegram_id"]) if r.get("author_telegram_id") else None,
        "author_video_id": r.get("author_video_id"),
        "issued_for": r.get("issued_for"),
        "arrivals": int(r["arrivals"]) if r.get("arrivals") is not None else None,
        "created_by": r.get("created_by"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
        **_referral_links(r),
    }
    if balance is not None:
        out["partner_balance_rub"] = round(balance, 2)
    if partner_username is not None:
        out["partner_username"] = partner_username
    if activations_used is not None:
        out["activations_used"] = activations_used
        out["activations_remaining"] = max(
            0, int(out["max_activations"]) - int(activations_used)
        )
        out["status"] = effective_promo_status(
            is_active=bool(r["is_active"]),
            activations_used=int(activations_used),
            max_activations=int(out["max_activations"]),
            campaign_kind=r.get("campaign_kind"),
        )
    issued_op_id = r.get("issued_by_operator_id")
    if issued_op_id is not None:
        out["issued_by_operator"] = {
            "id": issued_op_id,
            "username": r.get("issued_operator_username"),
            "display_name": r.get("issued_operator_display_name"),
        }
    return out


async def _count_promo_activations(conn, promo_code: str, campaign_kind: str) -> int:
    kind = (campaign_kind or "generic").lower()
    if kind in ("fixed_rub", "exchange_discount"):
        return int(
            await conn.fetchval(
                "SELECT COUNT(*)::int FROM promo_gift_redemptions WHERE promo_code = $1",
                promo_code,
            )
            or 0
        )
    return int(
        await conn.fetchval(
            "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
            promo_code,
        )
        or 0
    )


@router.get("/promos")
async def list_promos(admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pc.*, pa.username AS partner_username,
                   oa.username AS issued_operator_username,
                   oa.display_name AS issued_operator_display_name,
                   (
                     SELECT COUNT(*)::int FROM promo_attributions pat
                     WHERE pat.promo_code = pc.code
                   ) AS arrivals
            FROM promo_campaigns pc
            LEFT JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            LEFT JOIN operator_accounts oa ON oa.id = pc.issued_by_operator_id
            ORDER BY pc.created_at DESC LIMIT 200
            """
        )
        result = []
        for r in rows:
            bal = await get_campaign_balance(conn, r["id"])
            used = await _count_promo_activations(conn, r["code"], r.get("campaign_kind") or "")
            result.append(
                _promo_out(
                    r,
                    balance=bal,
                    partner_username=r.get("partner_username"),
                    activations_used=used,
                )
            )
    return {"promos": result}


@router.get("/promos/{promo_id}")
async def get_promo_detail(promo_id: int, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pc.*, pa.id AS partner_account_id, pa.username AS partner_username,
                   pa.display_name AS partner_display_name, pa.is_active AS partner_is_active,
                   oa.username AS issued_operator_username,
                   oa.display_name AS issued_operator_display_name
            FROM promo_campaigns pc
            LEFT JOIN partner_accounts pa ON pa.promo_campaign_id = pc.id
            LEFT JOIN operator_accounts oa ON oa.id = pc.issued_by_operator_id
            WHERE pc.id = $1
            """,
            promo_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Promo not found")

        balance = await get_campaign_balance(conn, promo_id)
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

        attracted = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1
            """,
            row["code"],
        )
        activations_used = await _count_promo_activations(
            conn, row["code"], row.get("campaign_kind") or ""
        )

        gift_entries = []
        if (row.get("campaign_kind") or "") in ("fixed_rub", "exchange_discount"):
            gift_rows = await conn.fetch(
                """
                SELECT pgr.user_id, pgr.amount_rub, pgr.redeemed_at,
                       bu.username, bu.first_name
                FROM promo_gift_redemptions pgr
                LEFT JOIN bot_users bu ON bu.user_id = pgr.user_id
                WHERE pgr.promo_code = $1
                ORDER BY pgr.redeemed_at DESC
                LIMIT 500
                """,
                row["code"],
            )
            gift_entries = [
                {
                    "user_id": g["user_id"],
                    "username": g["username"],
                    "first_name": g["first_name"],
                    "amount_rub": float(g["amount_rub"]),
                    "entered_at": g["redeemed_at"].isoformat() if g["redeemed_at"] else None,
                }
                for g in gift_rows
            ]
        discount_orders = await author_discount_order_stats(conn, row["code"])
        paid_stats = await conn.fetchrow(
            """
            SELECT COUNT(o.id)::int AS cnt, COALESCE(SUM(o.fiat_amount), 0)::float AS fiat
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
            WHERE o.status IN ('PAID', 'COMPLETED')
            """,
            row["code"],
        )

        users = await conn.fetch(
            """
            SELECT pa.user_id, pa.assigned_at, bu.username, bu.first_name
            FROM promo_attributions pa
            LEFT JOIN bot_users bu ON bu.user_id = pa.user_id
            WHERE pa.promo_code = $1
            ORDER BY pa.assigned_at DESC
            LIMIT 100
            """,
            row["code"],
        )

        orders = await conn.fetch(
            """
            SELECT o.order_id, o.status, o.direction, o.fiat_amount, o.created_at
            FROM orders o
            JOIN promo_attributions pa ON pa.user_id = o.user_id AND pa.promo_code = $1
            ORDER BY o.created_at DESC
            LIMIT 100
            """,
            row["code"],
        )

        ledger = await conn.fetch(
            """
            SELECT id, type, amount_rub, order_id, note, created_at
            FROM partner_ledger WHERE campaign_id = $1
            ORDER BY created_at DESC LIMIT 100
            """,
            promo_id,
        )

        total_accrued = round(float(accrued or 0), 2)
        referred_orders = await fetch_partner_referred_orders(conn, promo_code=row["code"])
        gross_by_campaign = profit_by_campaign_id(referred_orders)
        service_profit = partner_service_profit_metrics(
            gross=gross_by_campaign.get(promo_id, 0.0),
            accrued=total_accrued,
        )

    ad_spend = float(row["ad_spend_rub"])
    net = float(balance) - ad_spend

    return {
        "promo": _promo_out(
            row,
            balance=balance,
            partner_username=row.get("partner_username"),
            activations_used=activations_used,
        ),
        "partner": {
            "account_id": row.get("partner_account_id"),
            "username": row.get("partner_username"),
            "display_name": row.get("partner_display_name"),
            "is_active": row.get("partner_is_active"),
        }
        if row.get("partner_account_id")
        else None,
        "metrics": {
            "attracted_users": attracted or 0,
            "activations_used": activations_used,
            "activations_max": int(row.get("max_activations") or 5),
            "activations_remaining": max(
                0, int(row.get("max_activations") or 5) - activations_used
            ),
            "paid_orders_count": paid_stats["cnt"] if paid_stats else 0,
            "paid_fiat_sum": round(float(paid_stats["fiat"] if paid_stats else 0), 2),
            **discount_orders,
            "partner_balance_rub": round(balance, 2),
            "total_accrued": total_accrued,
            "total_paid_out": round(abs(float(paid_out or 0)), 2),
            "ad_spend_rub": ad_spend,
            "net_after_ad_spend": round(net, 2),
            **service_profit,
        },
        "users": [
            {
                "user_id": u["user_id"],
                "username": u["username"],
                "first_name": u["first_name"],
                "assigned_at": u["assigned_at"].isoformat() if u["assigned_at"] else None,
                "entered_at": u["assigned_at"].isoformat() if u["assigned_at"] else None,
            }
            for u in users
        ],
        "gift_entries": gift_entries,
        "orders": [
            {
                "order_id": o["order_id"],
                "status": o["status"],
                "direction": o["direction"],
                "fiat_amount": o["fiat_amount"],
                "created_at": o["created_at"].isoformat() if o["created_at"] else None,
            }
            for o in orders
        ],
        "ledger": [
            {
                "id": e["id"],
                "type": e["type"],
                "amount_rub": float(e["amount_rub"]),
                "order_id": e["order_id"],
                "note": e["note"],
                "created_at": e["created_at"].isoformat() if e["created_at"] else None,
            }
            for e in ledger
        ],
    }


@router.post("/promos/{promo_id}/payout", status_code=201)
async def record_payout(promo_id: int, body: PayoutBody, admin=Depends(get_current_admin)):
    if body.amount_rub <= 0:
        raise HTTPException(status_code=400, detail="amount_rub must be positive")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            campaign = await conn.fetchrow(
                "SELECT id, code FROM promo_campaigns WHERE id = $1 FOR UPDATE",
                promo_id,
            )
            if not campaign:
                raise HTTPException(status_code=404, detail="Promo not found")

            balance = await get_campaign_balance(conn, promo_id)
            available = await get_campaign_available_balance(conn, promo_id)
            if body.amount_rub > available + 0.01:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient available balance ({available:.2f} ₽)",
                )

            row = await conn.fetchrow(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, note, created_by_web_user_id)
                VALUES ($1, 'payout', $2, $3, $4)
                RETURNING *
                """,
                promo_id,
                -round(body.amount_rub, 2),
                body.note or f"Выплата партнёру {campaign['code']}",
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


@router.post("/partners/quick", status_code=201)
async def create_partner_quick(body: PartnerQuickCreate, admin=Depends(get_current_admin)):
    """Партнёр: только логин и % от прибыли; остальное генерируется."""
    pool = await get_pool()
    username = normalize_username(body.partner_username)
    password_plain = secrets.token_urlsafe(10)

    async with pool.acquire() as conn:
        dup = await conn.fetchval(
            "SELECT 1 FROM partner_accounts WHERE LOWER(username) = $1", username
        )
        if dup:
            raise HTTPException(status_code=400, detail="Partner username already in use")

        code = _generate_campaign_code("PR")
        for _ in range(10):
            if not await conn.fetchval("SELECT 1 FROM promo_campaigns WHERE code = $1", code):
                break
            code = _generate_campaign_code("PR")
        else:
            raise HTTPException(status_code=500, detail="Could not generate unique code")

        ref_token = generate_ref_token()
        name = f"Партнёр {username}"

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO promo_campaigns (
                    code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
                    ref_token, campaign_kind, client_fixed_bonus_rub, max_activations,
                    is_active, created_by, created_at, updated_at
                )
                VALUES ($1, $2, 0, 0, $3, $4, 'partner', NULL, 1000, TRUE, $5, now(), now())
                RETURNING *
                """,
                code,
                name,
                body.partner_commission_percent,
                ref_token,
                admin["id"],
            )
            await conn.execute(
                """
                INSERT INTO partner_accounts (
                    promo_campaign_id, username, password_hash, display_name, telegram_user_id
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                row["id"],
                username,
                hash_password(password_plain),
                name,
                body.telegram_user_id,
            )
            await refresh_settings()
            tier_overrides = partner_tier_overrides_for_rate(
                body.partner_commission_percent, partner_tier_global()
            )
            tier_sets = []
            tier_vals = [row["id"]]
            for col, val in tier_overrides.items():
                tier_sets.append(f"{col} = ${len(tier_vals) + 1}")
                tier_vals.append(val)
            if tier_sets:
                await conn.execute(
                    f"UPDATE promo_campaigns SET {', '.join(tier_sets)} WHERE id = $1",
                    *tier_vals,
                )

    out = _promo_out(row, balance=0.0, partner_username=username)
    out["partner_password"] = password_plain
    return out


@router.post("/promos/fixed-rub", status_code=201)
async def create_fixed_rub_promo(body: FixedRubPromoCreate, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await create_fixed_rub_campaign(
                    conn,
                    client_fixed_bonus_rub=body.client_fixed_bonus_rub,
                    max_activations=body.max_activations,
                    name=(body.name or "").strip() or None,
                    created_by_web_user_id=admin["id"],
                    code_prefix="B",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

    return _promo_out(row, balance=0.0, partner_username=None)


@router.post("/promos/exchange-discount", status_code=201)
async def create_exchange_discount_promo(
    body: FixedRubPromoCreate, admin=Depends(get_current_admin)
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await create_exchange_discount_campaign(
                    conn,
                    client_fixed_bonus_rub=body.client_fixed_bonus_rub,
                    max_activations=body.max_activations,
                    name=(body.name or "").strip() or None,
                    created_by_web_user_id=admin["id"],
                    min_order_rub=body.min_order_rub,
                    code_prefix="D",
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

    return _promo_out(row, balance=0.0, partner_username=None)


@router.post("/promos", status_code=201)
async def create_promo(body: PromoCreate, admin=Depends(get_current_admin)):
    if body.partner_username and not body.partner_password:
        raise HTTPException(
            status_code=400, detail="partner_password required when partner_username is set"
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM promo_campaigns WHERE code = $1", body.code
        )
        if existing:
            raise HTTPException(status_code=400, detail="Promo code already exists")

        if body.partner_username:
            dup = await conn.fetchval(
                "SELECT 1 FROM partner_accounts WHERE LOWER(username) = $1",
                normalize_username(str(body.partner_username)),
            )
            if dup:
                raise HTTPException(status_code=400, detail="Partner username already in use")

        ref_token = generate_ref_token()
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO promo_campaigns (
                    code, name, bonus_percent, ad_spend_rub, partner_commission_percent,
                    ref_token, is_active, created_by, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7, now(), now())
                RETURNING *
                """,
                body.code,
                body.name,
                body.bonus_percent,
                body.ad_spend_rub,
                body.partner_commission_percent,
                ref_token,
                admin["id"],
            )

            partner_username = None
            if body.partner_username and body.partner_password:
                await conn.execute(
                    """
                    INSERT INTO partner_accounts (promo_campaign_id, username, password_hash, display_name)
                    VALUES ($1, $2, $3, $4)
                    """,
                    row["id"],
                    normalize_username(str(body.partner_username)),
                    hash_password(body.partner_password),
                    body.partner_display_name or body.name,
                )
                partner_username = normalize_username(str(body.partner_username))

    return _promo_out(row, balance=0.0, partner_username=partner_username)


@router.patch("/promos/{promo_id}")
async def update_promo(promo_id: int, body: PromoUpdate, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM promo_campaigns WHERE id = $1", promo_id)
        if not row:
            raise HTTPException(status_code=404, detail="Promo not found")

        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.bonus_percent is not None:
            updates["bonus_percent"] = body.bonus_percent
        if body.ad_spend_rub is not None:
            updates["ad_spend_rub"] = body.ad_spend_rub
        if body.partner_commission_percent is not None:
            updates["partner_commission_percent"] = body.partner_commission_percent
        if body.is_active is not None:
            updates["is_active"] = body.is_active
        if body.max_activations is not None:
            if body.max_activations < 1 or body.max_activations > 1000:
                raise HTTPException(status_code=400, detail="max_activations must be 1–1000")
            updates["max_activations"] = body.max_activations

        if updates:
            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
            values = list(updates.values())
            row = await conn.fetchrow(
                f"UPDATE promo_campaigns SET {set_clauses}, updated_at = now() WHERE id = $1 RETURNING *",
                promo_id,
                *values,
            )

        pa = await conn.fetchrow(
            "SELECT * FROM partner_accounts WHERE promo_campaign_id = $1", promo_id
        )

        if body.partner_username or body.partner_password or body.partner_display_name is not None:
            if not pa and not (body.partner_username and body.partner_password):
                raise HTTPException(
                    status_code=400,
                    detail="Set partner_username and partner_password to create partner account",
                )
            if body.partner_username and pa:
                dup = await conn.fetchval(
                    """
                    SELECT 1 FROM partner_accounts
                    WHERE LOWER(username) = $1 AND promo_campaign_id != $2
                    """,
                    normalize_username(str(body.partner_username)),
                    promo_id,
                )
                if dup:
                    raise HTTPException(status_code=400, detail="Partner username already in use")

            if not pa:
                await conn.execute(
                    """
                    INSERT INTO partner_accounts (promo_campaign_id, username, password_hash, display_name)
                    VALUES ($1, $2, $3, $4)
                    """,
                    promo_id,
                    normalize_username(str(body.partner_username)),
                    hash_password(body.partner_password),
                    body.partner_display_name or row["name"],
                )
            else:
                pa_updates = []
                pa_vals = []
                if body.partner_username is not None:
                    pa_updates.append(f"username = ${len(pa_vals)+2}")
                    pa_vals.append(normalize_username(str(body.partner_username)))
                if body.partner_password:
                    pa_updates.append(f"password_hash = ${len(pa_vals)+2}")
                    pa_vals.append(hash_password(body.partner_password))
                if body.partner_display_name is not None:
                    pa_updates.append(f"display_name = ${len(pa_vals)+2}")
                    pa_vals.append(body.partner_display_name)
                if body.partner_is_active is not None:
                    pa_updates.append(f"is_active = ${len(pa_vals)+2}")
                    pa_vals.append(body.partner_is_active)
                if pa_updates:
                    await conn.execute(
                        f"UPDATE partner_accounts SET {', '.join(pa_updates)} WHERE promo_campaign_id = $1",
                        promo_id,
                        *pa_vals,
                    )

        partner_row = await conn.fetchrow(
            "SELECT username FROM partner_accounts WHERE promo_campaign_id = $1", promo_id
        )
        balance = await get_campaign_balance(conn, promo_id)

    return _promo_out(
        row,
        balance=balance,
        partner_username=partner_row["username"] if partner_row else None,
    )


@router.delete("/promos/{promo_id}", status_code=204)
async def delete_promo(promo_id: int, admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        has_attr = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM promo_attributions pa
                JOIN promo_campaigns pc ON pc.code = pa.promo_code
                WHERE pc.id = $1
            )
            """,
            promo_id,
        )
        if has_attr:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: promo has user attributions. Deactivate it instead.",
            )
        result = await conn.execute("DELETE FROM promo_campaigns WHERE id = $1", promo_id)
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Promo not found")

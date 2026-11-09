import logging
import json
import asyncpg
from typing import Optional, List
from datetime import datetime, timedelta, date, timezone

logger = logging.getLogger("db")

DB_POOL: Optional[asyncpg.Pool] = None


# ============================================================
# INIT
# ============================================================

async def init_db(dsn: str):
    global DB_POOL
    from services import config_rates

    DB_POOL = await asyncpg.create_pool(
        dsn,
        min_size=config_rates.DB_POOL_MIN,
        max_size=config_rates.DB_POOL_MAX,
    )


async def get_pool() -> asyncpg.Pool:
    if DB_POOL is None:
        raise RuntimeError("DB_POOL не инициализирован. Вызови init_db() при старте.")
    return DB_POOL

# ============================================================
# ORDERS — CREATE
# ============================================================
async def create_order(
    *,
    order_id: str,
    user_id: int,
    crypto: str,
    direction: str,
    crypto_amount: float,
    fiat_amount: float,
    rate: float,
    requisites: str,
    status: str = "CREATED",
    ttl_seconds: int = 1200,
    merchant_order_id: str | None = None,
    sub_token: str | None = None,
    expires_at_override=None,
    economics_snapshot: dict | None = None,
):
    """
    merchant_order_id = uuid_system из ответа мерча.
    expires_at_override = dateEnd от мерча (datetime), если есть — иначе expires_at = now() + ttl_seconds.
    ttl_seconds по умолчанию 20 мин (1200).
    """
    query = """
    INSERT INTO orders (
        order_id,
        user_id,
        crypto,
        direction,
        crypto_amount,
        fiat_amount,
        rate,
        requisites,
        status,
        created_at,
        expires_at,
        updated_at,
        merchant_order_id,
        order_source,
        sub_token,
        economics_snapshot
    )
    VALUES (
        $1,$2,$3,$4,$5,$6,$7,$8,$9,
        now(),
        COALESCE($10::timestamptz, now() + ($11 * interval '1 second')),
        now(),
        $12,'bot',$13,$14::jsonb
    )
"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            order_id,
            user_id,
            crypto,
            direction,
            crypto_amount,
            fiat_amount,
            rate,
            requisites,
            status,
            expires_at_override,
            ttl_seconds,
            merchant_order_id,
            sub_token,
            json.dumps(economics_snapshot) if economics_snapshot else None,
        )


async def create_order_with_promo(
    *,
    order_id: str,
    user_id: int,
    crypto: str,
    direction: str,
    crypto_amount: float,
    fiat_amount: float,
    rate: float,
    requisites: str,
    status: str = "CREATED",
    ttl_seconds: int = 1200,
    merchant_order_id: str | None = None,
    sub_token: str | None = None,
    expires_at_override=None,
    economics_snapshot: dict | None = None,
) -> dict:
    """
    Создаёт заявку; если у пользователя есть неиспользованный промо-бонус —
    резервирует его и увеличивает выплату клиенту (крипта при BUY, рубли при SELL).
    Сумма оплаты клиентом (fiat при BUY, crypto при SELL) не меняется.
    """
    from decimal import Decimal

    from services.promo_bonus import apply_fixed_rub_bonus

    query = """
    INSERT INTO orders (
        order_id,
        user_id,
        crypto,
        direction,
        crypto_amount,
        fiat_amount,
        rate,
        requisites,
        status,
        created_at,
        expires_at,
        updated_at,
        merchant_order_id,
        sub_token,
        promo_code,
        promo_bonus_percent,
        economics_snapshot,
        order_source
    )
    VALUES (
        $1,$2,$3,$4,$5,$6,$7,$8,$9,
        now(),
        COALESCE($10::timestamptz, now() + ($11 * interval '1 second')),
        now(),
        $12,$13,$14,$15,$16::jsonb,'bot'
    )
"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            promo_row = await conn.fetchrow(
                """
                INSERT INTO promo_bonus_usages (user_id, order_id, promo_code, bonus_percent, bonus_fixed_rub)
                SELECT pa.user_id, $2, pa.promo_code, 0, pc.client_fixed_bonus_rub
                FROM promo_attributions pa
                JOIN promo_campaigns pc ON pc.code = pa.promo_code AND pc.is_active = TRUE
                WHERE pa.user_id = $1
                  AND pc.client_fixed_bonus_rub IS NOT NULL
                  AND pc.client_fixed_bonus_rub > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM promo_bonus_usages pbu WHERE pbu.user_id = pa.user_id
                  )
                ON CONFLICT (user_id) DO NOTHING
                RETURNING promo_code, bonus_fixed_rub
                """,
                user_id,
                order_id,
            )

            final_crypto = Decimal(str(crypto_amount))
            final_fiat = Decimal(str(fiat_amount))
            promo_code = None
            promo_bonus_percent = None
            promo_bonus_fixed_rub = None

            if promo_row and promo_row["bonus_fixed_rub"]:
                promo_code = promo_row["promo_code"]
                promo_bonus_fixed_rub = float(promo_row["bonus_fixed_rub"])
                crypto_base = crypto.split("_")[0].lower()
                final_crypto, final_fiat = apply_fixed_rub_bonus(
                    direction,
                    final_crypto,
                    final_fiat,
                    Decimal(str(promo_row["bonus_fixed_rub"])),
                    crypto_base,
                    Decimal(str(rate)),
                )

            if economics_snapshot is None:
                from services.economics_snapshot import build_economics_snapshot

                economics_snapshot = build_economics_snapshot(
                    direction,
                    crypto,
                    float(final_fiat),
                    float(final_crypto),
                    float(rate),
                )

            await conn.execute(
                query,
                order_id,
                user_id,
                crypto,
                direction,
                float(final_crypto),
                float(final_fiat),
                rate,
                requisites,
                status,
                expires_at_override,
                ttl_seconds,
                merchant_order_id,
                sub_token,
                promo_code,
                promo_bonus_percent,
                json.dumps(economics_snapshot) if economics_snapshot else None,
            )

    return {
        "promo_applied": promo_row is not None,
        "promo_code": promo_code,
        "promo_bonus_percent": promo_bonus_percent,
        "promo_bonus_fixed_rub": promo_bonus_fixed_rub,
        "crypto_amount": float(final_crypto),
        "fiat_amount": float(final_fiat),
    }


# ============================================================
# ORDERS — UPDATE STATUS
# ============================================================

async def release_promo_bonus_for_order(
    order_id: str, *, conn=None, only_if_status: str | None = "CREATED"
) -> bool:
    """
    Освобождает слот промо-бонуса только для заявок, не ушедших дальше CREATED.
    Иначе отмена после «Я оплатил» позволяла повторно резервировать бонус.
    """
    query = """
        DELETE FROM promo_bonus_usages pbu
        USING orders o
        WHERE pbu.order_id = o.order_id
          AND o.order_id = $1
          AND o.status = $2
        RETURNING pbu.user_id
    """
    status_filter = only_if_status or "CREATED"
    if conn is not None:
        row = await conn.fetchrow(query, order_id, status_filter)
        return row is not None

    pool = await get_pool()
    async with pool.acquire() as acquired:
        row = await acquired.fetchrow(query, order_id, status_filter)
        return row is not None


async def _apply_paid_side_effects_in_tx(conn, order_id: str) -> None:
    from services.order_financial import apply_paid_financial_effects
    from services.partner_commission import accrue_partner_commission
    from services.user_referral_commission import accrue_user_referral_commission
    from services.user_cashback_commission import accrue_user_cashback
    from services.user_cashback_db import credit_manual_buy_overpay_for_order
    from services.raffle_accrual import accrue_raffle_tickets

    await apply_paid_financial_effects(order_id, conn=conn)
    await accrue_partner_commission(order_id, conn=conn)
    await accrue_user_referral_commission(order_id, conn=conn)
    await accrue_user_cashback(order_id, conn=conn)
    await credit_manual_buy_overpay_for_order(order_id, conn=conn)
    await accrue_raffle_tickets(order_id, conn=conn)
    try:
        uid = await conn.fetchval(
            "SELECT user_id FROM orders WHERE order_id = $1",
            order_id,
        )
        if uid:
            await conn.execute(
                """
                UPDATE bot_users
                SET account_review_status = 'approved',
                    account_reviewed_at = COALESCE(account_reviewed_at, now()),
                    account_review_reason = COALESCE(account_review_reason, 'auto_paid')
                WHERE user_id = $1
                  AND COALESCE(account_review_status, 'none') <> 'approved'
                """,
                int(uid),
            )
    except Exception as e:
        import logging

        logging.getLogger("db").warning(
            "auto account_review approve failed order=%s: %s", order_id, e
        )


async def _compute_buy_network_fee_rub(order: dict) -> float:
    from services.crypto_network_fee import buy_network_fee_rub, network_fee_applies

    crypto = str(order.get("crypto") or "")
    if not network_fee_applies(crypto):
        return 0.0
    base = crypto.split("_")[0].lower()
    rate = float(order.get("rate") or 0)
    if base == "usdt" and rate > 0:
        usdt_rub = rate
    else:
        from services.rates_api import get_market_price

        price, _, blocked = await get_market_price("usdt")
        usdt_rub = float(price) if not blocked and price else (rate if rate > 0 else 90.0)
    return round(buy_network_fee_rub(crypto, usdt_rub=usdt_rub), 2)


async def transition_buy_payout_to_paid_in_tx(
    conn,
    order_id: str,
    *,
    payout_tx_hash: str,
    payout_confirmed_by: str,
    operator_id: int | None = None,
) -> tuple[bool, str | None, dict | None]:
    """
    COMPLETED → PAID + payout fields + финансовые начисления в одной транзакции.
    Returns (ok, error_code, order_dict).
    """
    from services.buy_payout_validate import validate_buy_payout_crypto
    from services.order_transitions import allowed_status_transition

    oid = order_id.strip()
    row = await conn.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
        oid,
    )
    if not row:
        return False, "not_found", None
    order = dict(row)
    direction = (order.get("direction") or "").lower()
    status = str(order.get("status") or "").upper()

    if direction != "buy":
        return False, "not_buy", order
    if status == "PAID":
        existing = str(order.get("payout_tx_hash") or "").strip()
        if existing and existing.lower() == payout_tx_hash.lower():
            return True, None, order
        return False, "already_paid", order
    if status != "COMPLETED":
        return False, "wrong_status", order

    ok_amt, amt_reason = validate_buy_payout_crypto(order)
    if not ok_amt:
        return False, amt_reason or "amount_mismatch", order

    if not allowed_status_transition(status, "PAID", direction=direction):
        return False, "transition_rejected", order

    dup = await conn.fetchrow(
        """
        SELECT order_id FROM orders
        WHERE payout_tx_hash = $1 AND order_id <> $2
        LIMIT 1
        """,
        payout_tx_hash,
        oid,
    )
    if dup:
        return False, f"duplicate_tx_hash:{dup['order_id']}", order

    network_fee = await _compute_buy_network_fee_rub(order)
    await conn.execute(
        """
        UPDATE orders
        SET status = 'PAID',
            operator_completed_at = COALESCE(operator_completed_at, now()),
            payout_tx_hash = $1,
            payout_confirmed_at = now(),
            payout_confirmed_by = $2,
            operator_id = COALESCE(operator_id, $3),
            network_fee_rub = $5,
            updated_at = now()
        WHERE order_id = $4
        """,
        payout_tx_hash,
        payout_confirmed_by,
        operator_id,
        oid,
        network_fee,
    )
    await _apply_paid_side_effects_in_tx(conn, oid)
    refreshed = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
    return True, None, dict(refreshed) if refreshed else order


async def transition_manual_buy_payout_to_paid_in_tx(
    conn,
    order_id: str,
    *,
    payout_tx_hash: str,
    payout_confirmed_by: str,
    operator_id: int | None = None,
) -> tuple[bool, str | None, dict | None]:
    """
    OPERATOR_PENDING → PAID + payout fields + финансовые начисления (ручная BUY).
    Returns (ok, error_code, order_dict).
    """
    from services.order_transitions import allowed_status_transition

    oid = order_id.strip()
    row = await conn.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
        oid,
    )
    if not row:
        return False, "not_found", None
    order = dict(row)
    direction = (order.get("direction") or "").lower()
    status = str(order.get("status") or "").upper()

    if direction != "buy":
        return False, "not_buy", order
    if status == "PAID":
        existing = str(order.get("payout_tx_hash") or "").strip()
        if existing and existing.lower() == payout_tx_hash.lower():
            return True, None, order
        return False, "already_paid", order
    if status != "OPERATOR_PENDING":
        return False, "wrong_status", order

    if not allowed_status_transition(status, "PAID", direction=direction):
        return False, "transition_rejected", order

    dup = await conn.fetchrow(
        """
        SELECT order_id FROM orders
        WHERE payout_tx_hash = $1 AND order_id <> $2
        LIMIT 1
        """,
        payout_tx_hash,
        oid,
    )
    if dup:
        return False, f"duplicate_tx_hash:{dup['order_id']}", order

    network_fee = await _compute_buy_network_fee_rub(order)
    await conn.execute(
        """
        UPDATE orders
        SET status = 'PAID',
            operator_completed_at = COALESCE(operator_completed_at, now()),
            payout_tx_hash = $1,
            payout_confirmed_at = now(),
            payout_confirmed_by = $2,
            operator_id = COALESCE(operator_id, $3),
            network_fee_rub = $5,
            updated_at = now()
        WHERE order_id = $4
        """,
        payout_tx_hash,
        payout_confirmed_by,
        operator_id,
        oid,
        network_fee,
    )
    await _apply_paid_side_effects_in_tx(conn, oid)
    refreshed = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
    return True, None, dict(refreshed) if refreshed else order


async def transition_awaiting_check_buy_payout_to_paid_in_tx(
    conn,
    order_id: str,
    *,
    payout_tx_hash: str,
    payout_confirmed_by: str,
    operator_id: int | None = None,
) -> tuple[bool, str | None, dict | None]:
    """
    AWAITING_CHECK → PAID + payout fields + финансовые начисления.

    Админский override: общая машина статусов BUY AWAITING_CHECK → PAID не
    открывает (чек должен уйти в PENDING). Этот путь — отдельная кнопка
    «крипта уже ушла».
    Returns (ok, error_code, order_dict).
    """
    from services.buy_payout_validate import validate_buy_payout_crypto

    oid = order_id.strip()
    row = await conn.fetchrow(
        "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
        oid,
    )
    if not row:
        return False, "not_found", None
    order = dict(row)
    direction = (order.get("direction") or "").lower()
    status = str(order.get("status") or "").upper()

    if direction != "buy":
        return False, "not_buy", order
    if status == "PAID":
        existing = str(order.get("payout_tx_hash") or "").strip()
        if existing and existing.lower() == payout_tx_hash.lower():
            return True, None, order
        return False, "already_paid", order
    if status != "AWAITING_CHECK":
        return False, "wrong_status", order

    ok_amt, amt_reason = validate_buy_payout_crypto(order)
    if not ok_amt:
        return False, amt_reason or "amount_mismatch", order

    dup = await conn.fetchrow(
        """
        SELECT order_id FROM orders
        WHERE payout_tx_hash = $1 AND order_id <> $2
        LIMIT 1
        """,
        payout_tx_hash,
        oid,
    )
    if dup:
        return False, f"duplicate_tx_hash:{dup['order_id']}", order

    network_fee = await _compute_buy_network_fee_rub(order)
    await conn.execute(
        """
        UPDATE orders
        SET status = 'PAID',
            operator_completed_at = COALESCE(operator_completed_at, now()),
            payout_tx_hash = $1,
            payout_confirmed_at = now(),
            payout_confirmed_by = $2,
            operator_id = COALESCE(operator_id, $3),
            network_fee_rub = $5,
            updated_at = now()
        WHERE order_id = $4
        """,
        payout_tx_hash,
        payout_confirmed_by,
        operator_id,
        oid,
        network_fee,
    )
    await _apply_paid_side_effects_in_tx(conn, oid)
    refreshed = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
    return True, None, dict(refreshed) if refreshed else order


async def update_order_status(
    order_id: str,
    status: str,
    *,
    cancel_reason: str | None = None,
    canceled_by: int | None = None,
) -> bool:
    from services.order_transitions import allowed_status_transition

    query = """
        UPDATE orders
        SET status = $1::varchar,
            operator_completed_at = CASE
                WHEN $1::varchar IN ('COMPLETED', 'PAID')
                    THEN COALESCE(operator_completed_at, now())
                ELSE operator_completed_at
            END,
            updated_at = now()
        WHERE order_id = $2
    """
    execute_args: tuple = (status, order_id)
    if cancel_reason is not None or canceled_by is not None:
        query = """
            UPDATE orders
            SET status = $1::varchar,
                operator_completed_at = CASE
                    WHEN $1::varchar IN ('COMPLETED', 'PAID')
                        THEN COALESCE(operator_completed_at, now())
                    ELSE operator_completed_at
                END,
                cancel_reason = COALESCE($3, cancel_reason),
                canceled_by = COALESCE($4, canceled_by),
                updated_at = now()
            WHERE order_id = $2
        """
        execute_args = (status, order_id, cancel_reason, canceled_by)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            prev = await conn.fetchrow(
                "SELECT status, direction, payin_requisite_id FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            if not prev:
                return False
            prev_status = prev["status"]
            direction = prev.get("direction")
            payin_rail = prev.get("payin_requisite_id") is not None
            if not allowed_status_transition(
                prev_status, status, direction=direction, payin_rail=payin_rail
            ):
                logger.warning(
                    "Rejected status transition %s -> %s for order %s",
                    prev_status,
                    status,
                    order_id,
                )
                return False
            if prev_status == status:
                return True

            # Центральная защита: BUY → PAID через generic-путь (admin PATCH,
            # ручная выплата оператора, DISPUTE) обязан пройти проверку крипты,
            # иначе можно отправить больше крипты, чем покрывает оплата.
            if status == "PAID" and (direction or "").lower() == "buy":
                full_row = await conn.fetchrow(
                    "SELECT * FROM orders WHERE order_id = $1", order_id
                )
                from services.buy_payout_validate import validate_buy_payout_crypto

                ok_amt, amt_reason = validate_buy_payout_crypto(dict(full_row))
                if not ok_amt:
                    logger.error(
                        "BUY PAID blocked order=%s reason=%s", order_id, amt_reason
                    )
                    return False

            # Промо-слот смотрит на текущий статус (CREATED). Снимаем до UPDATE.
            if status in ("CANCELED", "EXPIRED"):
                try:
                    await release_promo_bonus_for_order(order_id, conn=conn)
                except Exception as e:
                    logger.warning("promo bonus release failed for %s: %s", order_id, e)

            await conn.execute(query, *execute_args)

            if status in ("CANCELED", "EXPIRED"):
                try:
                    from services.order_financial import (
                        apply_cancel_financial_effects,
                        reverse_paid_accruals_for_order,
                    )

                    await apply_cancel_financial_effects(order_id, conn=conn)
                    if prev_status in ("COMPLETED", "PAID"):
                        await reverse_paid_accruals_for_order(order_id, conn=conn)
                except Exception as e:
                    logger.warning(
                        "cancel financial effects failed for %s: %s", order_id, e
                    )
                try:
                    from services.payin_requisite_rail import release_payin_allocation

                    await release_payin_allocation(conn, order_id)
                except Exception as e:
                    logger.warning(
                        "payin allocation release failed for %s: %s", order_id, e
                    )
            if status == "PAID":
                await _apply_paid_side_effects_in_tx(conn, order_id)
            if status == "COMPLETED" and prev_status != "COMPLETED":
                try:
                    from services.payin_requisite_rail import settle_payin_allocation

                    await settle_payin_allocation(conn, order_id)
                except Exception as e:
                    logger.warning(
                        "payin allocation settle failed for %s: %s", order_id, e
                    )
                try:
                    from services.buy_order_service import handle_order_paid_side_effects
                    from services.bot_context import get_bot

                    bot = get_bot()
                    await handle_order_paid_side_effects(order_id, bot)
                except Exception as e:
                    logger.warning("split next part failed for %s: %s", order_id, e)

    # После коммита транзакции: отмена связанных частей сплита.
    # (Раньше этот блок был недостижим из-за `return True` внутри транзакции.)
    if status in ("CANCELED", "EXPIRED"):
        try:
            from services.order_financial import apply_cancel_group_if_needed
            await apply_cancel_group_if_needed(order_id)
        except Exception as e:
            logger.warning("cancel order group failed for %s: %s", order_id, e)
    return True


async def get_active_order_by_user(user_id: int):
    """Заявка, блокирующая создание новой: до выплаты крипты включая COMPLETED."""
    query = """
        SELECT *
        FROM orders
        WHERE user_id = $1
          AND status IN (
              'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
          )
        ORDER BY created_at DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, user_id)


async def count_orders_by_user_in_last_minutes(user_id: int, minutes: int = 15) -> int:
    """Количество заявок за последние minutes минут, не доведённых до сделки (без PAID/COMPLETED). Для антиспама: оплаченные не лимитируют."""
    query = """
        SELECT COUNT(*)::int
        FROM orders
        WHERE user_id = $1
          AND created_at > now() - ($2 * interval '1 minute')
          AND status NOT IN ('PAID', 'COMPLETED')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id, minutes)
        return row["count"] if row else 0


# ============================================================
# ORDERS — GET ONE
# ============================================================

async def get_order(order_id: str):
    query = """
        SELECT *
        FROM orders
        WHERE order_id = $1
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, order_id)


async def get_order_by_merchant_ref(ref: str):
    """Поиск по Payfast uuid (merchant_order_id) или нашему order_id."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    query = """
        SELECT *
        FROM orders
        WHERE merchant_order_id = $1 OR order_id = $1
        ORDER BY created_at DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, ref)


async def find_order_for_stat(ref: str):
    """Заявка по Payfast uuid (колонка или snapshot), либо по нашему order_id."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    query = """
        SELECT *
        FROM orders
        WHERE merchant_order_id = $1
           OR order_id = $1
           OR payment_snapshot->>'merchant_uuid' = $1
           OR payment_snapshot->>'uuid_system' = $1
        ORDER BY created_at DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, ref)


async def get_external_exchanger_ops_stats(exchanger_id: int) -> dict:
    """Статистика внештатника для ops-уведомлений."""
    query = """
        SELECT
            COUNT(*)::int AS confirmed_count,
            COALESCE(SUM(client_pays_rub), 0)::double precision AS total_turnover_rub,
            MAX(created_at) AS last_confirmed_at
        FROM external_deals
        WHERE exchanger_id = $1 AND status = 'confirmed'
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, exchanger_id)
        if not row:
            return {
                "confirmed_count": 0,
                "total_turnover_rub": 0.0,
                "last_confirmed_at": None,
            }
        return dict(row)


async def get_external_deal_by_merchant_ref(ref: str):
    """Сделка кабинета по Payfast uuid, EXT-{id} или merchant_order_id."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    deal_id = None
    if ref.upper().startswith("EXT-"):
        try:
            deal_id = int(ref.split("-", 1)[1])
        except ValueError:
            deal_id = None
    query = """
        SELECT d.*, e.name AS exchanger_name, ea.username AS account_username,
               d.exchanger_id
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        LEFT JOIN external_exchanger_accounts ea ON ea.external_exchanger_id = d.exchanger_id
        WHERE ($1::int IS NOT NULL AND d.id = $1)
           OR d.merchant_order_id = $2
           OR d.payment_snapshot->>'merchant_uuid' = $2
           OR ('EXT-' || d.id::text) = $2
        ORDER BY d.created_at DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, deal_id, ref)


async def get_external_client_stat(exchanger_id: int, fingerprint: str | None):
    """Последняя сводка магазина по fingerprint (кэш HMAC POST /clients/stat)."""
    fp = str(fingerprint or "").strip()
    if not fp or not exchanger_id:
        return None
    query = """
        SELECT payload, updated_at
        FROM external_client_stats
        WHERE exchanger_id = $1 AND fingerprint = $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, int(exchanger_id), fp)


async def get_external_deals_for_payfast_reconcile(min_age_sec: int = 90):
    query = """
        SELECT d.id
        FROM external_deals d
        JOIN external_exchangers e ON e.id = d.exchanger_id
        WHERE d.status = 'pending'
          AND d.receipt_submitted_at IS NOT NULL
          AND d.receipt_submitted_at < now() - make_interval(secs => $1)
          AND e.is_trusted_client = TRUE
          AND e.auto_credit_on_payfast = TRUE
          AND COALESCE(d.required_receipt_type, 2) != 3
        ORDER BY d.receipt_submitted_at ASC
        LIMIT 50
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, min_age_sec)


async def get_active_orders(limit: int = 50) -> List[asyncpg.Record]:
    """Заявки со статусами CREATED, PENDING, AWAITING_CHECK, COMPLETED (ещё не закрыты)."""
    query = """
        SELECT *
        FROM orders
        WHERE status IN ('CREATED', 'PENDING', 'AWAITING_CHECK', 'COMPLETED')
        ORDER BY created_at DESC
        LIMIT $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, limit)


async def get_recent_orders(limit: int = 30) -> List[asyncpg.Record]:
    """Последние N заявок по дате создания (любой статус)."""
    query = """
        SELECT *
        FROM orders
        ORDER BY created_at DESC
        LIMIT $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, limit)


async def get_paid_orders_for_stats(days: int = 1) -> List[asyncpg.Record]:
    """Заявки со статусом PAID за последние days дней (для /stats). direction нужен для разделения BUY/SELL."""
    query = """
        SELECT crypto, crypto_amount, fiat_amount, rate, created_at, direction,
               cashback_applied_rub, card_fee_pct, economics_snapshot
        FROM orders
        WHERE status = 'PAID'
          AND created_at >= now() - ($1 * interval '1 day')
        ORDER BY created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, days)


async def get_paid_orders_for_date(date_obj: date) -> List[asyncpg.Record]:
    """Заявки со статусом PAID за конкретный день по created_at. date_obj — datetime.date."""
    query = """
        SELECT crypto, crypto_amount, fiat_amount, rate, created_at, direction,
               cashback_applied_rub, card_fee_pct, economics_snapshot
        FROM orders
        WHERE status = 'PAID'
          AND created_at::date = $1
        ORDER BY created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, date_obj)


# ============================================================
# ORDERS — EXPIRED (КЛЮЧЕВАЯ ФУНКЦИЯ)
# ============================================================

async def extend_order_expires_at(order_id: str, until: datetime) -> None:
    """Продлить таймер заявки (например, на время апелляции Payfast)."""
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE orders
            SET expires_at = GREATEST(expires_at, $2),
                updated_at = now()
            WHERE order_id = $1
            """,
            order_id,
            until,
        )


async def get_expired_orders(limit: int = 100) -> List[asyncpg.Record]:
    """
    Заявки для истечения (с grace после expires_at для payin-flow).
    OPERATOR_PENDING — по expires_at без grace (обычно 24ч).

    Дедлайн — максимум из expires_at и окна мерчанта: при создании payin-заявки
    expires_at = merchant_expires_at минус recovery-буфер, поэтому GREATEST даёт
    окно мерчанта. Позже поднять expires_at выше окна может только явное
    продление (апелляция Payfast, ожидание чека) — и оно должно действовать.
    """
    from services import config_rates

    grace = max(0, int(getattr(config_rates, "EXPIRE_GRACE_SECONDS", 0) or 0))

    query = """
        SELECT order_id, user_id
        FROM orders
        WHERE (
            status IN ('CREATED', 'AWAITING_CHECK', 'PENDING')
            AND GREATEST(
                expires_at,
                CASE
                    WHEN COALESCE(payment_snapshot->>'merchant_expires_at', '')
                         ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                    THEN (payment_snapshot->>'merchant_expires_at')::timestamptz
                END
            ) <= now() - ($2 * interval '1 second')
        )
        OR (
            status = 'OPERATOR_PENDING'
            AND expires_at <= now()
        )
        LIMIT $1
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, limit, grace)


async def user_has_active_order(conn, user_id: int, *, exclude_order_id: str | None = None) -> bool:
    """Есть ли незавершённая заявка (блокирует создание новой)."""
    if exclude_order_id:
        row = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE user_id = $1
              AND order_id != $2
              AND status IN (
                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
              )
            LIMIT 1
            """,
            user_id,
            exclude_order_id,
        )
    else:
        row = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE user_id = $1
              AND status IN (
                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
              )
            LIMIT 1
            """,
            user_id,
        )
    return row is not None


async def user_has_active_buy_order(
    conn, user_id: int, *, exclude_order_id: str | None = None
) -> bool:
    """Незавершённая BUY-заявка — блокирует новую покупку (продажа не мешает)."""
    if exclude_order_id:
        row = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE user_id = $1
              AND order_id != $2
              AND direction = 'buy'
              AND status IN (
                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
              )
            LIMIT 1
            """,
            user_id,
            exclude_order_id,
        )
    else:
        row = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE user_id = $1
              AND direction = 'buy'
              AND status IN (
                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING', 'COMPLETED'
              )
            LIMIT 1
            """,
            user_id,
        )
    return row is not None


# ============================================================
# ORDERS — BULK EXPIRE
# ============================================================

async def mark_orders_expired(order_ids: list[str]):
    """Истечение заявок с теми же финансовыми откатами, что и ручная отмена."""
    for oid in order_ids:
        try:
            await update_order_status(oid, "EXPIRED")
        except Exception as e:
            import logging
            logging.getLogger("db").warning("expire %s failed: %s", oid, e)


# ============================================================
# ORDERS — AWAITING CHECK (чек для мерча; нужны для вебхука и прикрепления чека)
# ============================================================

async def update_order_to_awaiting_check(order_id: str, required_receipt_type: int = 2) -> bool:
    from services.order_transitions import allowed_status_transition

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            prev = await conn.fetchrow(
                "SELECT status, direction FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            if not prev:
                return False
            prev_status = prev["status"]
            if not allowed_status_transition(
                prev_status, "AWAITING_CHECK", direction=prev.get("direction")
            ):
                import logging

                logging.getLogger("db").warning(
                    "Rejected AWAITING_CHECK transition from %s for order %s",
                    prev_status,
                    order_id,
                )
                return False
            # Клиенту нужно время прислать чек/видео. Продлеваем всегда: часть
            # вызывающих (appeals-листенер) своего продления не делает вовсе.
            await conn.execute(
                """
                UPDATE orders
                SET status = 'AWAITING_CHECK',
                    required_receipt_type = $1,
                    updated_at = now(),
                    payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb)
                        || jsonb_build_object(
                            'receipt_requested_at',
                            to_jsonb(to_char(timezone('UTC', now()), 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
                        ),
                    expires_at = GREATEST(expires_at, now() + interval '45 minutes')
                WHERE order_id = $2
                """,
                required_receipt_type,
                order_id,
            )
    return True


async def set_order_receipt_file(order_id: str, receipt_file: str) -> None:
    """Сохранить имя файла последнего чека/видео клиента (для просмотра в админке)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET receipt_file = $1, updated_at = now() WHERE order_id = $2",
            receipt_file,
            order_id,
        )


from services.payment_snapshot import parse_payment_snapshot as _parse_payment_snapshot  # noqa: E402


def _parse_snapshot_datetime(raw):
    """Парсит ISO или PostgreSQL now()::text (Python 3.10 не ест 'YYYY-MM-DD HH:MM:SS-05')."""
    import re
    from datetime import datetime, timezone

    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw).strip()
        if not s:
            return None
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        if re.search(r"[+-]\d{2}$", s):
            s = f"{s}:00"
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_receipt_ops_pending(order: dict) -> bool:
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return bool(snap.get("receipt_ops_pending"))


def get_receipt_requested_at(order: dict):
    """Время запроса чека у клиента (переход в AWAITING_CHECK), UTC."""
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return _parse_snapshot_datetime(snap.get("receipt_requested_at"))


def get_merchant_expires_at(order: dict):
    """Конец окна оплаты у мерчанта (Payfast dateEnd), UTC."""
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return _parse_snapshot_datetime(snap.get("merchant_expires_at"))


def get_receipt_recheck_requested_at(order: dict):
    """Когда мерчант/appeals запросили чек повторно (не первичное ожидание), UTC.

    Отличает «Payfast отклонил PDF, ждём видео» от обычного «клиент нажал
    оплатил и ещё не прислал чек»: первое нельзя истекать по таймеру оплаты.
    """
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return _parse_snapshot_datetime(snap.get("receipt_recheck_requested_at"))


def get_requisites_revealed_at(order: dict):
    """Когда клиент впервые открыл реквизиты (Mini App) или выдали bill."""
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return _parse_snapshot_datetime(snap.get("requisites_revealed_at"))


def get_receipt_timer_start_at(order: dict, *, submitted_at=None):
    """
    Старт таймера «PDF отправлен за N сек» для ops:
    от «Я оплатил» (receipt_requested_at), если интервал осмысленный.

    Если CREATED→AWAITING_CHECK случился в момент загрузки чека
    (requested≈submitted → «0 сек»), падаем на открытие реквизитов.
    """
    from datetime import datetime, timezone

    revealed = get_requisites_revealed_at(order)
    requested = get_receipt_requested_at(order)
    submitted = submitted_at or get_receipt_submitted_at(order)
    if submitted is None:
        submitted = datetime.now(tz=timezone.utc)
    if getattr(submitted, "tzinfo", None) is None:
        submitted = submitted.replace(tzinfo=timezone.utc)

    if requested is not None:
        try:
            req = requested
            if getattr(req, "tzinfo", None) is None:
                req = req.replace(tzinfo=timezone.utc)
            if (submitted - req).total_seconds() >= 3:
                return req
        except Exception:
            logger.debug("requisites timestamp compare failed", exc_info=True)
    return revealed or requested


def get_receipt_payment_window_start_at(order: dict):
    """Старт для риска «слишком быстро для живой оплаты»: открытие реквизитов."""
    return get_requisites_revealed_at(order) or get_receipt_requested_at(order)


def get_receipt_submitted_at(order: dict):
    """Время приёма чека от клиента (если сохранено в snapshot)."""
    snap = _parse_payment_snapshot(order.get("payment_snapshot"))
    return _parse_snapshot_datetime(snap.get("receipt_ops_submitted_at"))


async def merge_order_payment_snapshot(order_id: str, patch: dict) -> bool:
    """Слить patch в payment_snapshot заявки. Возвращает False если заявка не найдена."""
    import json

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payment_snapshot FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row:
            return False
        merged = _parse_payment_snapshot(row["payment_snapshot"])
        merged.update(patch)
        await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = $1::jsonb, updated_at = now()
            WHERE order_id = $2
            """,
            json.dumps(merged),
            order_id,
        )
    return True


async def clear_receipt_ops_pending(order_id: str) -> None:
    """Снять флаг ожидания ручной проверки (время отправки PDF не трогаем)."""
    await merge_order_payment_snapshot(
        order_id,
        {"receipt_ops_pending": False},
    )


def _naive_utc_timestamp(value):
    """asyncpg + timestamp without time zone: не смешивать naive и aware."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def find_matching_paid_buy_payout(order: dict):
    """PAID BUY того же клиента: тот же кошелёк и та же сумма крипты после этой заявки."""
    from services.stale_payin_hold import payout_identity_matches

    user_id = order.get("user_id")
    order_id = str(order.get("order_id") or "").strip()
    crypto = str(order.get("crypto") or "").strip()
    wallet = str(order.get("wallet_address") or order.get("requisites") or "").strip()
    created = _naive_utc_timestamp(order.get("created_at"))
    if not user_id or not order_id or not crypto or not wallet or created is None:
        return None

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM orders
            WHERE user_id = $1
              AND order_id <> $2
              AND direction = 'buy'
              AND status = 'PAID'
              AND lower(crypto) = lower($3)
              AND created_at >= $4::timestamp
              AND created_at <= $4::timestamp + interval '48 hours'
            ORDER BY created_at ASC
            """,
            int(user_id),
            order_id,
            crypto,
            created,
        )
    for row in rows:
        if payout_identity_matches(order, dict(row)):
            return dict(row)
    return None


async def find_open_payins_superseded_by_paid(paid_order: dict) -> list:
    """Открытые BUY, которые ручная PAID уже закрыла по факту выплаты."""
    from services.stale_payin_hold import SUPERSEDE_OPEN_STATUSES, payout_identity_matches

    user_id = paid_order.get("user_id")
    paid_id = str(paid_order.get("order_id") or "").strip()
    crypto = str(paid_order.get("crypto") or "").strip()
    created = _naive_utc_timestamp(paid_order.get("created_at"))
    if not user_id or not paid_id or not crypto:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM orders
            WHERE user_id = $1
              AND order_id <> $2
              AND direction = 'buy'
              AND status = ANY($3::varchar[])
              AND lower(crypto) = lower($4)
              AND ($5::timestamp IS NULL OR created_at <= $5::timestamp)
            ORDER BY created_at ASC
            """,
            int(user_id),
            paid_id,
            list(SUPERSEDE_OPEN_STATUSES),
            crypto,
            created,
        )
    matched = []
    for row in rows:
        if payout_identity_matches(dict(row), paid_order):
            matched.append(dict(row))
    return matched


async def find_completed_buys_possibly_superseded(limit: int = 40):
    """COMPLETED BUY старше 30 мин — если крипта уже в другой PAID, клиента всё ещё держит."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT *
            FROM orders
            WHERE direction = 'buy'
              AND status = 'COMPLETED'
              AND created_at < now() - interval '30 minutes'
            ORDER BY created_at ASC
            LIMIT $1
            """,
            limit,
        )



async def get_order_awaiting_check_by_user(user_id: int):
    query = """
        SELECT *
        FROM orders
        WHERE user_id = $1
          AND status = 'AWAITING_CHECK'
        ORDER BY created_at DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, user_id)


# ============================================================
# ORDERS — COMPLETED (для истории пользователя)
# ============================================================

async def get_completed_orders_count(user_id: int) -> int:
    """Количество заявок пользователя со статусом COMPLETED или PAID."""
    query = """
        SELECT COUNT(*)::int
        FROM orders
        WHERE user_id = $1
          AND status IN ('COMPLETED', 'PAID')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(query, user_id)
        return row or 0


async def get_buyer_ops_stats(user_id: int) -> dict:
    """Сделки для ops / автопропуска чека: PAID+COMPLETED, как /stat и payin rail."""
    query = """
        SELECT
            COUNT(*)::int AS paid_count,
            MAX(created_at) AS last_paid_at,
            COALESCE(SUM(fiat_amount), 0)::double precision AS total_volume_rub
        FROM orders
        WHERE user_id = $1 AND status IN ('PAID', 'COMPLETED')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id)
        if row:
            return dict(row)
        return {"paid_count": 0, "last_paid_at": None, "total_volume_rub": 0.0}


async def buyer_has_orders(user_id: int) -> bool:
    """Есть ли хотя бы одна заявка у этого Telegram user_id."""
    uid = int(user_id)
    if uid <= 0:
        return False
    pool = await get_pool()
    async with pool.acquire() as conn:
        found = await conn.fetchval(
            "SELECT 1 FROM orders WHERE user_id = $1 LIMIT 1",
            uid,
        )
    return found is not None


def clamp_receipt_limit(limit: int) -> int:
    """Пачка чеков в ops-чат: от 1 до 10."""
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return 1
    if n < 1:
        return 1
    return min(n, 10)


async def get_recent_receipt_orders(user_id: int, limit: int = 10) -> List[asyncpg.Record]:
    """Последние заявки пользователя с непустым receipt_file, любой статус."""
    capped = clamp_receipt_limit(limit)
    query = """
        SELECT order_id, merchant_order_id, payment_snapshot, crypto, direction,
               status, crypto_amount, fiat_amount, created_at, receipt_file,
               user_id, required_receipt_type
        FROM orders
        WHERE user_id = $1
          AND receipt_file IS NOT NULL
          AND btrim(receipt_file) <> ''
        ORDER BY created_at DESC
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, int(user_id), capped)


async def get_recent_approved_receipt_documents(
    limit: int, offset: int = 0
) -> List[asyncpg.Record]:
    """Свежие апрувнутые чеки-документы, без фильтра по банку.

    Банк реквизита (`bill.bank`) — это получатель перевода, а не банк, из которого
    клиент платил. Отправителя читаем из PDF уже после выборки.
    Видео отсекаются в запросе, иначе пачка документов была бы короче лимита.
    """
    capped = max(1, min(int(limit or 1), 200))
    skipped = max(0, int(offset or 0))
    query = """
        SELECT order_id, merchant_order_id, payment_snapshot, crypto, direction,
               status, crypto_amount, fiat_amount, created_at, receipt_file,
               user_id, required_receipt_type
        FROM orders
        WHERE status IN ('PAID', 'COMPLETED')
          AND receipt_file IS NOT NULL
          AND btrim(receipt_file) <> ''
          AND lower(receipt_file) !~ '\\.(mp4|mov|avi|webm|mkv|m4v|3gp)$'
        ORDER BY created_at DESC, order_id DESC
        LIMIT $1 OFFSET $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, capped, skipped)


async def get_completed_orders_by_user(user_id: int, limit: int = 10) -> List[asyncpg.Record]:
    """Последние завершённые заявки пользователя (COMPLETED или PAID)."""
    query = """
        SELECT o.order_id, o.crypto, o.direction, o.status,
               o.crypto_amount, o.fiat_amount, o.created_at,
               COALESCE(o.cashback_applied_rub, 0)::float AS cashback_applied_rub,
               accrual.amount_rub AS cashback_accrued_rub
        FROM orders o
        LEFT JOIN LATERAL (
            SELECT l.amount_rub
            FROM user_cashback_ledger l
            WHERE l.user_id = o.user_id
              AND l.type = 'accrual'
              AND l.order_id = o.order_id
            LIMIT 1
        ) accrual ON true
        WHERE o.user_id = $1
          AND o.status IN ('COMPLETED', 'PAID')
        ORDER BY o.created_at DESC
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, user_id, limit)


# ============================================================
# BOT USERS — для рассылки (все, кто хотя бы раз запустил бота)
# ============================================================

async def ensure_bot_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
):
    """Добавляет пользователя в bot_users или обновляет last_seen_at (при /start или другом входе).

    При смене username сохраняет старый в previous_username и ставит username_changed_at.
    """
    query = """
        INSERT INTO bot_users (user_id, username, first_name, first_seen_at, last_seen_at)
        VALUES ($1, $2, $3, now(), now())
        ON CONFLICT (user_id) DO UPDATE SET
            last_seen_at = now(),
            previous_username = CASE
                WHEN EXCLUDED.username IS NOT NULL
                     AND bot_users.username IS NOT NULL
                     AND EXCLUDED.username IS DISTINCT FROM bot_users.username
                THEN bot_users.username
                ELSE bot_users.previous_username
            END,
            username_changed_at = CASE
                WHEN EXCLUDED.username IS NOT NULL
                     AND bot_users.username IS NOT NULL
                     AND EXCLUDED.username IS DISTINCT FROM bot_users.username
                THEN now()
                ELSE bot_users.username_changed_at
            END,
            username = CASE
                WHEN EXCLUDED.username IS NOT NULL THEN EXCLUDED.username
                ELSE bot_users.username
            END,
            first_name = CASE
                WHEN EXCLUDED.first_name IS NOT NULL THEN EXCLUDED.first_name
                ELSE bot_users.first_name
            END
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, user_id, username, first_name)


async def get_bot_user(user_id: int):
    query = """
        SELECT user_id, username, first_name, first_seen_at, last_seen_at, captcha_passed_at,
               previous_username, username_changed_at,
               account_review_status, account_review_reason,
               account_reviewed_at, account_reviewed_by
        FROM bot_users
        WHERE user_id = $1
        LIMIT 1
    """
    query_with_device = """
        SELECT user_id, username, first_name, first_seen_at, last_seen_at, captcha_passed_at,
               previous_username, username_changed_at,
               account_review_status, account_review_reason,
               account_reviewed_at, account_reviewed_by,
               COALESCE(device_review_status, 'none') AS device_review_status,
               device_review_reason
        FROM bot_users
        WHERE user_id = $1
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await conn.fetchrow(query_with_device, user_id)
        except Exception:
            return await conn.fetchrow(query, user_id)


async def get_buyer_payfast_conversion(user_id: int) -> dict:
    """Конверсия taken→paid по всем BUY (Payfast + ручные)."""
    query = """
        SELECT
            COUNT(*)::int AS taken,
            COUNT(*) FILTER (WHERE status = 'PAID')::int AS paid,
            COUNT(*) FILTER (WHERE status IN ('CANCELED', 'EXPIRED'))::int AS failed
        FROM orders
        WHERE user_id = $1
          AND direction = 'buy'
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id)
    taken = int(row["taken"] or 0) if row else 0
    paid = int(row["paid"] or 0) if row else 0
    failed = int(row["failed"] or 0) if row else 0
    denom = paid + failed
    conv_pct = round(100.0 * paid / denom, 1) if denom > 0 else None
    return {
        "taken": taken,
        "paid": paid,
        "failed": failed,
        "conversion_pct": conv_pct,
    }


async def get_buyer_stat_summary(user_id: int) -> dict:
    """Сводка заявок клиента для /stat в группе споров."""
    query = """
        SELECT
            COUNT(*)::int AS total_orders,
            COUNT(*) FILTER (WHERE direction = 'buy')::int AS buy_total,
            COUNT(*) FILTER (WHERE direction = 'buy' AND status = 'PAID')::int AS buy_paid,
            COUNT(*) FILTER (
                WHERE direction = 'buy' AND status IN ('CANCELED', 'EXPIRED')
            )::int AS buy_failed,
            COUNT(*) FILTER (WHERE status IN ('PAID', 'COMPLETED'))::int AS paid_orders,
            COALESCE(
                SUM(fiat_amount) FILTER (WHERE status IN ('PAID', 'COMPLETED')),
                0
            )::double precision AS turnover_rub,
            MIN(created_at) AS first_order_at,
            MAX(created_at) FILTER (WHERE status IN ('PAID', 'COMPLETED')) AS last_paid_at
        FROM orders
        WHERE user_id = $1
    """
    empty = {
        "total_orders": 0,
        "buy_total": 0,
        "buy_paid": 0,
        "buy_failed": 0,
        "paid_orders": 0,
        "turnover_rub": 0.0,
        "first_order_at": None,
        "last_paid_at": None,
        "conversion_pct": None,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id)
    if not row:
        return empty
    buy_paid = int(row["buy_paid"] or 0)
    buy_failed = int(row["buy_failed"] or 0)
    denom = buy_paid + buy_failed
    conv_pct = round(100.0 * buy_paid / denom, 1) if denom > 0 else None
    return {
        "total_orders": int(row["total_orders"] or 0),
        "buy_total": int(row["buy_total"] or 0),
        "buy_paid": buy_paid,
        "buy_failed": buy_failed,
        "paid_orders": int(row["paid_orders"] or 0),
        "turnover_rub": float(row["turnover_rub"] or 0),
        "first_order_at": row["first_order_at"],
        "last_paid_at": row["last_paid_at"],
        "conversion_pct": conv_pct,
    }


async def find_wallet_reuse(
    wallet: str,
    exclude_user_id: int,
    *,
    limit: int = 20,
) -> list[dict]:
    """Другие user_id с тем же BUY wallet — любой статус (вкл. CANCELED/EXPIRED)."""
    addr = (wallet or "").strip()
    if not addr:
        return []
    query = """
        SELECT o.user_id,
               o.order_id,
               o.status,
               o.created_at,
               b.username
        FROM orders o
        LEFT JOIN bot_users b ON b.user_id = o.user_id
        WHERE o.wallet_address = $1
          AND o.user_id <> $2
          AND o.direction = 'buy'
        ORDER BY o.created_at DESC
        LIMIT $3
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, addr, int(exclude_user_id), int(limit))
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "user_id": int(r["user_id"]),
                "order_id": str(r["order_id"]),
                "status": str(r["status"] or ""),
                "created_at": r["created_at"],
                "username": r["username"],
            }
        )
    return out


async def find_ip_reuse(
    ip: str,
    exclude_user_id: int,
    *,
    limit: int = 20,
) -> list[dict]:
    """Другие user_id с тем же IP (orders + web_order_ip_log + device signals)."""
    addr = (ip or "").strip()
    if not addr:
        return []
    query = """
        WITH hits AS (
            SELECT o.user_id,
                   o.order_id,
                   o.status,
                   o.created_at,
                   b.username
            FROM orders o
            LEFT JOIN bot_users b ON b.user_id = o.user_id
            WHERE o.client_ip = $1::inet
              AND o.user_id IS NOT NULL
              AND o.user_id <> $2

            UNION ALL

            SELECT w.user_id,
                   w.order_id,
                   NULL::text AS status,
                   w.created_at,
                   b.username
            FROM web_order_ip_log w
            LEFT JOIN bot_users b ON b.user_id = w.user_id
            WHERE w.ip_address = $1::inet
              AND w.user_id IS NOT NULL
              AND w.user_id <> $2

            UNION ALL

            SELECT s.user_id,
                   s.order_id,
                   NULL::text AS status,
                   s.created_at,
                   b.username
            FROM buyer_device_signals s
            LEFT JOIN bot_users b ON b.user_id = s.user_id
            WHERE s.ip = $1::inet
              AND s.user_id IS NOT NULL
              AND s.user_id <> $2
        )
        SELECT DISTINCT ON (user_id)
               user_id, order_id, status, created_at, username
        FROM hits
        ORDER BY user_id, created_at DESC NULLS LAST
        LIMIT $3
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(query, addr, int(exclude_user_id), int(limit))
        except Exception:
            # колонка/таблица может отсутствовать на старых стендах
            return []
    return [
        {
            "user_id": int(r["user_id"]),
            "order_id": str(r["order_id"] or "") or None,
            "status": str(r["status"] or ""),
            "created_at": r["created_at"],
            "username": r["username"],
        }
        for r in rows
    ]


def serialize_reuse_matches(rows: list[dict] | None, *, limit: int = 5) -> list[dict]:
    """JSON-safe список совпадений IP/FP для payment_snapshot."""
    out: list[dict] = []
    for r in (rows or [])[:limit]:
        try:
            uid = int(r["user_id"]) if r.get("user_id") is not None else None
        except (TypeError, ValueError):
            uid = None
        out.append(
            {
                "user_id": uid,
                "username": (str(r.get("username") or "").strip().lstrip("@") or None),
                "order_id": str(r.get("order_id") or "") or None,
                "status": str(r.get("status") or "") or None,
            }
        )
    return out


async def find_receipt_sha256_reuse(
    sha256: str,
    *,
    exclude_order_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Другие заявки с тем же receipt sha256 в payment_snapshot."""
    digest = (sha256 or "").strip().lower()
    if not digest or len(digest) < 16:
        return []
    query = """
        SELECT o.order_id, o.user_id, o.status, b.username
        FROM orders o
        LEFT JOIN bot_users b ON b.user_id = o.user_id
        WHERE o.payment_snapshot->>'receipt_sha256' = $1
          AND ($2::text IS NULL OR o.order_id <> $2)
        ORDER BY o.created_at DESC
        LIMIT $3
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            query,
            digest,
            exclude_order_id,
            int(limit),
        )
    return [
        {
            "order_id": str(r["order_id"]),
            "user_id": int(r["user_id"]),
            "status": str(r["status"] or ""),
            "username": r["username"],
        }
        for r in rows
    ]


async def get_last_payfast_unpaid_at(user_id: int, *, within_minutes: int | None = None):
    """Время последней неоплаты BUY, где реквизиты клиенту уже выдали.

    Признак выдачи — счёт с получателем в снапшоте, тот же, по которому судит
    веб (`order_service._snapshot_has_bill`). По `requisites_revealed_at`
    судить нельзя: это поле пишет только WebApp-страница реквизитов, с
    2026-09-08 оно не проставляется вообще, и кулдаун молча не срабатывал.
    `merchant_order_id` тоже не условие — у заявок на реквизитах оператора
    его нет, и они проходили мимо гейта.
    """
    from services.payin_resolver import _bill_has_reciver
    from services.payment_snapshot import order_payment_snapshot

    query = """
        SELECT updated_at, payment_snapshot
        FROM orders
        WHERE user_id = $1
          AND direction = 'buy'
          AND status IN ('CANCELED', 'EXPIRED')
          AND payment_snapshot ? 'bill'
          AND ($2::int IS NULL OR updated_at > now() - make_interval(mins => $2::int))
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 10
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, within_minutes)
    for row in rows:
        if _bill_has_reciver(order_payment_snapshot(row).get("bill")):
            return row["updated_at"]
    return None


async def get_last_payfast_cancel_at(user_id: int):
    """Alias: кулдаун после любой неоплаты (cancel или expire)."""
    return await get_last_payfast_unpaid_at(user_id)


async def get_payfast_conversion_period(days: int = 1) -> dict:
    """Агрегат taken→paid по всем BUY за последние N дней."""
    days = max(1, int(days))
    query = """
        SELECT
            COUNT(*)::int AS taken,
            COUNT(*) FILTER (WHERE status = 'PAID')::int AS paid,
            COUNT(*) FILTER (WHERE status IN ('CANCELED', 'EXPIRED'))::int AS failed,
            COUNT(*) FILTER (WHERE status = 'EXPIRED')::int AS expired,
            COUNT(*) FILTER (WHERE status = 'CANCELED')::int AS canceled
        FROM orders
        WHERE direction = 'buy'
          AND created_at > now() - ($1 * interval '1 day')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, days)
    taken = int(row["taken"] or 0) if row else 0
    paid = int(row["paid"] or 0) if row else 0
    failed = int(row["failed"] or 0) if row else 0
    denom = paid + failed
    conv_pct = round(100.0 * paid / denom, 1) if denom > 0 else None
    return {
        "taken": taken,
        "paid": paid,
        "failed": failed,
        "expired": int(row["expired"] or 0) if row else 0,
        "canceled": int(row["canceled"] or 0) if row else 0,
        "conversion_pct": conv_pct,
        "days": days,
    }


async def set_account_review_status(
    user_id: int,
    status: str,
    *,
    reason: str | None = None,
    operator_id: int | None = None,
) -> bool:
    """Обновить account_review_status. Возвращает True если строка обновлена."""
    if status not in ("none", "pending", "approved", "rejected"):
        raise ValueError(f"invalid account_review_status: {status}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE bot_users
            SET account_review_status = $2,
                account_review_reason = $3,
                account_reviewed_at = CASE
                    WHEN $2 IN ('approved', 'rejected') THEN now()
                    WHEN $2 = 'pending' THEN COALESCE(account_reviewed_at, now())
                    ELSE account_reviewed_at
                END,
                account_reviewed_by = CASE
                    WHEN $4::bigint IS NOT NULL THEN $4
                    ELSE account_reviewed_by
                END
            WHERE user_id = $1
            """,
            user_id,
            status,
            reason,
            operator_id,
        )
    return res.endswith("1")


async def set_device_review_status(
    user_id: int,
    status: str,
    *,
    reason: str | None = None,
    operator_id: int | None = None,
) -> bool:
    if status not in ("none", "pending", "approved", "rejected"):
        raise ValueError(f"invalid device_review_status: {status}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            res = await conn.execute(
                """
                UPDATE bot_users
                SET device_review_status = $2,
                    device_review_reason = $3,
                    device_review_at = CASE
                        WHEN $2 IN ('approved', 'rejected', 'pending') THEN now()
                        ELSE device_review_at
                    END,
                    device_review_by = CASE
                        WHEN $4::bigint IS NOT NULL THEN $4
                        ELSE device_review_by
                    END
                WHERE user_id = $1
                """,
                user_id,
                status,
                reason,
                operator_id,
            )
        except Exception:
            return False
    return res.endswith("1")


async def get_latest_device_signal_for_order(order_id: str) -> dict | None:
    """Последний fingerprint/IP сигнал Mini App по заявке."""
    oid = (order_id or "").strip()
    if not oid:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                SELECT user_id, order_id, fingerprint, host(ip)::text AS ip,
                       user_agent, platform, screen, timezone, languages, extra, created_at
                FROM buyer_device_signals
                WHERE order_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                oid,
            )
        except Exception:
            return None
    return dict(row) if row else None


async def get_latest_device_signal_for_user(user_id: int) -> dict | None:
    """Последний fingerprint/IP сигнал Mini App по user_id."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                SELECT user_id, order_id, fingerprint, host(ip)::text AS ip,
                       user_agent, platform, screen, timezone, languages, extra, created_at
                FROM buyer_device_signals
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                uid,
            )
        except Exception:
            return None
    return dict(row) if row else None


async def save_device_signal(
    *,
    user_id: int,
    order_id: str | None,
    fingerprint: str | None,
    ip: str | None,
    user_agent: str | None = None,
    platform: str | None = None,
    screen: str | None = None,
    timezone: str | None = None,
    languages: list | None = None,
    extra: dict | None = None,
) -> int | None:
    import json

    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO buyer_device_signals (
                    user_id, order_id, fingerprint, ip, user_agent, platform,
                    screen, timezone, languages, extra
                )
                VALUES (
                    $1, $2, $3, $4::inet, $5, $6, $7, $8, $9::jsonb, $10::jsonb
                )
                RETURNING id
                """,
                int(user_id),
                order_id,
                (fingerprint or "").strip() or None,
                (ip or "").strip() or None,
                user_agent,
                platform,
                screen,
                timezone,
                json.dumps(languages) if languages is not None else None,
                json.dumps(extra or {"source": "tg_webapp"}),
            )
        except Exception:
            return None
    return int(row["id"]) if row else None


async def find_fingerprint_reuse(
    fingerprint: str,
    exclude_user_id: int,
    *,
    limit: int = 20,
) -> list[dict]:
    fp = (fingerprint or "").strip().lower()
    if not fp or len(fp) < 16:
        return []
    query = """
        SELECT DISTINCT ON (s.user_id)
               s.user_id, s.order_id, s.created_at, b.username
        FROM buyer_device_signals s
        LEFT JOIN bot_users b ON b.user_id = s.user_id
        WHERE s.fingerprint = $1
          AND s.user_id <> $2
        ORDER BY s.user_id, s.created_at DESC
        LIMIT $3
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(query, fp, int(exclude_user_id), int(limit))
        except Exception:
            return []
    return [
        {
            "user_id": int(r["user_id"]),
            "order_id": str(r["order_id"] or "") or None,
            "created_at": r["created_at"],
            "username": r["username"],
        }
        for r in rows
    ]


async def count_fingerprint_users(fingerprint: str) -> int:
    """Сколько разных user_id уже имеют этот fingerprint (когорта модели)."""
    fp = (fingerprint or "").strip().lower()
    if not fp or len(fp) < 16:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            n = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT user_id)::int
                FROM buyer_device_signals
                WHERE fingerprint = $1
                """,
                fp,
            )
        except Exception:
            return 0
    return int(n or 0)


# Старый FP (до v2) часто общий у одной модели iPhone в TG WebView.
# Если один хеш уже у ≥2 аккаунтов — это когорта, не доказательство одного устройства.
POPULAR_FP_USER_THRESHOLD = 2


def is_popular_fingerprint(user_count: int) -> bool:
    return int(user_count or 0) >= POPULAR_FP_USER_THRESHOLD


async def set_order_client_ip(order_id: str, ip: str | None) -> None:
    addr = (ip or "").strip()
    if not addr:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                UPDATE orders SET client_ip = $2::inet, updated_at = now()
                WHERE order_id = $1 AND client_ip IS NULL
                """,
                order_id,
                addr,
            )
        except Exception:
            logger.debug("client_ip backfill skipped", exc_info=True)


async def get_orders_needing_payment_nudge(
    *,
    remaining_sec: int = 300,
    limit: int = 50,
) -> list:
    """Legacy CREATED BUY с expires_at в ближайшие remaining_sec."""
    query = """
        SELECT order_id, user_id, fiat_amount, crypto, crypto_amount, expires_at,
               payment_snapshot, status, merchant_order_id
        FROM orders
        WHERE direction = 'buy'
          AND status = 'CREATED'
          AND expires_at IS NOT NULL
          AND expires_at > now()
          AND expires_at <= now() + ($1 * interval '1 second')
          AND COALESCE(payment_snapshot->>'merchant_expires_at', '') = ''
          AND COALESCE(payment_snapshot->>'payment_nudge_5m_sent_at', '') = ''
        ORDER BY expires_at ASC
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, int(remaining_sec), int(limit))


async def get_orders_with_closed_payfast_requisites(*, limit: int = 50) -> list:
    """Новые BUY в recovery-окне PayFast без одноразового уведомления."""
    query = """
        SELECT order_id, user_id, fiat_amount, crypto, crypto_amount, expires_at,
               payment_snapshot, status, merchant_order_id
        FROM orders
        WHERE direction = 'buy'
          AND status = 'CREATED'
          AND expires_at <= now()
          AND COALESCE(payment_snapshot->>'merchant_expires_at', '')
              ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
          AND (payment_snapshot->>'merchant_expires_at')::timestamptz > now()
          AND COALESCE(
                payment_snapshot->>'payment_requisites_closed_7m_sent_at',
                ''
              ) = ''
          AND (
                COALESCE(
                    payment_snapshot->>'payment_requisites_closed_7m_sent_at_lease_id',
                    ''
                ) = ''
                OR NOT (
                    COALESCE(
                        payment_snapshot->>'payment_requisites_closed_7m_sent_at_lease_until',
                        ''
                    ) ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                )
                OR (payment_snapshot->>'payment_requisites_closed_7m_sent_at_lease_until')::timestamptz <= now()
              )
        ORDER BY expires_at ASC
        LIMIT $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, int(limit))


def _valid_payment_snapshot_marker(marker: str) -> bool:
    return bool(marker) and marker.replace("_", "").isalnum()


async def acquire_order_payment_snapshot_lease(
    order_id: str,
    marker: str,
    *,
    lease_seconds: int = 120,
) -> str | None:
    """Захватить временный lease для доставки одноразового уведомления."""
    import uuid

    if not _valid_payment_snapshot_marker(marker):
        raise ValueError("Invalid payment snapshot marker")
    lease_id = uuid.uuid4().hex
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = jsonb_set(
                    jsonb_set(
                        COALESCE(payment_snapshot, '{}'::jsonb),
                        ARRAY[$2 || '_lease_id'],
                        to_jsonb($3::text),
                        TRUE
                    ),
                    ARRAY[$2 || '_lease_until'],
                    to_jsonb(
                        to_char(
                            timezone('UTC', now() + ($4 * interval '1 second')),
                            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                        )
                    ),
                    TRUE
                ),
                updated_at = now()
            WHERE order_id = $1
              AND COALESCE(payment_snapshot->>$2, '') = ''
              AND (
                    COALESCE(payment_snapshot->>($2 || '_lease_id'), '') = ''
                    OR NOT (
                        COALESCE(
                            payment_snapshot->>($2 || '_lease_until'),
                            ''
                        ) ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                    )
                    OR (payment_snapshot->>($2 || '_lease_until'))::timestamptz <= now()
                  )
            """,
            order_id,
            marker,
            lease_id,
            max(1, int(lease_seconds)),
        )
    return lease_id if result.endswith("1") else None


async def complete_order_payment_snapshot_lease(
    order_id: str,
    marker: str,
    lease_id: str,
) -> bool:
    """Подтвердить доставку уведомления, удерживаемого текущим lease."""
    if not _valid_payment_snapshot_marker(marker) or not lease_id:
        raise ValueError("Invalid payment snapshot marker lease")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            COALESCE(payment_snapshot, '{}'::jsonb),
                            ARRAY[$2::text],
                            to_jsonb(now()::text),
                            TRUE
                        ),
                        ARRAY[$2 || '_lease_id'],
                        to_jsonb(''::text),
                        TRUE
                    ),
                    ARRAY[$2 || '_lease_until'],
                    to_jsonb(''::text),
                    TRUE
                ),
                updated_at = now()
            WHERE order_id = $1
              AND COALESCE(payment_snapshot->>$2, '') = ''
              AND payment_snapshot->>($2 || '_lease_id') = $3
            """,
            order_id,
            marker,
            lease_id,
        )
    return result.endswith("1")


async def release_order_payment_snapshot_lease(
    order_id: str,
    marker: str,
    lease_id: str,
) -> bool:
    """Освободить lease после ошибки доставки, чтобы следующая итерация повторила её."""
    if not _valid_payment_snapshot_marker(marker) or not lease_id:
        raise ValueError("Invalid payment snapshot marker lease")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = jsonb_set(
                    jsonb_set(
                        COALESCE(payment_snapshot, '{}'::jsonb),
                        ARRAY[$2 || '_lease_id'],
                        to_jsonb(''::text),
                        TRUE
                    ),
                    ARRAY[$2 || '_lease_until'],
                    to_jsonb(''::text),
                    TRUE
                ),
                updated_at = now()
            WHERE order_id = $1
              AND COALESCE(payment_snapshot->>$2, '') = ''
              AND payment_snapshot->>($2 || '_lease_id') = $3
            """,
            order_id,
            marker,
            lease_id,
        )
    return result.endswith("1")


async def user_has_payment_active_order(user_id: int) -> bool:
    """CREATED или AWAITING_CHECK — для кнопки «Активная заявка»."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            """
            SELECT 1 FROM orders
            WHERE user_id = $1
              AND direction = 'buy'
              AND status IN ('CREATED', 'AWAITING_CHECK')
            LIMIT 1
            """,
            int(user_id),
        )
    return row is not None


async def mark_account_review_approved_on_paid(user_id: int) -> None:
    """Авто-approve после первого PAID (если ещё не approved)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE bot_users
            SET account_review_status = 'approved',
                account_reviewed_at = COALESCE(account_reviewed_at, now()),
                account_review_reason = COALESCE(account_review_reason, 'auto_paid')
            WHERE user_id = $1
              AND COALESCE(account_review_status, 'none') <> 'approved'
            """,
            user_id,
        )


async def set_captcha_passed(user_id: int) -> None:
    """Проставить captcha_passed_at = now() после успешного прохождения капчи."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE bot_users SET captcha_passed_at = now() WHERE user_id = $1",
            user_id,
        )


async def is_user_banned(user_id: int) -> tuple[bool, str | None, str]:
    """Проверить, заблокирован ли клиент.

    Возвращает (is_banned, ban_reason, ban_type).
    ban_type: 'hard' — явный бан, 'soft' — тихий блок (клиент видит «нет реквизитов»).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_banned, ban_reason, ban_type FROM bot_users WHERE user_id = $1",
            user_id,
        )
    if not row:
        return False, None, "hard"
    return bool(row["is_banned"]), row.get("ban_reason"), (row.get("ban_type") or "hard")


async def ban_user(user_id: int, *, reason: str = "", operator_id: int, ban_type: str = "hard") -> bool:
    """Заблокировать клиента.

    ban_type: 'hard' — показывает «заблокирован», 'soft' — показывает «нет реквизитов».
    Возвращает True если пользователь найден.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE bot_users
            SET is_banned = TRUE, ban_type = $2, ban_reason = $3,
                banned_at = now(), banned_by_op_id = $4
            WHERE user_id = $1
            """,
            user_id,
            ban_type if ban_type in ("hard", "soft") else "hard",
            reason or None,
            operator_id,
        )
    return res.endswith("1")


async def unban_user(user_id: int) -> bool:
    """Разблокировать клиента. Возвращает True если пользователь найден."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            """
            UPDATE bot_users
            SET is_banned = FALSE, ban_type = 'hard', ban_reason = NULL,
                banned_at = NULL, banned_by_op_id = NULL
            WHERE user_id = $1
            """,
            user_id,
        )
    return res.endswith("1")


async def get_bot_user_ids(limit: int = 100_000) -> List[int]:
    """Список user_id всех пользователей бота (для рассылки)."""
    return await get_broadcast_user_ids("all", limit=limit)


BROADCAST_SEGMENTS = frozenset({"all", "inactive7", "paid", "referrers"})


async def get_broadcast_user_ids(segment: str = "all", *, limit: int = 100_000) -> List[int]:
    """Сегменты рассылки /post: all | inactive7 | paid | referrers."""
    seg = (segment or "all").strip().lower()
    if seg not in BROADCAST_SEGMENTS:
        seg = "all"
    if seg == "inactive7":
        query = """
            SELECT user_id FROM bot_users
            WHERE last_seen_at < now() - interval '7 days'
            ORDER BY last_seen_at DESC
            LIMIT $1
        """
    elif seg == "paid":
        query = """
            SELECT DISTINCT bu.user_id
            FROM bot_users bu
            JOIN orders o ON o.user_id = bu.user_id AND o.status = 'PAID'
            ORDER BY bu.user_id
            LIMIT $1
        """
    elif seg == "referrers":
        query = """
            SELECT DISTINCT referrer_user_id AS user_id
            FROM user_referral_attributions
            ORDER BY referrer_user_id
            LIMIT $1
        """
    else:
        query = """
            SELECT user_id FROM bot_users
            ORDER BY last_seen_at DESC
            LIMIT $1
        """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
    return [int(r["user_id"]) for r in rows]


async def is_stale_alert_sent(order_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            val = await conn.fetchval(
                "SELECT 1 FROM owner_stale_alerts WHERE order_id = $1",
                str(order_id),
            )
            return val is not None
        except Exception:
            return False


async def mark_stale_alert_sent(order_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO owner_stale_alerts (order_id, alerted_at)
                VALUES ($1, now())
                ON CONFLICT (order_id) DO NOTHING
                """,
                str(order_id),
            )
        except Exception:
            logger.debug("stale alert insert skipped", exc_info=True)


async def clear_stale_alert_sent(order_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM owner_stale_alerts WHERE order_id = $1",
                str(order_id),
            )
        except Exception:
            logger.debug("stale alert clear skipped", exc_info=True)


async def mark_ops_alert_once(order_id: str, kind: str) -> bool:
    """Дедуп повторяющихся ops-алертов по заявке.

    Возвращает True только при ПЕРВОМ вызове для пары (order_id, kind) — тогда
    уведомление нужно отправить. На повторных вызовах (ретраи вебхука) — False.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchval(
                """
                INSERT INTO ops_alert_dedup (order_id, kind, alerted_at)
                VALUES ($1, $2, now())
                ON CONFLICT (order_id, kind) DO NOTHING
                RETURNING 1
                """,
                str(order_id),
                str(kind),
            )
            return row is not None
        except Exception:
            logging.getLogger("db").warning(
                "mark_ops_alert_once failed order=%s kind=%s", order_id, kind
            )
            return False


async def ops_alert_was_sent(order_id: str, kind: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchval(
                "SELECT 1 FROM ops_alert_dedup WHERE order_id = $1 AND kind = $2",
                str(order_id),
                str(kind),
            )
            return row is not None
        except Exception:
            logging.getLogger("db").warning(
                "ops_alert_was_sent failed order=%s kind=%s", order_id, kind
            )
            return False


async def clear_ops_alert_once(order_id: str, kind: str) -> None:
    """Сбросить дедуп ops-алерта, чтобы уведомление могло прийти повторно.

    Нужно, например, когда выплата ставится на удержание и после повторного
    подтверждения оператору снова требуется свежая карточка «подтверждено».
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM ops_alert_dedup WHERE order_id = $1 AND kind = $2",
                str(order_id),
                str(kind),
            )
        except Exception:
            logging.getLogger("db").warning(
                "clear_ops_alert_once failed order=%s kind=%s", order_id, kind
            )


# ============================================================
# ORDERS — TELEGRAM DATA (если понадобится)
# ============================================================

async def get_order_telegram_data(order_id: str):
    query = """
        SELECT user_id
        FROM orders
        WHERE order_id = $1
    """

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, order_id)


# ============================================================
# PROMO CAMPAIGNS / ATTRIBUTIONS
# ============================================================

async def create_promo_campaign(
    *,
    code: str,
    name: str,
    bonus_percent: float,
    ad_spend_rub: float,
    created_by: int,
    ref_token: str | None = None,
):
    from services.referral_links import generate_ref_token

    token = ref_token or generate_ref_token()
    query = """
        INSERT INTO promo_campaigns (
            code, name, bonus_percent, ad_spend_rub, is_active, created_by,
            ref_token, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, TRUE, $5, $6, now(), now())
        RETURNING *
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            query, code, name, bonus_percent, ad_spend_rub, created_by, token
        )


async def list_promo_campaigns(active_only: bool = False, limit: int = 50) -> List[asyncpg.Record]:
    query = """
        SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by, created_at, updated_at
        FROM promo_campaigns
        WHERE ($1::bool = FALSE OR is_active = TRUE)
        ORDER BY created_at DESC
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, active_only, limit)


async def get_promo_campaign_by_id(campaign_id: int):
    query = """
        SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by, created_at, updated_at
        FROM promo_campaigns
        WHERE id = $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, campaign_id)


async def get_active_promo_campaign_by_code(code: str):
    query = """
        SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by,
               ref_token, campaign_kind, client_fixed_bonus_rub, created_at, updated_at
        FROM promo_campaigns
        WHERE code = $1
          AND is_active = TRUE
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, code)


async def get_active_promo_campaign_by_ref_token(ref_token: str):
    query = """
        SELECT id, code, name, bonus_percent, ad_spend_rub, is_active, created_by,
               ref_token, campaign_kind, client_fixed_bonus_rub, created_at, updated_at
        FROM promo_campaigns
        WHERE ref_token = $1
          AND is_active = TRUE
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, ref_token.strip().lower())


async def update_promo_bonus_percent(campaign_id: int, bonus_percent: float):
    query = """
        UPDATE promo_campaigns
        SET bonus_percent = $1,
            updated_at = now()
        WHERE id = $2
        RETURNING *
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, bonus_percent, campaign_id)


async def set_promo_campaign_active(campaign_id: int, is_active: bool):
    query = """
        UPDATE promo_campaigns
        SET is_active = $1,
            updated_at = now()
        WHERE id = $2
        RETURNING *
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, is_active, campaign_id)


async def promo_campaign_has_attributions(campaign_id: int) -> bool:
    query = """
        SELECT EXISTS (
            SELECT 1
            FROM promo_attributions pa
            JOIN promo_campaigns pc ON pc.code = pa.promo_code
            WHERE pc.id = $1
        ) AS has_data
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, campaign_id)
        return bool(row["has_data"]) if row else False


async def delete_promo_campaign(campaign_id: int) -> bool:
    query = """
        DELETE FROM promo_campaigns
        WHERE id = $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(query, campaign_id)
        return result.endswith("1")


async def assign_promo_to_user_if_first(user_id: int, promo_code: str) -> bool:
    """
    Привязывает пользователя к promo-коду только один раз.
    Учитывает max_activations только для gift/generic; у партнёров — без лимита.
    Возвращает True, если связь создана сейчас; False, если уже была привязка или лимит исчерпан.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            campaign = await conn.fetchrow(
                """
                SELECT max_activations, campaign_kind FROM promo_campaigns
                WHERE code = $1 AND is_active = TRUE
                FOR UPDATE
                """,
                promo_code,
            )
            if not campaign:
                return False
            kind = (campaign.get("campaign_kind") or "").lower()
            if kind != "partner":
                max_act = int(campaign["max_activations"] or 5)
                used = int(
                    await conn.fetchval(
                        "SELECT COUNT(*)::int FROM promo_attributions WHERE promo_code = $1",
                        promo_code,
                    )
                    or 0
                )
                if used >= max_act:
                    return False
            result = await conn.execute(
                """
                INSERT INTO promo_attributions (user_id, promo_code, assigned_at)
                VALUES ($1, $2, now())
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id,
                promo_code,
            )
            applied = result.endswith("1")
            is_partner = kind == "partner"
        if applied and is_partner:
            import asyncio

            from services.partner_tier_notify import maybe_notify_tier_upgrade

            asyncio.create_task(maybe_notify_tier_upgrade(promo_code))
        return applied


async def get_promo_stats_for_days(days: int = 1) -> List[asyncpg.Record]:
    query = """
        SELECT
            pc.id,
            pc.code,
            pc.name,
            pc.bonus_percent,
            pc.ad_spend_rub,
            pc.is_active,
            COUNT(DISTINCT pa.user_id)::int AS attracted_users,
            COUNT(o.id)::int AS paid_orders_count,
            COALESCE(SUM(o.fiat_amount), 0)::double precision AS paid_fiat_sum
        FROM promo_campaigns pc
        LEFT JOIN promo_attributions pa ON pa.promo_code = pc.code
        LEFT JOIN orders o
          ON o.user_id = pa.user_id
         AND o.status = 'PAID'
         AND o.created_at >= now() - ($1 * interval '1 day')
        GROUP BY pc.id, pc.code, pc.name, pc.bonus_percent, pc.ad_spend_rub, pc.is_active
        ORDER BY pc.created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, days)


async def get_promo_stats_for_date(date_obj: date) -> List[asyncpg.Record]:
    query = """
        SELECT
            pc.id,
            pc.code,
            pc.name,
            pc.bonus_percent,
            pc.ad_spend_rub,
            pc.is_active,
            COUNT(DISTINCT pa.user_id)::int AS attracted_users,
            COUNT(o.id)::int AS paid_orders_count,
            COALESCE(SUM(o.fiat_amount), 0)::double precision AS paid_fiat_sum
        FROM promo_campaigns pc
        LEFT JOIN promo_attributions pa ON pa.promo_code = pc.code
        LEFT JOIN orders o
          ON o.user_id = pa.user_id
         AND o.status = 'PAID'
         AND o.created_at::date = $1
        GROUP BY pc.id, pc.code, pc.name, pc.bonus_percent, pc.ad_spend_rub, pc.is_active
        ORDER BY pc.created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, date_obj)


async def get_promo_paid_orders_for_days(days: int = 1) -> List[asyncpg.Record]:
    query = """
        SELECT
            pc.id AS campaign_id,
            pc.code,
            pc.name,
            pc.bonus_percent,
            pc.ad_spend_rub,
            pa.user_id,
            o.crypto,
            o.direction,
            o.crypto_amount,
            o.fiat_amount,
            o.rate,
            o.cashback_applied_rub,
            o.card_fee_pct,
            o.economics_snapshot
        FROM promo_campaigns pc
        JOIN promo_attributions pa ON pa.promo_code = pc.code
        JOIN orders o ON o.user_id = pa.user_id
        WHERE o.status = 'PAID'
          AND o.created_at >= now() - ($1 * interval '1 day')
          AND o.created_at >= pa.assigned_at
        ORDER BY pc.id, o.created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, days)


async def get_promo_paid_orders_for_date(date_obj: date) -> List[asyncpg.Record]:
    query = """
        SELECT
            pc.id AS campaign_id,
            pc.code,
            pc.name,
            pc.bonus_percent,
            pc.ad_spend_rub,
            pa.user_id,
            o.crypto,
            o.direction,
            o.crypto_amount,
            o.fiat_amount,
            o.rate,
            o.cashback_applied_rub,
            o.card_fee_pct,
            o.economics_snapshot
        FROM promo_campaigns pc
        JOIN promo_attributions pa ON pa.promo_code = pc.code
        JOIN orders o ON o.user_id = pa.user_id
        WHERE o.status = 'PAID'
          AND o.created_at::date = $1
          AND o.created_at >= pa.assigned_at
        ORDER BY pc.id, o.created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, date_obj)


# ============================================================
# OWNER DASHBOARD
# ============================================================

_OWNER_PAID_COLUMNS = """
    order_id, direction, crypto, crypto_amount, fiat_amount, rate,
    COALESCE(cashback_applied_rub, 0)::float AS cashback_applied_rub,
    card_fee_pct,
    economics_snapshot,
    created_at,
    payout_confirmed_at,
    updated_at
"""


async def get_paid_orders_for_owner_days(days: int = 1) -> List[asyncpg.Record]:
    """PAID за последние days дней с полями для order_service_profit."""
    query = f"""
        SELECT {_OWNER_PAID_COLUMNS}
        FROM orders
        WHERE status = 'PAID'
          AND created_at >= now() - ($1 * interval '1 day')
        ORDER BY created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, days)


async def get_paid_orders_for_owner_date(date_obj: date) -> List[asyncpg.Record]:
    query = f"""
        SELECT {_OWNER_PAID_COLUMNS}
        FROM orders
        WHERE status = 'PAID'
          AND created_at::date = $1
        ORDER BY created_at DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, date_obj)


async def sum_review_bonus_rub(days: int = 1) -> float:
    """SUM выплаченных бонусов за отзывы за последние days дней."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM review_bonus_claims
            WHERE created_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_review_bonus_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM review_bonus_claims
            WHERE created_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def sum_operator_wallet_payout_rub(days: int = 1) -> float:
    """SUM зафиксированных крипто-выплат операторами за последние days дней."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM operator_wallet_payouts
            WHERE created_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_operator_wallet_payout_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM operator_wallet_payouts
            WHERE created_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def sum_buy_network_fee_rub(days: int = 1) -> float:
    """SUM network_fee_rub по PAID BUY-заявкам за период."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(network_fee_rub), 0)::float
            FROM orders
            WHERE status = 'PAID'
              AND LOWER(direction) = 'buy'
              AND payout_confirmed_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_buy_network_fee_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(network_fee_rub), 0)::float
            FROM orders
            WHERE status = 'PAID'
              AND LOWER(direction) = 'buy'
              AND payout_confirmed_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def sum_cashback_accrual_rub(days: int = 1) -> float:
    """Начисления кешбэка пользователям (type=accrual) за период."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_cashback_ledger
            WHERE type = 'accrual'
              AND created_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_cashback_accrual_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_cashback_ledger
            WHERE type = 'accrual' AND created_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def sum_referral_accrual_rub(days: int = 1) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger
            WHERE type = 'accrual'
              AND created_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_referral_accrual_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger
            WHERE type = 'accrual' AND created_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def sum_partner_accrual_rub(days: int = 1) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM partner_ledger
            WHERE type = 'accrual'
              AND created_at >= now() - ($1 * interval '1 day')
            """,
            days,
        )
    return float(val or 0)


async def sum_partner_accrual_rub_for_date(date_obj: date) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM partner_ledger
            WHERE type = 'accrual' AND created_at::date = $1
            """,
            date_obj,
        )
    return float(val or 0)


async def get_active_operator_shifts() -> List[asyncpg.Record]:
    query = """
        SELECT
            s.id,
            s.operator_id,
            s.started_at,
            a.telegram_user_id,
            COALESCE(a.display_name, a.username) AS operator_name,
            a.operator_role,
            a.operator_roles
        FROM operator_shifts s
        JOIN operator_accounts a ON a.id = s.operator_id
        WHERE s.ended_at IS NULL
          AND a.is_active = TRUE
        ORDER BY s.started_at
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query)


async def record_no_shift_requisites_block(
    user_id: int,
    direction: str,
    reason: str = "no_shift",
    fiat_amount: int | None = None,
) -> bool:
    """Один клиент за скользящий час: повтор через 5–30 мин не пишем."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        inserted = await conn.fetchval(
            """
            INSERT INTO no_shift_requisites_blocks (user_id, direction, reason, fiat_amount)
            SELECT $1, $2, $3, $4
            WHERE NOT EXISTS (
                SELECT 1
                FROM no_shift_requisites_blocks
                WHERE user_id = $1
                  AND created_at > now() - interval '1 hour'
            )
            RETURNING id
            """,
            int(user_id),
            (direction or "buy")[:8],
            (reason or "no_shift")[:20],
            int(fiat_amount) if fiat_amount else None,
        )
        return inserted is not None


async def count_no_shift_blocks_since(since: datetime) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM no_shift_requisites_blocks
            WHERE created_at >= $1
            """,
            since,
        )
        return int(val or 0)


async def get_no_shift_requisites_blocks(
    since: datetime,
    until: datetime | None = None,
    *,
    limit: int = 1000,
) -> list[asyncpg.Record]:
    """Пропуски клиентов из-за отсутствия реквизитов за заданный период."""
    limit = max(1, min(int(limit), 5000))
    pool = await get_pool()
    async with pool.acquire() as conn:
        if until is None:
            return await conn.fetch(
                """
                SELECT id, user_id, direction, reason, created_at, fiat_amount
                FROM no_shift_requisites_blocks
                WHERE created_at >= $1
                ORDER BY created_at ASC, id ASC
                LIMIT $2
                """,
                since,
                limit,
            )
        return await conn.fetch(
            """
            SELECT id, user_id, direction, reason, created_at, fiat_amount
            FROM no_shift_requisites_blocks
            WHERE created_at >= $1
              AND created_at < $2
            ORDER BY created_at ASC, id ASC
            LIMIT $3
            """,
            since,
            until,
            limit,
        )


async def count_no_shift_requisites_blocks(
    since: datetime,
    until: datetime | None = None,
) -> int:
    """Количество пропусков клиентов из-за отсутствия реквизитов."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if until is None:
            val = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM no_shift_requisites_blocks
                WHERE created_at >= $1
                """,
                since,
            )
        else:
            val = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM no_shift_requisites_blocks
                WHERE created_at >= $1
                  AND created_at < $2
                """,
                since,
                until,
            )
        return int(val or 0)


async def get_no_shift_period_start() -> datetime | None:
    """Момент, когда активная команда перестала покрывать обе роли."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        active = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT roles.role)
                       FILTER (WHERE roles.role IN ('client', 'finance')) >= 2
            FROM operator_shifts s
            JOIN operator_accounts a ON a.id = s.operator_id
            CROSS JOIN LATERAL unnest(
                CASE
                    WHEN a.operator_roles IS NULL OR cardinality(a.operator_roles) = 0
                    THEN ARRAY[COALESCE(a.operator_role, 'client')]::text[]
                    ELSE a.operator_roles
                END
            ) AS roles(role)
            WHERE s.ended_at IS NULL AND a.is_active = TRUE
            """
        )
        if active:
            return None
        return await conn.fetchval(
            """
            SELECT MAX(s.ended_at)
            FROM operator_shifts s
            JOIN operator_accounts a ON a.id = s.operator_id
            WHERE s.ended_at IS NOT NULL AND a.is_active = TRUE
            """
        )


async def count_no_shift_blocks_since_empty_shift() -> int:
    since = await get_no_shift_period_start()
    if since is None:
        return 0
    return await count_no_shift_blocks_since(since)


async def get_last_paid_order() -> asyncpg.Record | None:
    query = """
        SELECT
            order_id,
            direction,
            crypto,
            crypto_amount,
            fiat_amount,
            COALESCE(payout_confirmed_at, updated_at, created_at) AS closed_at
        FROM orders
        WHERE status = 'PAID'
        ORDER BY COALESCE(payout_confirmed_at, updated_at, created_at) DESC
        LIMIT 1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query)


async def get_open_orders_summary() -> List[asyncpg.Record]:
    query = """
        SELECT status, COUNT(*)::int AS cnt
        FROM orders
        WHERE status IN (
            'CREATED', 'AWAITING_CHECK', 'PENDING', 'COMPLETED', 'OPERATOR_PENDING'
        )
        GROUP BY status
        ORDER BY status
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query)


async def get_max_open_order_fiat() -> float | None:
    query = """
        SELECT MAX(fiat_amount)::float AS max_fiat
        FROM orders
        WHERE status IN (
            'CREATED', 'AWAITING_CHECK', 'PENDING', 'COMPLETED', 'OPERATOR_PENDING'
        )
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(query)
        return float(val) if val is not None else None


async def get_stale_completed_buy_orders(minutes: int, *, limit: int = 50) -> List[asyncpg.Record]:
    query = """
        SELECT
            order_id,
            fiat_amount,
            crypto,
            crypto_amount,
            updated_at,
            EXTRACT(EPOCH FROM (now() - updated_at)) / 60.0 AS age_minutes
        FROM orders
        WHERE direction = 'buy'
          AND status = 'COMPLETED'
          AND updated_at < now() - ($1 * interval '1 minute')
        ORDER BY updated_at
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, minutes, limit)


async def get_buy_orders_for_payfast_reconcile(
    min_age_seconds: int = 90, *, limit: int = 30
) -> List[asyncpg.Record]:
    """BUY на проверке и закрытые для клиента новые PayFast-заявки."""
    query = """
        SELECT *
        FROM orders
        WHERE direction = 'buy'
          AND (
              status IN ('AWAITING_CHECK', 'PENDING')
              OR (
                  status = 'CREATED'
                  AND expires_at <= now()
                  AND COALESCE(payment_snapshot->>'merchant_expires_at', '')
                      ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
                  AND (payment_snapshot->>'merchant_expires_at')::timestamptz > now()
              )
          )
          AND updated_at < now() - ($1 * interval '1 second')
        ORDER BY updated_at
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, min_age_seconds, limit)


async def get_orders_with_pending_receipt_send(*, limit: int = 20) -> List[asyncpg.Record]:
    """Заявки с отложенной досылкой чека после Payfast 503/timeout."""
    query = """
        SELECT *
        FROM orders
        WHERE direction = 'buy'
          AND status IN ('AWAITING_CHECK', 'PENDING')
          AND COALESCE(payment_snapshot->'receipt_send_pending'->>'receipt_name', '') <> ''
          AND COALESCE(payment_snapshot->'receipt_send_pending'->>'done_at', '') = ''
          AND (
              COALESCE(payment_snapshot->'receipt_send_pending'->>'next_try_at', '')
                  = ''
              OR NOT (
                  COALESCE(payment_snapshot->'receipt_send_pending'->>'next_try_at', '')
                      ~ '^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?(Z|[+-]\\d{2}:\\d{2})$'
              )
              OR (payment_snapshot->'receipt_send_pending'->>'next_try_at')::timestamptz <= now()
          )
        ORDER BY updated_at
        LIMIT $1
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, limit)


async def get_completed_buy_orders_for_payout_reminder(
    min_age_seconds: int = 300, *, limit: int = 50
) -> List[asyncpg.Record]:
    """BUY-заявки, подтверждённые мерчантом (COMPLETED), но ещё не выплаченные.

    Используется для напоминаний операторам раз в 5 мин, пока крипта не отправлена
    (статус перейдёт в PAID/CANCELED и заявка выпадет из выборки)."""
    query = """
        SELECT *
        FROM orders
        WHERE direction = 'buy'
          AND status = 'COMPLETED'
          AND updated_at < now() - ($1 * interval '1 second')
        ORDER BY updated_at
        LIMIT $2
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, min_age_seconds, limit)


async def get_negative_ledger_accounts() -> list[dict]:
    """Счета с отрицательным балансом леджера — признак over-spend/over-hold.

    Внутренние проверки доступности больше не маскируются max(0,...); этот запрос
    нужен для алёрта владельцу, чтобы быстро ловить рассинхрон баланса.
    """
    query = """
        SELECT 'cashback' AS kind, user_id::text AS ref, SUM(amount_rub)::float AS bal
        FROM user_cashback_ledger GROUP BY user_id HAVING SUM(amount_rub) < -0.01
        UNION ALL
        SELECT 'referral', referrer_user_id::text, SUM(amount_rub)::float
        FROM user_referral_ledger GROUP BY referrer_user_id HAVING SUM(amount_rub) < -0.01
        UNION ALL
        SELECT 'partner', campaign_id::text, SUM(amount_rub)::float
        FROM partner_ledger GROUP BY campaign_id HAVING SUM(amount_rub) < -0.01
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return [dict(r) for r in rows]


def _audience_since_clause(days: int, column: str) -> tuple[str, list]:
    """Условие «за последние days календарных дней» (включая сегодня)."""
    if days <= 1:
        return f"{column}::date = CURRENT_DATE", []
    return f"{column} >= CURRENT_DATE - ($1 - 1) * interval '1 day'", [days]


async def count_bot_new_users(days: int = 1) -> int:
    where, params = _audience_since_clause(days, "first_seen_at")
    query = f"SELECT COUNT(*)::int FROM bot_users WHERE {where}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, *params) or 0)


async def count_bot_active_users(days: int = 1) -> int:
    where, params = _audience_since_clause(days, "last_seen_at")
    query = f"SELECT COUNT(*)::int FROM bot_users WHERE {where}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, *params) or 0)


async def get_recent_bot_new_users(days: int = 1, *, limit: int = 15) -> List[asyncpg.Record]:
    where, params = _audience_since_clause(days, "first_seen_at")
    query = f"""
        SELECT user_id, username, first_name, first_seen_at
        FROM bot_users
        WHERE {where}
        ORDER BY first_seen_at DESC
        LIMIT ${len(params) + 1}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *params, limit)


async def count_web_unique_ips(days: int = 1) -> int:
    where, params = _audience_since_clause(days, "created_at")
    query = f"""
        SELECT COUNT(DISTINCT ip_address)::int
        FROM web_order_ip_log
        WHERE {where}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return int(await conn.fetchval(query, *params) or 0)
        except Exception:
            return 0


async def count_web_guest_sessions(days: int = 1) -> int:
    where, params = _audience_since_clause(days, "created_at")
    query = f"SELECT COUNT(*)::int FROM web_guest_sessions WHERE {where}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return int(await conn.fetchval(query, *params) or 0)
        except Exception:
            return 0


async def count_web_new_registrations(days: int = 1) -> int:
    where, params = _audience_since_clause(days, "created_at")
    query = f"""
        SELECT COUNT(*)::int FROM web_users
        WHERE is_admin IS NOT TRUE AND {where}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return int(await conn.fetchval(query, *params) or 0)
        except Exception:
            return 0


async def count_funnel_starts(days: int = 1) -> int:
    return await count_bot_new_users(days)


async def count_funnel_created_order(days: int = 1) -> int:
    """Заявки только среди новых /start за период (иначе конверсия >100%)."""
    order_where, params = _audience_since_clause(days, "o.created_at")
    first_where, first_params = _audience_since_clause(days, "b.first_seen_at")
    # сдвигаем плейсхолдеры $N для второго условия, если days > 1
    if first_params:
        first_where = first_where.replace("$1", f"${len(params) + 1}")
        params = list(params) + list(first_params)
    query = f"""
        SELECT COUNT(DISTINCT o.user_id)::int
        FROM orders o
        JOIN bot_users b ON b.user_id = o.user_id
        WHERE o.user_id IS NOT NULL
          AND ({order_where})
          AND ({first_where})
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, *params) or 0)


async def count_funnel_paid_users(days: int = 1) -> int:
    """PAID только среди новых /start за период (когорта = starts)."""
    paid_where, params = _audience_since_clause(
        days, "COALESCE(o.payout_confirmed_at, o.updated_at, o.created_at)"
    )
    first_where, first_params = _audience_since_clause(days, "b.first_seen_at")
    if first_params:
        first_where = first_where.replace("$1", f"${len(params) + 1}")
        params = list(params) + list(first_params)
    query = f"""
        SELECT COUNT(DISTINCT o.user_id)::int
        FROM orders o
        JOIN bot_users b ON b.user_id = o.user_id
        WHERE o.status = 'PAID' AND o.user_id IS NOT NULL
          AND ({paid_where})
          AND ({first_where})
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, *params) or 0)


async def count_stale_sell_operator_pending(minutes: int = 30) -> int:
    query = """
        SELECT COUNT(*)::int FROM orders
        WHERE direction = 'sell'
          AND status = 'OPERATOR_PENDING'
          AND updated_at < now() - ($1 * interval '1 minute')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, minutes) or 0)


async def get_top_web_ips(days: int = 1, *, limit: int = 10) -> List[asyncpg.Record]:
    where, params = _audience_since_clause(days, "created_at")
    query = f"""
        SELECT host(ip_address)::text AS ip, COUNT(*)::int AS cnt
        FROM web_order_ip_log
        WHERE {where}
        GROUP BY host(ip_address)
        ORDER BY cnt DESC
        LIMIT ${len(params) + 1}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await conn.fetch(query, *params, limit)
        except Exception:
            return []


async def count_old_pending_orders(minutes: int = 15) -> int:
    query = """
        SELECT COUNT(*)::int
        FROM orders
        WHERE status = 'PENDING'
          AND updated_at < now() - ($1 * interval '1 minute')
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(query, minutes) or 0)


async def count_terminal_orders_today() -> dict[str, int]:
    query = """
        SELECT status, COUNT(*)::int AS cnt
        FROM orders
        WHERE status IN ('EXPIRED', 'CANCELED', 'FAILED')
          AND updated_at::date = CURRENT_DATE
        GROUP BY status
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    return {str(r["status"]): int(r["cnt"]) for r in rows}

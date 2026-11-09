"""Резерв и списание рублёвого баланса под оплату по QR СБП.

Деньги клиента резервируются ДО вызова `pay`: платформа морозит средства у себя, и если
мы спишем после, два одновременных кода уедут с одного баланса. Проводки в ledger
делаются только при успехе, резерв до этого момента лишь уменьшает доступный баланс
(см. `qr_reserved_rub` в `user_unified_balance`).
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from services.db import get_pool
from services.runtime_settings import (
    qr_pay_markup_pct,
    qr_pay_max_rub_per_day,
    qr_pay_max_rub_per_tx,
)
from services.user_unified_balance import unified_available

logger = logging.getLogger("qr_pay_wallet")

LEDGER_NOTE_PREFIX = "Оплата по QR"


class QrPayError(RuntimeError):
    """Отказ по нашим правилам: баланс, лимит, состояние платежа."""


def new_merchant_transaction_id() -> str:
    return f"qr-{secrets.token_hex(8)}"


def charged_rub_for(amount_rub: float, markup_pct: float | None = None) -> float:
    """Сумма к списанию с клиента: сумма кода плюс наша наценка."""
    pct = qr_pay_markup_pct() if markup_pct is None else float(markup_pct)
    return round(float(amount_rub) * (1.0 + pct / 100.0), 2)


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def spent_today_rub(conn, user_id: int) -> float:
    """Что уже ушло или зарезервировано за сутки — база суточного лимита."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(charged_rub), 0)::float
        FROM qr_sbp_payments
        WHERE user_id = $1
          AND created_at >= $2
          AND local_status IN ('RESERVED', 'SETTLED', 'REFUNDED')
        """,
        user_id,
        since,
    )
    return float(val or 0)


async def check_limits(conn, user_id: int, charged_rub: float) -> None:
    per_tx = qr_pay_max_rub_per_tx()
    if charged_rub > per_tx + 0.01:
        raise QrPayError(f"Максимум одной оплаты — {per_tx:,.0f} ₽".replace(",", " "))
    per_day = qr_pay_max_rub_per_day()
    already = await spent_today_rub(conn, user_id)
    if already + charged_rub > per_day + 0.01:
        left = max(0.0, per_day - already)
        raise QrPayError(
            f"Лимит за сутки — {per_day:,.0f} ₽. Осталось {left:,.0f} ₽".replace(",", " ")
        )


async def record_check(
    *,
    user_id: int,
    merchant_transaction_id: str,
    qr_code: str,
    payment,
) -> dict:
    """Сохранить результат `check`. Деньги ещё не тронуты."""
    amount_rub = float(payment.amount_in_currency or 0)
    markup = qr_pay_markup_pct()
    charged = charged_rub_for(amount_rub, markup)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await check_limits(conn, user_id, charged)
        available = await unified_available(conn, user_id)
        if available + 0.01 < charged:
            raise QrPayError(
                f"Не хватает баланса: нужно {charged:,.2f} ₽, доступно {available:,.2f} ₽".replace(
                    ",", " "
                )
            )
        row = await conn.fetchrow(
            """
            INSERT INTO qr_sbp_payments (
                merchant_transaction_id, provider_transaction_id, user_id, qr_code,
                payee_name, amount_rub, charged_rub, markup_pct, amount_usdt, fee_usdt,
                status_group, status_code, is_final, local_status,
                provider_updated_at, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'CHECKED', $14, $15)
            RETURNING *
            """,
            merchant_transaction_id,
            payment.transaction_id or None,
            user_id,
            qr_code,
            payment.payee_name,
            amount_rub,
            charged,
            markup,
            payment.amount_usdt,
            payment.fee_usdt,
            payment.status.group or None,
            payment.status.code or None,
            payment.status.is_final,
            _parse_dt(payment.updated_at),
            _parse_dt(payment.expires_at),
        )
    return dict(row)


async def webhook_already_handled(webhook_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM qr_sbp_webhook_events WHERE webhook_id = $1::uuid",
                webhook_id,
            )
        )


async def mark_webhook_handled(webhook_id: str) -> None:
    """Запоминаем только после успешной обработки, чтобы повтор после сбоя прошёл."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO qr_sbp_webhook_events (webhook_id)
            VALUES ($1::uuid)
            ON CONFLICT (webhook_id) DO NOTHING
            """,
            webhook_id,
        )


async def get_payment(merchant_transaction_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qr_sbp_payments WHERE merchant_transaction_id = $1",
            merchant_transaction_id,
        )
    return dict(row) if row else None


async def get_payment_by_provider(provider_transaction_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qr_sbp_payments WHERE provider_transaction_id = $1",
            provider_transaction_id,
        )
    return dict(row) if row else None


async def reserve(*, merchant_transaction_id: str, user_id: int) -> dict:
    """Перевести платёж в RESERVED под advisory lock. Вызывать строго до `pay`."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", int(user_id))
            row = await conn.fetchrow(
                """
                SELECT * FROM qr_sbp_payments
                WHERE merchant_transaction_id = $1 AND user_id = $2
                """,
                merchant_transaction_id,
                user_id,
            )
            if not row:
                raise QrPayError("Платёж не найден.")
            payment = dict(row)
            if payment["local_status"] != "CHECKED":
                raise QrPayError("Этот код уже отправлен в оплату.")
            expires_at = _parse_dt(payment.get("expires_at"))
            if not expires_at or expires_at <= datetime.now(timezone.utc):
                raise QrPayError("Проверка кода истекла, отсканируйте заново.")
            if str(payment.get("status_code") or "") != "CHECKED":
                raise QrPayError("Этот код нельзя оплатить.")

            charged = float(payment["charged_rub"] or 0)
            await check_limits(conn, user_id, charged)
            available = await unified_available(conn, user_id)
            if available + 0.01 < charged:
                raise QrPayError(
                    f"Не хватает баланса: нужно {charged:,.2f} ₽, "
                    f"доступно {available:,.2f} ₽".replace(",", " ")
                )
            updated = await conn.fetchrow(
                """
                UPDATE qr_sbp_payments
                SET local_status = 'RESERVED', updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                payment["id"],
            )
    return dict(updated)


async def _cascade_spend(conn, user_id: int, amount_rub: float, note: str) -> dict:
    """Списать кешбэк → рефералку → партнёрский ledger. Возвращает split для возврата."""
    from services.user_unified_balance import _partner_parts

    amount = round(float(amount_rub), 2)
    cashback = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger WHERE user_id = $1",
        user_id,
    )
    from_cb = min(max(0.0, float(cashback or 0)), amount)
    remainder = round(amount - from_cb, 2)

    referral = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_ledger WHERE referrer_user_id = $1
        """,
        user_id,
    )
    from_ref = min(max(0.0, float(referral or 0)), remainder)
    from_partner = round(remainder - from_ref, 2)

    split: dict[str, float | int | None] = {
        "cashback": from_cb,
        "referral": from_ref,
        "partner": from_partner,
        "campaign_id": None,
    }

    if from_cb > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
            VALUES ($1, 'spend', $2, $3)
            """,
            user_id,
            -from_cb,
            note,
        )
    if from_ref > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, note)
            VALUES ($1, 'spend', $2, $3)
            """,
            user_id,
            -from_ref,
            note,
        )
    if from_partner > 0:
        partner = await _partner_parts(conn, user_id)
        campaign_id = partner.get("campaign_id")
        if not campaign_id or from_partner > partner["balance_rub"] + 0.01:
            raise QrPayError("Недостаточно баланса для оплаты.")
        await conn.execute("SELECT pg_advisory_xact_lock($1)", int(campaign_id))
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
            VALUES ($1, 'spend', $2, $3)
            """,
            int(campaign_id),
            -from_partner,
            note,
        )
        split["campaign_id"] = int(campaign_id)
    return split


async def settle(merchant_transaction_id: str) -> dict | None:
    """Выплата прошла: списать резерв проводками. Идемпотентно."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM qr_sbp_payments
                WHERE merchant_transaction_id = $1
                FOR UPDATE
                """,
                merchant_transaction_id,
            )
            if not row:
                return None
            payment = dict(row)
            if payment["local_status"] != "RESERVED":
                return payment
            user_id = int(payment["user_id"])
            await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
            note = f"{LEDGER_NOTE_PREFIX} {merchant_transaction_id}"
            split = await _cascade_spend(conn, user_id, float(payment["charged_rub"] or 0), note)
            updated = await conn.fetchrow(
                """
                UPDATE qr_sbp_payments
                SET local_status = 'SETTLED',
                    charge_split = $2,
                    settled_at = now(),
                    updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                payment["id"],
                json.dumps(split),
            )
    return dict(updated)


async def release(merchant_transaction_id: str) -> dict | None:
    """Отказ или сбой: резерв снят, проводок не было, баланс возвращается сам."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE qr_sbp_payments
            SET local_status = 'RELEASED', updated_at = now()
            WHERE merchant_transaction_id = $1
              AND local_status IN ('CHECKED', 'RESERVED')
            RETURNING *
            """,
            merchant_transaction_id,
        )
        if row:
            return dict(row)
        existing = await conn.fetchrow(
            "SELECT * FROM qr_sbp_payments WHERE merchant_transaction_id = $1",
            merchant_transaction_id,
        )
    return dict(existing) if existing else None


async def refund(merchant_transaction_id: str) -> dict | None:
    """Возврат проведённой выплаты: вернуть деньги теми же частями, что списали."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM qr_sbp_payments
                WHERE merchant_transaction_id = $1
                FOR UPDATE
                """,
                merchant_transaction_id,
            )
            if not row:
                return None
            payment = dict(row)
            if payment["local_status"] == "REFUNDED":
                return payment
            if payment["local_status"] != "SETTLED":
                # Проводок не было — достаточно снять резерв.
                updated = await conn.fetchrow(
                    """
                    UPDATE qr_sbp_payments
                    SET local_status = 'REFUNDED', updated_at = now()
                    WHERE id = $1
                    RETURNING *
                    """,
                    payment["id"],
                )
                return dict(updated)

            user_id = int(payment["user_id"])
            await conn.execute("SELECT pg_advisory_xact_lock($1)", user_id)
            raw_split = payment.get("charge_split")
            if isinstance(raw_split, str):
                raw_split = json.loads(raw_split)
            split = raw_split if isinstance(raw_split, dict) else {}
            note = f"Возврат оплаты по QR {merchant_transaction_id}"

            from_cb = float(split.get("cashback") or 0)
            from_ref = float(split.get("referral") or 0)
            from_partner = float(split.get("partner") or 0)
            campaign_id = split.get("campaign_id")
            if from_cb <= 0 and from_ref <= 0 and from_partner <= 0:
                # Сплита нет (старая запись) — возвращаем всё в кешбэк, сумма та же.
                from_cb = float(payment["charged_rub"] or 0)

            if from_cb > 0:
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    user_id,
                    from_cb,
                    note,
                )
            if from_ref > 0:
                await conn.execute(
                    """
                    INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    user_id,
                    from_ref,
                    note,
                )
            if from_partner > 0 and campaign_id:
                await conn.execute(
                    """
                    INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
                    VALUES ($1, 'adjustment', $2, $3)
                    """,
                    int(campaign_id),
                    from_partner,
                    note,
                )
            updated = await conn.fetchrow(
                """
                UPDATE qr_sbp_payments
                SET local_status = 'REFUNDED', updated_at = now()
                WHERE id = $1
                RETURNING *
                """,
                payment["id"],
            )
    return dict(updated)


async def apply_provider_status(
    merchant_transaction_id: str,
    payment,
) -> tuple[dict | None, bool]:
    """Записать статус платформы. Применяем только если `updated_at` новее нашего.

    Возвращает (строка платежа, применён ли статус).
    """
    provider_updated = _parse_dt(payment.updated_at)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM qr_sbp_payments WHERE merchant_transaction_id = $1",
            merchant_transaction_id,
        )
        if not row:
            return None, False
        stored = dict(row)
        known = _parse_dt(stored.get("provider_updated_at"))
        if provider_updated and known and provider_updated <= known:
            logger.info(
                "qr pay %s: stale provider status %s <= %s",
                merchant_transaction_id,
                provider_updated,
                known,
            )
            return stored, False
        updated = await conn.fetchrow(
            """
            UPDATE qr_sbp_payments
            SET status_group = $2,
                status_code = $3,
                is_final = $4,
                provider_transaction_id = COALESCE(provider_transaction_id, $5),
                amount_usdt = COALESCE($6, amount_usdt),
                fee_usdt = COALESCE($7, fee_usdt),
                provider_updated_at = COALESCE($8, provider_updated_at),
                updated_at = now()
            WHERE id = $1
            RETURNING *
            """,
            stored["id"],
            payment.status.group or None,
            payment.status.code or None,
            payment.status.is_final,
            payment.transaction_id or None,
            payment.amount_usdt,
            payment.fee_usdt,
            provider_updated,
        )
    return dict(updated), True

"""Заявки на вывод реферального баланса."""
import html
import logging

import asyncpg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import config_rates
from services.callback_signatures import sign_withdrawal, verify_withdrawal_signature
from services.crypto_network_fee import (
    min_crypto_amount_rub,
    min_withdraw_usd,
    payout_from_fee,
    resolve_usdt_rub,
    withdraw_fee_rub,
)
from services.db import get_pool

logger = logging.getLogger("user_referral_withdraw")

SOURCE_BALANCE = "balance"
SOURCE_CASINO = "casino"
ALLOWED_SOURCES = frozenset({SOURCE_BALANCE, SOURCE_CASINO})


def normalize_withdrawal_source(raw: object) -> str:
    value = str(raw or SOURCE_BALANCE).strip().lower()
    if value not in ALLOWED_SOURCES:
        raise ValueError("Неверный источник вывода")
    return value


def is_casino_withdrawal(row: dict | None) -> bool:
    if not row:
        return False
    return str(row.get("source") or SOURCE_BALANCE).strip().lower() == SOURCE_CASINO


def min_card_withdraw_rub(source: str | None) -> int:
    """Карта везде от одного минимума: кабинет, рефералка, казино, партнёры."""
    _ = source
    from services.runtime_settings import min_withdraw_card_rub

    return min_withdraw_card_rub()


def ops_path_for_withdrawal(row: dict | None) -> str:
    return "/ops/casino-payouts" if is_casino_withdrawal(row) else "/ops/orders"


async def _available_balance_locked(conn, referrer_user_id: int) -> float:
    from services.user_unified_balance import unified_available

    return await unified_available(conn, referrer_user_id)


async def _lock_and_check_pending(conn, referrer_user_id: int) -> None:
    from services.user_unified_balance import get_partner_campaign_conn

    await conn.execute(
        "SELECT pg_advisory_xact_lock($1)",
        referrer_user_id,
    )
    if await conn.fetchval(
        """
        SELECT 1 FROM user_referral_withdrawals
        WHERE referrer_user_id = $1
          AND status IN ('pending', 'reserved', 'sending')
        LIMIT 1
        """,
        referrer_user_id,
    ):
        raise ValueError("У вас уже есть заявка на вывод в обработке")

    campaign = await get_partner_campaign_conn(conn, referrer_user_id)
    if campaign:
        campaign_id = int(campaign["campaign_id"])
        await conn.execute(
            "SELECT pg_advisory_xact_lock($1)",
            campaign_id,
        )
        if await conn.fetchval(
            """
            SELECT 1 FROM partner_withdrawals
            WHERE campaign_id = $1
              AND status IN ('pending', 'reserved', 'sending')
            LIMIT 1
            """,
            campaign_id,
        ):
            raise ValueError("У вас уже есть заявка на вывод в обработке")


def format_crypto_withdraw_limits(crypto: str) -> str:
    return f"${min_withdraw_usd(crypto):g}"


async def preview_crypto_withdraw(
    amount_rub: float, crypto: str, source: str | None = None
) -> tuple[float, float]:
    """(network_fee_rub, payout_amount_rub) по текущему курсу USDT."""
    usdt_rub = await resolve_usdt_rub()
    fee = withdraw_fee_rub("crypto", crypto, usdt_rub=usdt_rub, source=source)
    payout = payout_from_fee(amount_rub, fee)
    return fee, payout


async def create_withdrawal(
    *,
    referrer_user_id: int,
    amount_rub: float,
    method: str,
    requisites: str,
    crypto: str | None = None,
    network: str | None = None,
    source: str | None = None,
) -> dict:
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        raise ValueError("Укажите сумму больше нуля")

    method = method.lower()
    network_fee = 0.0
    payout_rub: float | None = None
    origin = normalize_withdrawal_source(source)

    if method == "card":
        min_card = min_card_withdraw_rub(origin)
        if amount < min_card:
            raise ValueError(f"Минимум для карты: {min_card:,.0f} ₽".replace(",", " "))
        network_fee = withdraw_fee_rub("card", None, usdt_rub=None, source=origin)
        if network_fee > 0:
            payout_rub = payout_from_fee(amount, network_fee)
            if payout_rub <= 0:
                raise ValueError(
                    f"Сумма слишком мала: комиссия {network_fee:,.2f} ₽. "
                    "Увеличьте сумму вывода."
                )
    elif method == "crypto":
        if not crypto:
            raise ValueError("Укажите криптовалюту")
        from services.wallet_validation import clean_crypto_address

        requisites = clean_crypto_address(requisites)
        min_rub = await min_crypto_amount_rub(crypto)
        if amount < min_rub - 0.01:
            raise ValueError(
                f"Минимум для крипты: ~{min_rub:,.0f} ₽ "
                f"({format_crypto_withdraw_limits(crypto)} в {crypto.upper()})"
            )
        usdt_rub = await resolve_usdt_rub()
        network_fee = withdraw_fee_rub(
            "crypto", crypto, usdt_rub=usdt_rub, source=origin
        )
        payout_rub = payout_from_fee(amount, network_fee)
        if payout_rub <= 0:
            raise ValueError(
                f"Сумма слишком мала: комиссия сети {network_fee:,.2f} ₽. "
                "Увеличьте сумму вывода."
            )
    else:
        raise ValueError("Неверный способ вывода")

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _lock_and_check_pending(conn, referrer_user_id)

                if method == "crypto":
                    from services.casino_payout_rail import assert_crypto_withdraw_allowed

                    await assert_crypto_withdraw_allowed(conn, referrer_user_id)

                available = await _available_balance_locked(conn, referrer_user_id)
                if amount > available + 0.01:
                    raise ValueError(
                        f"Недостаточно средств. Доступно: {available:,.2f} ₽"
                    )

                row = await conn.fetchrow(
                    """
                    INSERT INTO user_referral_withdrawals (
                        referrer_user_id, amount_rub, method, requisites, crypto, network,
                        status, network_fee_rub, payout_amount_rub, source
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9)
                    RETURNING *
                    """,
                    referrer_user_id,
                    amount,
                    method,
                    requisites.strip(),
                    crypto,
                    network,
                    network_fee,
                    payout_rub,
                    origin,
                )
        wd = dict(row)
        if method == "crypto" and origin == SOURCE_BALANCE:
            wd = await _try_backend_auto_reserve(wd)
        return wd
    except asyncpg.UniqueViolationError:
        raise ValueError("У вас уже есть заявка на вывод в обработке") from None


async def _try_backend_auto_reserve(wd: dict) -> dict:
    """После insert — тот же auto-reserve, что у кабинетного API."""
    from services.auto_withdraw_client import request_auto_reserve

    wid = int(wd["id"])
    result = await request_auto_reserve(wid)
    if not result:
        return wd
    outcome = str(result.get("outcome") or "")
    if outcome == "reject":
        reason = str(result.get("reason") or "").strip()
        if reason and reason not in ("banned", "risk"):
            raise ValueError(reason)
        raise ValueError(
            "Вывод недоступен для вашего аккаунта. Напишите в поддержку."
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        refreshed = await conn.fetchrow(
            "SELECT * FROM user_referral_withdrawals WHERE id = $1",
            wid,
        )
    return dict(refreshed) if refreshed else wd


def _crypto_explorer_key(wd: dict) -> str:
    c = (wd.get("crypto") or "").lower()
    n = (wd.get("network") or "").lower()
    if n:
        return f"{c}_{n}"
    return c


def format_withdrawal_admin_message(wd: dict, referrer_username: str | None) -> str:
    from services.order_ops_notify import (
        OPS_MSG_SEPARATOR,
        format_ops_tx_html,
        format_ops_user_line,
        operator_url,
    )

    method = wd["method"]
    if method == "card":
        method_line = "💳 Карта / СБП"
    else:
        net = wd.get("network") or ""
        method_line = f"🪙 Крипта: {wd.get('crypto', '').upper()} {net.upper()}".strip()

    requisites = html.escape(str(wd["requisites"] or ""))
    lines = [
        f"<b>💸 Заявка на {'вывод FocusBet' if is_casino_withdrawal(wd) else 'вывод баланса'}</b> · #{wd['id']}",
        OPS_MSG_SEPARATOR,
        "",
        format_ops_user_line(
            wd.get("referrer_user_id"),
            username=referrer_username,
            include_id=True,
        ),
        method_line,
        f"👛 <code>{requisites}</code>",
    ]
    amount = float(wd["amount_rub"])
    fee = float(wd.get("network_fee_rub") or 0)
    payout = wd.get("payout_amount_rub")
    if payout is None and fee > 0:
        payout = max(0.0, amount - fee)
    if fee > 0.009 or payout is not None:
        payout_f = float(payout if payout is not None else amount)
        dest = ""
        if method == "crypto":
            dest = f" (в {wd.get('crypto', '').upper()} по курсу)"
        lines.extend(
            [
                f"💰 Списано с баланса: <b>{amount:,.2f} ₽</b>",
                f"⛽ Комиссия{' сети' if method == 'crypto' else ''}: <b>{fee:,.2f} ₽</b>",
                f"📤 <b>К отправке: {payout_f:,.2f} ₽</b>{dest}",
            ]
        )
    else:
        lines.append(f"💰 Сумма: <b>{amount:,.2f} ₽</b>")
    tx = wd.get("payout_tx_hash")
    if tx:
        crypto_key = _crypto_explorer_key(wd)
        tx_line = format_ops_tx_html(str(tx), crypto_key)
        if tx_line:
            lines.append(tx_line)
    lines.append(
        f'🌐 <a href="{operator_url(ops_path_for_withdrawal(wd))}">Кабинет оператора</a>'
    )
    return "\n".join(lines)


def withdrawal_admin_keyboard(withdrawal_id: int, *, source: str | None = None) -> InlineKeyboardMarkup:
    sig = sign_withdrawal(withdrawal_id)
    from services.order_ops_notify import operator_url

    panel_path = ops_path_for_withdrawal({"source": source or SOURCE_BALANCE})
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👁 Кабинет оператора", url=operator_url("/ops/login")
                ),
                InlineKeyboardButton("📋 Заявки", url=operator_url(panel_path)),
            ],
            [
                InlineKeyboardButton(
                    "✅ Выплачено",
                    callback_data=f"refwd:paid:{withdrawal_id}:{sig}",
                ),
                InlineKeyboardButton(
                    "❌ Отклонить",
                    callback_data=f"refwd:reject:{withdrawal_id}:{sig}",
                ),
            ],
        ]
    )


async def confirm_withdrawal_crypto_payout(
    withdrawal_id: int, tx_hash_raw: str
) -> tuple[bool, str | None, dict | None]:
    """Подтвердить крипто-вывод с tx hash. Возвращает (ok, error_code, wd)."""
    from services.buy_payout import normalize_tx_hash

    normalized = normalize_tx_hash(tx_hash_raw)
    if not normalized:
        return False, "invalid_tx", None

    pool = await get_pool()
    async with pool.acquire() as conn:
        wd = await conn.fetchrow(
            "SELECT * FROM user_referral_withdrawals WHERE id = $1",
            withdrawal_id,
        )
    if not wd:
        return False, "not_found", None
    if wd["status"] != "pending":
        return False, "already_processed", dict(wd)
    if (wd["method"] or "").lower() != "crypto":
        return False, "not_crypto", dict(wd)

    paid = await process_withdrawal_paid(withdrawal_id, payout_tx_hash=normalized)
    if not paid:
        pool = await get_pool()
        async with pool.acquire() as conn:
            from services.user_unified_balance import unified_available

            wd2 = await conn.fetchrow(
                "SELECT referrer_user_id, amount_rub FROM user_referral_withdrawals WHERE id = $1",
                withdrawal_id,
            )
            if wd2:
                avail = await unified_available(conn, int(wd2["referrer_user_id"]))
                avail += float(wd2["amount_rub"])
                if float(wd2["amount_rub"]) > avail + 0.01:
                    return False, "insufficient_balance", None
        return False, "process_failed", None
    return True, None, paid


async def process_withdrawal_paid(
    withdrawal_id: int, *, payout_tx_hash: str | None = None
) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            wd = await conn.fetchrow(
                """
                SELECT * FROM user_referral_withdrawals
                WHERE id = $1 FOR UPDATE
                """,
                withdrawal_id,
            )
            if not wd or wd["status"] != "pending":
                return None

            from services.user_unified_balance import deduct_unified_payout, unified_available

            available = await unified_available(conn, int(wd["referrer_user_id"]))
            # Эта же pending-заявка уже вычтена из available — при подтверждении не резервируем повторно
            available += float(wd["amount_rub"])
            if float(wd["amount_rub"]) > available + 0.01:
                logger.warning(
                    "Withdrawal #%s rejected: insufficient balance %.2f (need %.2f)",
                    withdrawal_id,
                    available,
                    float(wd["amount_rub"]),
                )
                return None

            await deduct_unified_payout(
                conn, int(wd["referrer_user_id"]), float(wd["amount_rub"]), withdrawal_id
            )
            await conn.execute(
                """
                UPDATE user_referral_withdrawals
                SET status = 'paid', processed_at = now(), payout_tx_hash = $2
                WHERE id = $1
                """,
                withdrawal_id,
                payout_tx_hash,
            )
            await conn.execute(
                """
                UPDATE bot_users
                SET account_review_status = 'approved',
                    account_reviewed_at = COALESCE(account_reviewed_at, now()),
                    account_review_reason = COALESCE(account_review_reason, 'auto_paid')
                WHERE user_id = $1
                  AND COALESCE(account_review_status, 'none') = 'pending'
                """,
                int(wd["referrer_user_id"]),
            )
            out = dict(wd)
            if payout_tx_hash:
                out["payout_tx_hash"] = payout_tx_hash
            return out


async def process_withdrawal_rejected(withdrawal_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        wd = await conn.fetchrow(
            """
            UPDATE user_referral_withdrawals
            SET status = 'rejected', processed_at = now()
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            withdrawal_id,
        )
    return dict(wd) if wd else None


async def get_withdrawal(withdrawal_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM user_referral_withdrawals WHERE id = $1",
            withdrawal_id,
        )


async def claim_withdrawal(withdrawal_id: int, operator_id: int) -> dict | None:
    """Взять pending-вывод в работу (кабинет оператора)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE user_referral_withdrawals
            SET operator_id = $2
            WHERE id = $1
              AND status = 'pending'
              AND operator_id IS NULL
            RETURNING *
            """,
            withdrawal_id,
            operator_id,
        )
    return dict(row) if row else None

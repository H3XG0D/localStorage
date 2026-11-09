"""Заявки на вывод реферального баланса (сайт + TG + кабинет оператора)."""
import html
import logging
import math
from datetime import datetime, timedelta, timezone

import asyncpg

from config import settings
from crypto_network_fee import (
    format_crypto_withdraw_limits,
    min_crypto_amount_rub,
    payout_from_fee,
    resolve_usdt_rub,
    withdraw_fee_rub,
)
from db import get_pool

logger = logging.getLogger("user_referral_withdraw")

SOURCE_BALANCE = "balance"
SOURCE_CASINO = "casino"
ALLOWED_SOURCES = frozenset({SOURCE_BALANCE, SOURCE_CASINO})
BALANCE_QUEUE_SQL = "COALESCE(source, 'balance') <> 'casino'"
CASINO_QUEUE_SQL = "COALESCE(source, 'balance') = 'casino'"

PHASE_AWAITING = "awaiting"
PHASE_PROCESSING = "processing"
PHASE_PAID = "paid"
PHASE_REJECTED = "rejected"
PHASE_CANCELED = "canceled"

PLAYER_STATUS: dict[str, dict[str, object]] = {
    PHASE_AWAITING: {
        "label": "В ожидании",
        "hint": "Заявка в очереди. Можно отменить.",
        "cancellable": True,
    },
    PHASE_PROCESSING: {
        "label": "На выплате",
        "hint": "Передана на выплату. Обычно зачисляем в течение 3 часов. Отменить нельзя.",
        "cancellable": False,
    },
    PHASE_PAID: {
        "label": "Выплачено",
        "hint": "",
        "cancellable": False,
    },
    PHASE_REJECTED: {
        "label": "Отклонено",
        "hint": "Деньги на балансе.",
        "cancellable": False,
    },
    PHASE_CANCELED: {
        "label": "Отменена",
        "hint": "",
        "cancellable": False,
    },
}

_PLAYER_HIDE = ("operator_id", "admin_message_id")

CASINO_PENDING_MAX = 5
CASINO_CREATE_INTERVAL = timedelta(minutes=5)
CASINO_PENDING_MAX_MSG = "Можно держать не больше 5 заявок на вывод одновременно"


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def casino_create_wait_message(last_created_at: object, *, now: datetime | None = None) -> str | None:
    last = _as_utc(last_created_at)
    if last is None:
        return None
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    remaining = last + CASINO_CREATE_INTERVAL - current
    seconds = remaining.total_seconds()
    if seconds <= 0:
        return None
    minutes = max(1, math.ceil(seconds / 60))
    return f"Следующую заявку можно создать через {minutes} мин."


class WithdrawalCancelError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    from runtime_settings import min_withdraw_card_rub

    return min_withdraw_card_rub()


def ops_path_for_withdrawal(row: dict | None) -> str:
    return "/ops/casino-payouts" if is_casino_withdrawal(row) else "/ops/orders"


async def _available_balance_locked(conn, referrer_user_id: int) -> float:
    from casino_wagering import locked_by_wagering
    from user_unified_balance import unified_available

    available = await unified_available(conn, referrer_user_id)
    # Casino-депозиты заперты к выводу, пока не отыграны (0% комиссия на входе).
    locked = float(await locked_by_wagering(conn, referrer_user_id))
    return round(max(0.0, available - locked), 2)


async def _lock_and_check_pending(conn, referrer_user_id: int, origin: str = SOURCE_BALANCE) -> None:
    from user_unified_balance import get_partner_campaign_conn

    await conn.execute(
        "SELECT pg_advisory_xact_lock($1)",
        referrer_user_id,
    )
    if origin == SOURCE_CASINO:
        pending = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM user_referral_withdrawals
                WHERE referrer_user_id = $1
                  AND status = 'pending'
                  AND COALESCE(source, 'balance') = 'casino'
                """,
                referrer_user_id,
            )
            or 0
        )
        if pending >= CASINO_PENDING_MAX:
            raise ValueError(CASINO_PENDING_MAX_MSG)
        last_created = await conn.fetchval(
            """
            SELECT created_at FROM user_referral_withdrawals
            WHERE referrer_user_id = $1
              AND COALESCE(source, 'balance') = 'casino'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            referrer_user_id,
        )
        wait = casino_create_wait_message(last_created)
        if wait:
            raise ValueError(wait)
        return

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
        from wallet_validation import clean_crypto_address, validate_buy_wallet

        requisites = clean_crypto_address(requisites)
        try:
            validate_buy_wallet(crypto, network, requisites)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
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
                await _lock_and_check_pending(conn, referrer_user_id, origin)

                if method == "crypto":
                    from casino_payout_rail import assert_crypto_withdraw_allowed

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
        if method == "card":
            try:
                from payin_requisite_rail import open_withdrawal_triangle

                await open_withdrawal_triangle(wd)
            except Exception:
                logger.exception("triangle for withdrawal %s failed", wd.get("id"))
        if method == "crypto" and origin == SOURCE_BALANCE:
            wd = await maybe_auto_reserve_withdrawal(wd, raise_on_reject=True)
        return wd
    except asyncpg.UniqueViolationError:
        raise ValueError("У вас уже есть заявка на вывод в обработке") from None


async def _refresh_withdrawal(withdrawal_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_referral_withdrawals WHERE id = $1",
            int(withdrawal_id),
        )
    return dict(row) if row else None


async def maybe_auto_reserve_withdrawal(
    wd: dict,
    *,
    raise_on_reject: bool = False,
) -> dict:
    """Риск-гейт + reserve для crypto/balance. И API, и бот (через internal)."""
    if (wd.get("method") or "").lower() != "crypto":
        return wd
    origin = normalize_withdrawal_source(wd.get("source"))
    if origin != SOURCE_BALANCE:
        return wd
    if str(wd.get("status") or "") != "pending":
        return wd

    from auto_payout_risk import evaluate_withdraw_risk

    outcome, reason = await evaluate_withdraw_risk(
        user_id=int(wd["referrer_user_id"]),
        amount_rub=float(wd["amount_rub"]),
        method="crypto",
        requisites=str(wd.get("requisites") or "").strip(),
        crypto=wd.get("crypto"),
        network=wd.get("network"),
        source=origin,
    )
    wid = int(wd["id"])
    if outcome == "auto":
        from auto_payout_worker import PartialHoldError, reserve_withdrawal_for_auto

        try:
            await reserve_withdrawal_for_auto(wid)
        except PartialHoldError as exc:
            # Резерв не собрался целиком — заявка остаётся pending,
            # её подхватит оператор. Для клиента это обычный вывод.
            logger.warning("auto reserve skipped for #%s: %s", wid, exc)
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE user_referral_withdrawals
                    SET auto_reason = $2
                    WHERE id = $1 AND status = 'pending'
                    """,
                    wid,
                    f"partial_hold:{(reason or 'ok')}"[:200],
                )
        except Exception as exc:
            logger.exception("auto reserve failed for #%s", wid)
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE user_referral_withdrawals
                    SET auto_reason = $2
                    WHERE id = $1 AND status = 'pending'
                    """,
                    wid,
                    f"reserve_error:{type(exc).__name__}"[:200],
                )
        refreshed = await _refresh_withdrawal(wid)
        return refreshed or wd

    if outcome == "reject":
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_referral_withdrawals
                SET status = 'rejected', processed_at = now(), auto_reason = $2
                WHERE id = $1 AND status = 'pending'
                """,
                wid,
                (reason or "risk")[:200],
            )
        logger.warning("withdrawal #%s auto-rejected: %s", wid, reason)
        refreshed = await _refresh_withdrawal(wid) or wd
        if raise_on_reject:
            if reason and reason not in ("banned", "risk"):
                raise ValueError(reason)
            raise ValueError(
                "Вывод недоступен для вашего аккаунта. Напишите в поддержку."
            )
        return refreshed

    # manual — оставляем pending, пишем причину для разбора
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_referral_withdrawals
            SET auto_reason = $2
            WHERE id = $1 AND status = 'pending'
            """,
            wid,
            f"manual:{(reason or 'unknown')}"[:200],
        )
    refreshed = await _refresh_withdrawal(wid)
    return refreshed or wd


async def auto_reserve_pending_withdrawal(withdrawal_id: int) -> dict:
    """Internal/bot: прогнать уже созданную pending-заявку через авто."""
    wd = await _refresh_withdrawal(withdrawal_id)
    if not wd:
        return {"ok": False, "outcome": "missing", "reason": "not_found"}
    if str(wd.get("status") or "") != "pending":
        return {
            "ok": True,
            "outcome": "noop",
            "reason": f"status_{wd.get('status')}",
            "status": wd.get("status"),
            "withdrawal_id": int(wd["id"]),
        }
    before = str(wd.get("status") or "")
    updated = await maybe_auto_reserve_withdrawal(wd, raise_on_reject=False)
    status = str(updated.get("status") or "")
    reason = updated.get("auto_reason")
    if status == "reserved":
        outcome = "auto"
    elif status == "rejected":
        outcome = "reject"
    elif status == "pending":
        outcome = "manual"
    else:
        outcome = "noop"
    return {
        "ok": True,
        "outcome": outcome,
        "reason": reason,
        "status": status,
        "before_status": before,
        "withdrawal_id": int(updated["id"]),
    }


def format_withdrawal_admin_message(wd: dict, referrer_username: str | None) -> str:
    method = wd["method"]
    if method == "card":
        method_line = "💳 Карта / СБП"
    else:
        net = html.escape(wd.get("network") or "")
        crypto = html.escape(wd.get("crypto", ""))
        method_line = f"🪙 Крипта: {crypto.upper()} {net.upper()}".strip()

    uname = html.escape(f"@{referrer_username}" if referrer_username else f"id {wd['referrer_user_id']}")
    requisites = html.escape(str(wd["requisites"] or ""))
    title = "вывод FocusBet" if is_casino_withdrawal(wd) else "вывод баланса"
    lines = [
        f"💸 <b>Заявка на {title}</b> #{wd['id']}\n",
        f"👤 Реферер: {uname} (<code>{wd['referrer_user_id']}</code>)",
        method_line,
        f"📝 Реквизиты:\n<code>{requisites}</code>",
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
        lines.append(f"🔗 Tx: <code>{html.escape(str(tx))}</code>")
    try:
        from order_ops_notify import operator_url

        lines.append(f'🌐 <a href="{operator_url(ops_path_for_withdrawal(wd))}">Кабинет оператора</a>')
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    return "\n".join(lines)


def withdrawal_admin_inline_keyboard(withdrawal_id: int, *, source: str | None = None) -> dict:
    from callback_signatures import sign_withdrawal

    sig = sign_withdrawal(withdrawal_id)
    panel_path = ops_path_for_withdrawal({"source": source or SOURCE_BALANCE})
    try:
        from order_ops_notify import _operator_url

        panel_row = [
            {"text": "👁 Кабинет оператора", "url": _operator_url("/ops/login")},
            {"text": "📋 Заявки", "url": _operator_url(panel_path)},
        ]
    except Exception:
        panel_row = []
    rows: list[list[dict]] = []
    if panel_row:
        rows.append(panel_row)
    rows.append(
        [
            {
                "text": "✅ Выплачено",
                "callback_data": f"refwd:paid:{withdrawal_id}:{sig}",
            },
            {
                "text": "❌ Отклонить",
                "callback_data": f"refwd:reject:{withdrawal_id}:{sig}",
            },
        ]
    )
    return {"inline_keyboard": rows}


def withdrawal_out(row: dict) -> dict:
    r = dict(row)
    for key in ("created_at", "processed_at"):
        val = r.get(key)
        if val and hasattr(val, "isoformat"):
            r[key] = val.isoformat()
    return r


def withdrawal_phase(row: dict | None) -> str:
    if not row:
        return PHASE_AWAITING
    status = str(row.get("status") or "").strip().lower()
    if status == "pending":
        return PHASE_PROCESSING if row.get("operator_id") is not None else PHASE_AWAITING
    if status in {PHASE_PAID, PHASE_REJECTED, PHASE_CANCELED}:
        return status
    return status or PHASE_AWAITING


def player_status_fields(row: dict | None) -> dict[str, object]:
    phase = withdrawal_phase(row)
    copy = PLAYER_STATUS.get(phase) or PLAYER_STATUS[PHASE_AWAITING]
    cancellable = bool(copy["cancellable"]) and is_casino_withdrawal(row) and phase == PHASE_AWAITING
    return {
        "phase": phase,
        "cancellable": cancellable,
        "status_label": copy["label"],
        "status_hint": copy["hint"],
    }


def player_withdrawal_out(row: dict) -> dict:
    r = withdrawal_out(row)
    r.update(player_status_fields(row))
    for key in _PLAYER_HIDE:
        r.pop(key, None)
    return r


async def claim_withdrawal(withdrawal_id: int, operator_id: int) -> dict | None:
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


def _bot_payout_utils():
    import os
    import sys

    root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    if root not in sys.path:
        sys.path.insert(0, root)
    from services.buy_payout import build_explorer_url, normalize_tx_hash

    return normalize_tx_hash, build_explorer_url


async def confirm_withdrawal_crypto_payout(
    withdrawal_id: int, tx_hash_raw: str
) -> tuple[bool, str | None, dict | None]:
    normalize_tx_hash, _ = _bot_payout_utils()
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
    if wd["status"] in ("reserved", "sending"):
        # Выплату ведёт автопилот: ручная отправка здесь = двойная выплата.
        return False, "auto_in_progress", dict(wd)
    if wd["status"] != "pending":
        return False, "already_processed", dict(wd)
    if (wd["method"] or "").lower() != "crypto":
        return False, "not_crypto", dict(wd)

    paid, err = await process_withdrawal_paid(withdrawal_id, payout_tx_hash=normalized)
    if err == "insufficient_balance":
        return False, "insufficient_balance", None
    if not paid:
        return False, "process_failed", None
    return True, None, paid


async def process_withdrawal_paid(
    withdrawal_id: int,
    *,
    payout_tx_hash: str | None = None,
    from_autopilot: bool = False,
) -> tuple[dict | None, str | None]:
    # Ручные кнопки закрывают только pending; reserved/sending — только воркер.
    allowed = ("pending", "reserved", "sending") if from_autopilot else ("pending",)
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
            if not wd or wd["status"] not in allowed:
                return None, None

            from casino_wagering import locked_by_wagering
            from user_unified_balance import deduct_unified_payout, unified_available

            if wd["status"] in ("reserved", "sending"):
                from auto_withdraw_holds import release_withdrawal_holds

                await release_withdrawal_holds(conn, withdrawal_id)

            available = await unified_available(conn, int(wd["referrer_user_id"]))
            # pending включает эту же заявку — при подтверждении не считаем её резервом
            if wd["status"] == "pending":
                available += float(wd["amount_rub"])
            # Не выплачиваем из запертого отыгрышем casino-депозита.
            available -= float(await locked_by_wagering(conn, int(wd["referrer_user_id"])))
            if float(wd["amount_rub"]) > available + 0.01:
                logger.warning(
                    "Withdrawal #%s rejected: insufficient balance %.2f (need %.2f)",
                    withdrawal_id,
                    available,
                    float(wd["amount_rub"]),
                )
                return None, "insufficient_balance"

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
            out["status"] = "paid"
            return out, None


TRIANGLE_LIVE_STATUSES = ("QUEUED", "OPEN", "RESERVED", "PARTIAL")


async def triangle_has_paid_check(conn, withdrawal_id: int) -> bool:
    value = await conn.fetchval(
        """
        SELECT 1
        FROM payout_requisite_allocations a
        JOIN operator_payout_requisites r ON r.id = a.requisite_id
        WHERE r.source_withdrawal_id = $1
          AND a.status = 'PAID'
        LIMIT 1
        """,
        int(withdrawal_id),
    )
    return value is not None


async def release_empty_withdrawal_triangle(conn, withdrawal_id: int) -> None:
    """Гасит живую карту вывода. Оплаченный чек отмену запрещает."""
    if await triangle_has_paid_check(conn, withdrawal_id):
        raise WithdrawalCancelError(
            "triangle_paid",
            "По карте уже есть оплата, отменить вывод нельзя",
        )
    await conn.execute(
        """
        UPDATE operator_payout_requisites
        SET status = 'CANCELED',
            closed_at = now(),
            close_note = 'вывод отменён',
            updated_at = now()
        WHERE source_withdrawal_id = $1
          AND status = ANY($2::text[])
        """,
        int(withdrawal_id),
        list(TRIANGLE_LIVE_STATUSES),
    )


async def manual_triangle_payout_error(conn, withdrawal_id: int) -> str | None:
    """Ручная отметка оплаты, пока карта в приёме или по ней уже есть чек."""
    if await triangle_has_paid_check(conn, withdrawal_id):
        return "По карте уже есть оплата. Вывод закроется вместе с приёмом."
    live = await conn.fetchval(
        """
        SELECT 1 FROM operator_payout_requisites
        WHERE source_withdrawal_id = $1
          AND status = ANY($2::text[])
        LIMIT 1
        """,
        int(withdrawal_id),
        list(TRIANGLE_LIVE_STATUSES),
    )
    if live is not None:
        return "Карта уже в приёме. Дождитесь оплат или снимите пустую карту в Реквизитах."
    return None


async def process_withdrawal_rejected(withdrawal_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await release_empty_withdrawal_triangle(conn, withdrawal_id)
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


async def cancel_casino_withdrawal(user_id: int, withdrawal_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            wd = await conn.fetchrow(
                """
                SELECT * FROM user_referral_withdrawals
                WHERE id = $1 FOR UPDATE
                """,
                int(withdrawal_id),
            )
            if (
                not wd
                or int(wd["referrer_user_id"]) != int(user_id)
                or not is_casino_withdrawal(dict(wd))
            ):
                raise WithdrawalCancelError("not_found", "Заявка не найдена")
            if str(wd["status"]) != "pending" or wd.get("operator_id") is not None:
                raise WithdrawalCancelError("not_cancellable", "Заявку уже нельзя отменить")
            await release_empty_withdrawal_triangle(conn, int(withdrawal_id))
            row = await conn.fetchrow(
                """
                UPDATE user_referral_withdrawals
                SET status = 'canceled', processed_at = now()
                WHERE id = $1
                  AND status = 'pending'
                  AND operator_id IS NULL
                RETURNING *
                """,
                int(withdrawal_id),
            )
    if not row:
        raise WithdrawalCancelError("not_cancellable", "Заявку уже нельзя отменить")
    return dict(row)


async def list_user_withdrawals(
    user_id: int, *, limit: int = 30, source: str | None = None
) -> list[dict]:
    origin = normalize_withdrawal_source(source) if source is not None else None
    pool = await get_pool()
    async with pool.acquire() as conn:
        if origin is None:
            rows = await conn.fetch(
                """
                SELECT id, amount_rub, method, requisites, crypto, network, status,
                       network_fee_rub, payout_amount_rub, source, created_at, processed_at,
                       payout_tx_hash, operator_id
                FROM user_referral_withdrawals
                WHERE referrer_user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                int(user_id),
                int(limit),
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, amount_rub, method, requisites, crypto, network, status,
                       network_fee_rub, payout_amount_rub, source, created_at, processed_at,
                       payout_tx_hash, operator_id
                FROM user_referral_withdrawals
                WHERE referrer_user_id = $1
                  AND COALESCE(source, 'balance') = $2
                ORDER BY created_at DESC
                LIMIT $3
                """,
                int(user_id),
                origin,
                int(limit),
            )
    return [player_withdrawal_out(dict(row)) for row in rows]


async def get_withdrawal(withdrawal_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM user_referral_withdrawals WHERE id = $1",
            withdrawal_id,
        )


async def notify_withdrawal_rejected(wd: dict) -> None:
    from telegram_notify import edit_admin_message, send_user_message

    wid = int(wd["id"])
    uid = int(wd["referrer_user_id"])
    await send_user_message(
        uid,
        f"❌ Заявка на вывод #{wid} отклонена. Средства остаются на балансе.",
    )
    admin_msg_id = wd.get("admin_message_id")
    if admin_msg_id:
        wd_full = await get_withdrawal(wid)
        if wd_full:
            body = format_withdrawal_admin_message(dict(wd_full), None)
            await edit_admin_message(
                int(admin_msg_id),
                f"{body}\n\n❌ <b>Отклонено</b>",
                reply_markup=None,
            )


async def notify_withdrawal_canceled(wd: dict) -> None:
    from telegram_notify import edit_admin_message, send_user_message

    wid = int(wd["id"])
    uid = int(wd["referrer_user_id"])
    await send_user_message(
        uid,
        f"Заявка на вывод #{wid} отменена. Средства снова на балансе.",
    )
    admin_msg_id = wd.get("admin_message_id")
    if admin_msg_id:
        wd_full = await get_withdrawal(wid)
        if wd_full:
            body = format_withdrawal_admin_message(dict(wd_full), None)
            await edit_admin_message(
                int(admin_msg_id),
                f"{body}\n\nЗаявка отменена игроком",
                reply_markup=None,
            )


def _triangle_done_line(
    *,
    card_paid_rub: float | None,
    balance_return_rub: float | None,
    subsidy_rub: float | None,
) -> str | None:
    if card_paid_rub is None:
        return None
    paid = f"{float(card_paid_rub):,.0f}".replace(",", " ")
    returned = float(balance_return_rub or 0)
    subsidy = float(subsidy_rub or 0)
    if returned > 0:
        back = f"{returned:,.0f}".replace(",", " ")
        return f"На карту пришло {paid} ₽. {back} ₽ зачислены на баланс."
    if subsidy > 0:
        return f"На карту пришло {paid} ₽. Разницу доплатил FocusPay."
    return f"На карту пришло {paid} ₽."


async def notify_withdrawal_completed(
    wd: dict,
    *,
    tx_hash: str | None = None,
    card_paid_rub: float | None = None,
    balance_return_rub: float | None = None,
    subsidy_rub: float | None = None,
) -> None:
    """Уведомить клиента и обновить сообщение в админ-группе."""
    _, build_explorer_url = _bot_payout_utils()
    from telegram_notify import edit_admin_message, send_user_message

    wid = int(wd["id"])
    amount = float(wd["amount_rub"])
    uid = int(wd["referrer_user_id"])
    explorer = ""
    if tx_hash and (wd.get("method") or "").lower() == "crypto":
        c = (wd.get("crypto") or "").lower()
        n = (wd.get("network") or "").lower()
        key = f"{c}_{n}" if n else c
        explorer = build_explorer_url(key, tx_hash)

    done = _triangle_done_line(
        card_paid_rub=card_paid_rub,
        balance_return_rub=balance_return_rub,
        subsidy_rub=subsidy_rub,
    )
    if done:
        user_text = f"✅ Ваша заявка на вывод #{wid} выполнена.\n{done}"
    else:
        user_text = (
            f"✅ Ваша заявка на вывод #{wid} на сумму <b>{amount:,.2f} ₽</b> выполнена."
        )
    user_text += f'\n🔗 <a href="{explorer}">Транзакция</a>' if explorer else ""
    await send_user_message(uid, user_text)

    admin_msg_id = wd.get("admin_message_id")
    if admin_msg_id:
        wd_full = await get_withdrawal(wid)
        if wd_full:
            body = format_withdrawal_admin_message(dict(wd_full), None)
            await edit_admin_message(
                int(admin_msg_id),
                f"{body}\n\n✅ <b>Выплачено</b>",
                reply_markup=None,
            )

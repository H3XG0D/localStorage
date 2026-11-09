"""Подтверждение адреса клиентом перед автовыплатой покупки BTC/LTC.

Воркер не шлёт монеты, пока в payout_wallet_confirms нет status=confirmed.
Без ответа отправка стоит. Повторный тик вопрос не дублирует.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import logging
from typing import Any

from db import get_pool
from wallet_validation import validate_buy_wallet

logger = logging.getLogger("payout_wallet_confirm")

_OPEN = frozenset({"pending", "awaiting_address"})
WALLET_ASK_DELAY_SEC = 300
WALLET_ASK_DELAY = timedelta(seconds=WALLET_ASK_DELAY_SEC)


def normalize_buy_address(raw: str | None) -> str:
    return (raw or "").strip().split()[0].strip()


def ask_text(*, order_id: str, coin: str, fiat: float, amount_crypto: float, address: str) -> str:
    crypto = _coin_amt(amount_crypto)
    rub = f"{float(fiat or 0):,.0f}"
    return (
        "<b>Уточните кошелёк перед отправкой</b>\n"
        f"Заявка #{html.escape(str(order_id))} · {html.escape(coin.upper())}\n"
        f"{html.escape(crypto)} · {html.escape(rub)} ₽\n\n"
        f"<code>{html.escape(address)}</code>\n\n"
        "Кошелёк актуален или нужна выплата на другой?"
    )


def ask_keyboard(order_id: str) -> dict[str, Any]:
    oid = str(order_id)
    return {
        "inline_keyboard": [
            [{"text": "Кошелёк актуален", "callback_data": f"pw:ok:{oid}"}],
            [{"text": "На другой", "callback_data": f"pw:new:{oid}"}],
        ]
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None or not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def order_needs_wallet_confirm(row: dict | Any) -> bool:
    """Нужен ли по этой BUY-заявке запрос подтверждения кошелька (BTC/LTC или черновик)."""
    if not row:
        return False
    if str(row.get("direction") or "").lower() != "buy":
        return False
    from requisite_retry import snapshot_is_requisite_retry, split_crypto, wallet_coin_supported

    retry = snapshot_is_requisite_retry(row.get("payment_snapshot"))
    coin, _ = split_crypto(str(row.get("crypto") or ""))
    return wallet_coin_supported(coin, requisite_retry=retry)


def order_wallet_timer_active(row: dict | Any) -> bool:
    """Открыта ли заявка для таймера/подтверждения кошелька."""
    if not order_needs_wallet_confirm(row):
        return False
    if str(row.get("payout_tx_hash") or "").strip():
        return False
    from requisite_retry import snapshot_is_requisite_retry

    retry = snapshot_is_requisite_retry(row.get("payment_snapshot"))
    status = str(row.get("status") or "").upper()
    return status == "COMPLETED" or (retry and status == "OPERATOR_PENDING")


def compute_wallet_grace_state(
    order: dict | Any,
    confirm: dict | Any | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Состояние 5-минутного таймера и подтверждения кошелька для /ops и воркера."""
    if not order_wallet_timer_active(order):
        return None
    moment = _aware(now) or datetime.now(timezone.utc)
    from requisite_retry import split_crypto

    coin, _ = split_crypto(str(order.get("crypto") or ""))
    address = str(
        (confirm.get("address") if confirm else None)
        or order.get("requisites")
        or order.get("wallet_address")
        or ""
    ).strip()
    if confirm:
        c_status = str(confirm.get("status") or "")
        return {
            "stage": "confirmed" if c_status == "confirmed" else "asked",
            "status": c_status,
            "coin": coin.upper(),
            "address": address,
            "confirmed_at": None,
            "send_at": None,
            "seconds_left": 0,
            "delay_sec": WALLET_ASK_DELAY_SEC,
            "can_send_early": False,
        }
    base_ts = _aware(order.get("updated_at")) or _aware(order.get("created_at"))
    if base_ts is None:
        send_at = moment
        left = 0
    else:
        send_at = base_ts + WALLET_ASK_DELAY
        left = max(0, int((send_at - moment).total_seconds() + 0.999))
    return {
        "stage": "waiting_timer",
        "status": "timer",
        "coin": coin.upper(),
        "address": address,
        "confirmed_at": base_ts.isoformat() if base_ts else None,
        "send_at": send_at.isoformat() if send_at else None,
        "seconds_left": left,
        "delay_sec": WALLET_ASK_DELAY_SEC,
        "can_send_early": True,
    }


def wallet_confirm_view(row) -> dict[str, Any] | None:
    """Поля для сайта и мини-приложения. Подтверждённый адрес уже не спрашиваем."""
    if not row:
        return None
    status = str(row["status"] or "")
    if status not in _OPEN:
        return None
    return {
        "status": status,
        "address": str(row["address"] or ""),
        "coin": str(row["coin"] or "").upper(),
    }


async def wallet_confirm_for_order(order_id: str) -> dict[str, Any] | None:
    if not order_id:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.status, c.address, c.coin
            FROM payout_wallet_confirms c
            JOIN orders o ON o.order_id = c.order_id
            WHERE c.order_id = $1
              AND c.status IN ('pending', 'awaiting_address')
              AND o.direction = 'buy'
              AND (
                o.status = 'COMPLETED'
                OR (
                  o.status = 'OPERATOR_PENDING'
                  AND COALESCE(o.payment_snapshot->>'requisite_retry', '') = 'true'
                )
              )
              AND (o.payout_tx_hash IS NULL OR btrim(o.payout_tx_hash) = '')
            """,
            order_id,
        )
    return wallet_confirm_view(row)


def _coin_amt(value: float) -> str:
    text = f"{float(value or 0):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def evaluate_wallet_decision(
    order: dict | None,
    confirm: dict | None,
    *,
    user_id: int,
    action: str,
    address: str | None,
) -> dict[str, Any]:
    """Решение без записи. http != 200 — клиенту ошибка, базу не трогаем."""
    if not order or int(order.get("user_id") or 0) != int(user_id):
        return {"http": 404, "detail": "order_not_found"}
    if str(order.get("payout_tx_hash") or "").strip():
        return {
            "http": 200,
            "status": "already_sent",
            "address": None,
            "detail": "Уже отправлено",
            "write_order": False,
        }
    if str(order.get("direction") or "").lower() != "buy":
        return {"http": 400, "detail": "not_buy"}
    from requisite_retry import snapshot_is_requisite_retry, split_crypto, wallet_coin_supported

    retry = snapshot_is_requisite_retry(order.get("payment_snapshot"))
    status = str(order.get("status") or "").upper()
    if status != "COMPLETED" and not (retry and status == "OPERATOR_PENDING"):
        return {"http": 409, "detail": "wrong_status"}
    coin, network = split_crypto(str(order.get("crypto") or ""))
    if not wallet_coin_supported(coin, requisite_retry=retry):
        return {"http": 400, "detail": "unsupported_coin"}
    if not confirm:
        return {"http": 409, "detail": "not_waiting"}

    status = str(confirm.get("status") or "")
    stored = str(confirm.get("address") or "").strip()
    if action == "confirm":
        if status == "confirmed":
            return _confirmed(stored, idempotent=True)
        if status not in _OPEN:
            return {"http": 409, "detail": "not_waiting"}
        return _confirmed(stored, idempotent=False)
    if action == "await_address":
        if status == "confirmed":
            return _confirmed(stored, idempotent=True)
        if status not in _OPEN:
            return {"http": 409, "detail": "not_waiting"}
        return {
            "http": 200,
            "status": "awaiting_address",
            "address": stored,
            "detail": (
                "Пришлите адрес одним сообщением. Проверим формат перед отправкой. "
                "Чтобы вернуться, напишите «отмена»."
            ),
            "write_order": False,
            "next_status": "awaiting_address",
        }
    if action == "cancel":
        if status == "confirmed":
            return _confirmed(stored, idempotent=True)
        if status not in _OPEN:
            return {"http": 409, "detail": "not_waiting"}
        return {
            "http": 200,
            "status": "pending",
            "address": stored,
            "detail": "Оставили адрес с заявки. Нажмите кнопку в новом сообщении.",
            "write_order": False,
            "next_status": "pending",
            "resend": True,
        }
    if action == "replace":
        if status == "confirmed":
            return _confirmed(stored, idempotent=True)
        if status not in _OPEN:
            return {"http": 409, "detail": "not_waiting"}
        addr = normalize_buy_address(address)
        try:
            validate_buy_wallet(coin, network, addr)
        except ValueError as exc:
            return {"http": 400, "detail": str(exc)}
        return {
            "http": 200,
            "status": "confirmed",
            "address": addr,
            "coin": coin,
            "detail": f"Адрес подходит. Отправляем {coin.upper()} на\n{addr}",
            "write_order": True,
            "next_status": "confirmed",
        }
    return {"http": 400, "detail": "bad_action"}


def _confirmed(address: str, *, idempotent: bool) -> dict[str, Any]:
    return {
        "http": 200,
        "status": "confirmed",
        "address": address,
        "detail": "Отправляем на этот адрес",
        "write_order": not idempotent,
        "next_status": None if idempotent else "confirmed",
    }


def _grace_remaining_seconds(row: dict | Any, *, now: datetime | None = None) -> int:
    """Сколько секунд осталось ждать 5 минут после подтверждения Payfast."""
    base_ts = _aware(row.get("updated_at") if hasattr(row, "get") else None) or _aware(
        row.get("created_at") if hasattr(row, "get") else None
    )
    if base_ts is None:
        return 0
    moment = _aware(now) or datetime.now(timezone.utc)
    send_at = base_ts + WALLET_ASK_DELAY
    return max(0, int((send_at - moment).total_seconds() + 0.999))


async def resolve_payout_address(
    row,
    *,
    coin: str,
    address: str,
    fiat: float,
    amount_crypto: float,
    force_ask: bool = False,
    now: datetime | None = None,
) -> str | None:
    """Адрес, который клиент подтвердил. None — отправку не начинать."""
    order_id = str(row["order_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT status, address
            FROM payout_wallet_confirms
            WHERE order_id = $1
            """,
            order_id,
        )
        if existing:
            if str(existing["status"] or "") == "confirmed":
                approved = str(existing["address"] or "").strip()
                return approved or None
            return None
        if not force_ask and _grace_remaining_seconds(row, now=now) > 0:
            logger.debug("wallet confirm in 5-min grace period order=%s", order_id)
            return None
        user_id = row.get("user_id")
        if user_id is None:
            logger.info("wallet confirm skipped, no user order=%s", order_id)
            return None
        inserted = await conn.fetchrow(
            """
            INSERT INTO payout_wallet_confirms (order_id, user_id, coin, address, status)
            VALUES ($1, $2, $3, $4, 'pending')
            ON CONFLICT (order_id) DO NOTHING
            RETURNING order_id
            """,
            order_id,
            int(user_id),
            coin,
            address,
        )
    if not inserted:
        return None
    delivered, message_id = await deliver_ask(
        user_id=int(user_id),
        order_id=order_id,
        coin=coin,
        fiat=fiat,
        amount_crypto=amount_crypto,
        address=address,
    )
    if message_id:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE payout_wallet_confirms
                    SET telegram_chat_id = $2, telegram_message_id = $3
                    WHERE order_id = $1
                    """,
                    order_id,
                    int(user_id),
                    int(message_id),
                )
        except Exception:
            logger.warning("wallet confirm message id not stored order=%s", order_id, exc_info=True)
    await _notify_ops_waiting(order_id, coin, address, delivered=delivered)
    return None


async def apply_client_decision(
    *,
    order_id: str,
    user_id: int,
    action: str,
    address: str | None = None,
) -> dict[str, Any]:
    from fastapi import HTTPException

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 FOR UPDATE",
                order_id,
            )
            confirm = None
            if order and int(order["user_id"] or 0) == int(user_id):
                confirm = await conn.fetchrow(
                    "SELECT * FROM payout_wallet_confirms WHERE order_id = $1 FOR UPDATE",
                    order_id,
                )
            decision = evaluate_wallet_decision(
                dict(order) if order else None,
                dict(confirm) if confirm else None,
                user_id=int(user_id),
                action=action,
                address=address,
            )
            if int(decision["http"]) != 200:
                raise HTTPException(status_code=int(decision["http"]), detail=decision["detail"])
            next_status = decision.get("next_status")
            stored = decision.get("address")
            if next_status == "confirmed" and stored:
                await conn.execute(
                    """
                    UPDATE payout_wallet_confirms
                    SET status = 'confirmed', address = $2, confirmed_at = now()
                    WHERE order_id = $1 AND status IN ('pending', 'awaiting_address')
                    """,
                    order_id,
                    stored,
                )
            elif next_status in ("awaiting_address", "pending"):
                await conn.execute(
                    """
                    UPDATE payout_wallet_confirms
                    SET status = $2
                    WHERE order_id = $1 AND status IN ('pending', 'awaiting_address')
                    """,
                    order_id,
                    next_status,
                )
            if decision.get("write_order") and stored:
                await conn.execute(
                    """
                    UPDATE orders
                    SET requisites = $2, wallet_address = $3, updated_at = now()
                    WHERE order_id = $1
                      AND (payout_tx_hash IS NULL OR btrim(payout_tx_hash) = '')
                    """,
                    order_id,
                    stored,
                    stored,
                )
            order_view = dict(order) if order else {}
    if decision.get("resend") and stored and order_view.get("user_id") is not None:
        coin = str(order_view.get("crypto") or "").split("_")[0].lower()
        delivered, message_id = await deliver_ask(
            user_id=int(order_view["user_id"]),
            order_id=order_id,
            coin=coin,
            fiat=float(order_view.get("fiat_amount") or 0),
            amount_crypto=float(order_view.get("crypto_amount") or 0),
            address=str(stored),
        )
        if message_id:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE payout_wallet_confirms
                        SET telegram_chat_id = $2, telegram_message_id = $3
                        WHERE order_id = $1
                        """,
                        order_id,
                        int(order_view["user_id"]),
                        int(message_id),
                    )
            except Exception:
                logger.warning("wallet confirm resend id not stored order=%s", order_id, exc_info=True)
        if not delivered:
            logger.info("wallet confirm resend not delivered order=%s", order_id)
    return {
        "ok": True,
        "status": decision["status"],
        "address": decision.get("address"),
        "detail": decision["detail"],
    }


async def deliver_ask(
    *,
    user_id: int,
    order_id: str,
    coin: str,
    fiat: float,
    amount_crypto: float,
    address: str,
) -> tuple[bool, int | None]:
    from telegram_notify import _post_telegram

    payload = {
        "chat_id": int(user_id),
        "text": ask_text(
            order_id=order_id,
            coin=coin,
            fiat=fiat,
            amount_crypto=amount_crypto,
            address=address,
        ),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": ask_keyboard(order_id),
    }
    data, err = await _post_telegram("sendMessage", json_payload=payload)
    if not data:
        logger.warning("wallet confirm dm failed order=%s uid=%s: %s", order_id, user_id, err)
        return False, None
    result = data.get("result") if isinstance(data, dict) else None
    message_id = result.get("message_id") if isinstance(result, dict) else None
    try:
        return True, int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return True, None


async def _notify_ops_waiting(order_id: str, coin: str, address: str, *, delivered: bool) -> None:
    from telegram_notify import send_admin_message

    tail = "" if delivered else " Личка не дошла."
    text = (
        f"Ждём подтверждение кошелька по заявке {html.escape(str(order_id))} "
        f"· {html.escape(coin.upper())} · <code>{html.escape(address)}</code>.{tail}"
    )
    try:
        await send_admin_message(text)
    except Exception:
        logger.warning("wallet confirm ops notify failed order=%s", order_id, exc_info=True)


class WalletNotConfirmed(Exception):
    """Выплату из черновика нельзя отправить, пока клиент не подтвердил адрес."""


async def ensure_retry_wallet_confirmed(
    order: dict,
    *,
    force_ask: bool = False,
    now: datetime | None = None,
) -> None:
    """Для заявки из черновика спросить кошелёк и не пускать выплату без ответа.

    Обычные заявки не трогает. BTC/LTC по-прежнему спрашивает автопилот отдельно.
    """
    from requisite_retry import snapshot_is_requisite_retry, split_crypto, wallet_coin_supported

    if not snapshot_is_requisite_retry(order.get("payment_snapshot")):
        return
    coin, _network = split_crypto(str(order.get("crypto") or ""))
    if not wallet_coin_supported(coin, requisite_retry=True):
        return
    order_id = str(order.get("order_id") or "")
    user_id = order.get("user_id")
    address = str(order.get("requisites") or order.get("wallet_address") or "").strip()
    if not order_id or user_id is None or not address:
        raise WalletNotConfirmed("Ждём подтверждение кошелька клиентом")
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT status, address
            FROM payout_wallet_confirms
            WHERE order_id = $1
            """,
            order_id,
        )
        if existing and str(existing["status"] or "") == "confirmed":
            return
        if existing:
            raise WalletNotConfirmed("Ждём подтверждение кошелька клиентом")
        left = _grace_remaining_seconds(order, now=now)
        if not force_ask and left > 0:
            mins = max(1, (left + 59) // 60)
            raise WalletNotConfirmed(
                f"Идёт таймер 5 мин после подтверждения Payfast (осталось ~{mins} мин). "
                "Нажмите «Отправить запрос досрочно», чтобы спросить кошелёк сейчас."
            )
        inserted = await conn.fetchrow(
            """
            INSERT INTO payout_wallet_confirms (order_id, user_id, coin, address, status)
            VALUES ($1, $2, $3, $4, 'pending')
            ON CONFLICT (order_id) DO NOTHING
            RETURNING order_id
            """,
            order_id,
            int(user_id),
            coin,
            address,
        )
    if not inserted:
        raise WalletNotConfirmed("Ждём подтверждение кошелька клиентом")
    delivered, message_id = await deliver_ask(
        user_id=int(user_id),
        order_id=order_id,
        coin=coin,
        fiat=float(order.get("fiat_amount") or 0),
        amount_crypto=float(order.get("crypto_amount") or 0),
        address=address,
    )
    if message_id:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE payout_wallet_confirms
                    SET telegram_chat_id = $2, telegram_message_id = $3
                    WHERE order_id = $1
                    """,
                    order_id,
                    int(user_id),
                    int(message_id),
                )
        except Exception:
            logger.warning("wallet confirm message id not stored order=%s", order_id, exc_info=True)
    await _notify_ops_waiting(order_id, coin, address, delivered=delivered)
    raise WalletNotConfirmed("Ждём подтверждение кошелька клиентом")


async def send_wallet_confirm_early(order_id: str) -> dict[str, Any]:
    """Досрочно убрать 5-минутный таймер и отправить запрос уточнения кошелька клиенту."""
    from fastapi import HTTPException
    from requisite_retry import split_crypto

    oid = (order_id or "").strip().upper()
    if not oid:
        raise HTTPException(status_code=400, detail="order_not_found")
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", oid)
        if not order:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        order_d = dict(order)
        if not order_needs_wallet_confirm(order_d):
            raise HTTPException(
                status_code=400,
                detail="Для этой заявки запрос подтверждения кошелька не требуется",
            )
        if str(order_d.get("payout_tx_hash") or "").strip():
            raise HTTPException(status_code=409, detail="Выплата по заявке уже отправлена")
        if not order_wallet_timer_active(order_d):
            raise HTTPException(
                status_code=409,
                detail="Заявка ещё не подтверждена Payfast или уже закрыта",
            )
        existing = await conn.fetchrow(
            "SELECT status, address FROM payout_wallet_confirms WHERE order_id = $1",
            oid,
        )
        if existing:
            st = str(existing["status"] or "")
            return {
                "ok": True,
                "already_sent": True,
                "status": st,
                "address": str(existing["address"] or ""),
                "detail": (
                    "Клиент уже подтвердил кошелёк"
                    if st == "confirmed"
                    else "Запрос уточнения кошелька уже отправлен клиенту"
                ),
            }
        user_id = order_d.get("user_id")
        address = str(order_d.get("requisites") or order_d.get("wallet_address") or "").strip()
        if user_id is None or not address:
            raise HTTPException(status_code=400, detail="В заявке нет клиента или адреса кошелька")
        coin, _ = split_crypto(str(order_d.get("crypto") or ""))
        inserted = await conn.fetchrow(
            """
            INSERT INTO payout_wallet_confirms (order_id, user_id, coin, address, status)
            VALUES ($1, $2, $3, $4, 'pending')
            ON CONFLICT (order_id) DO NOTHING
            RETURNING order_id
            """,
            oid,
            int(user_id),
            coin,
            address,
        )
    if not inserted:
        return {
            "ok": True,
            "already_sent": True,
            "status": "pending",
            "address": address,
            "detail": "Запрос уточнения кошелька уже отправлен клиенту",
        }
    delivered, message_id = await deliver_ask(
        user_id=int(user_id),
        order_id=oid,
        coin=coin,
        fiat=float(order_d.get("fiat_amount") or 0),
        amount_crypto=float(order_d.get("crypto_amount") or 0),
        address=address,
    )
    if message_id:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE payout_wallet_confirms
                    SET telegram_chat_id = $2, telegram_message_id = $3
                    WHERE order_id = $1
                    """,
                    oid,
                    int(user_id),
                    int(message_id),
                )
        except Exception:
            logger.warning("wallet confirm message id not stored order=%s", oid, exc_info=True)
    await _notify_ops_waiting(oid, coin, address, delivered=delivered)
    return {
        "ok": True,
        "already_sent": False,
        "delivered": delivered,
        "status": "pending",
        "address": address,
        "detail": (
            "Таймер снят — запрос уточнения кошелька отправлен покупателю"
            if delivered
            else "Таймер снят — запрос активирован (личка в Telegram не дошла, клиент увидит на сайте)"
        ),
    }


async def sweep_due_wallet_confirms(*, now: datetime | None = None) -> int:
    """После 5 минут с момента подтверждения Payfast отправить запрос кошелька покупателю."""
    moment = _aware(now) or datetime.now(timezone.utc)
    cutoff = moment - WALLET_ASK_DELAY
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT o.order_id, o.user_id, o.crypto, o.crypto_amount, o.fiat_amount,
                   o.requisites, o.wallet_address, o.status, o.direction,
                   o.payment_snapshot, o.payout_tx_hash, o.updated_at, o.created_at
            FROM orders o
            LEFT JOIN payout_wallet_confirms c ON c.order_id = o.order_id
            WHERE c.order_id IS NULL
              AND lower(o.direction) = 'buy'
              AND (o.payout_tx_hash IS NULL OR btrim(o.payout_tx_hash) = '')
              AND COALESCE(o.updated_at, o.created_at) <= $1
              AND (
                (
                  o.status = 'COMPLETED'
                  AND (
                    lower(split_part(COALESCE(o.crypto, ''), '_', 1)) IN ('btc', 'ltc')
                    OR COALESCE(o.payment_snapshot->>'requisite_retry', '') = 'true'
                  )
                )
                OR (
                  o.status = 'OPERATOR_PENDING'
                  AND COALESCE(o.payment_snapshot->>'requisite_retry', '') = 'true'
                )
              )
            ORDER BY COALESCE(o.updated_at, o.created_at) ASC
            LIMIT 20
            """,
            cutoff,
        )
    sent_count = 0
    from requisite_retry import split_crypto

    for row in rows:
        order_d = dict(row)
        if not order_wallet_timer_active(order_d):
            continue
        address = str(order_d.get("requisites") or order_d.get("wallet_address") or "").strip()
        if not address or order_d.get("user_id") is None:
            continue
        coin, _ = split_crypto(str(order_d.get("crypto") or ""))
        try:
            await resolve_payout_address(
                order_d,
                coin=coin,
                address=address,
                fiat=float(order_d.get("fiat_amount") or 0),
                amount_crypto=float(order_d.get("crypto_amount") or 0),
                force_ask=True,
                now=moment,
            )
            sent_count += 1
        except Exception:
            logger.warning(
                "sweep_due_wallet_confirms failed order=%s",
                order_d.get("order_id"),
                exc_info=True,
            )
    return sent_count

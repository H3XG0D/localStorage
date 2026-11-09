"""Создание и управление заявками с сайта."""
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import asyncpg
from fastapi import HTTPException

from config import settings
from db import get_pool
from economics_snapshot import build_economics_snapshot
from merchant_client import create_payin_order
from routers.public import get_need_rates_cached, get_rates_cached, get_sell_market_rates
from buy_rub_quote import quote_buy_rub_base
from ip_order_guard import enforce_one_active_order_per_ip, log_ip_event
from runtime_settings import MAINTENANCE_MESSAGE, maintenance_mode
from wallet_validation import validate_buy_wallet, validate_sell_fiat_requisites

logger = logging.getLogger("order_service")

ACTIVE_STATUSES = ("CREATED", "AWAITING_CHECK", "PENDING", "OPERATOR_PENDING", "COMPLETED")

# Совпадает с UNPAID_COOLDOWN_MINUTES бота (services/buyer_access_guards.py).
UNPAID_COOLDOWN_MINUTES = 30


def _plain_receipt_message(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", text or "").strip()


async def _attach_bot_receipt(order: dict, receipt_file: str | None) -> dict:
    """Миниапка: то же дерево, что чек файлом в боте. Сайтовый payin_set_check не зовём."""
    if not receipt_file:
        raise HTTPException(status_code=400, detail="Receipt file missing")
    from bot_status_bridge import route_uploaded_receipt

    try:
        routed = await route_uploaded_receipt(order, receipt_file)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("bot receipt route failed order=%s: %s", order.get("order_id"), e)
        raise HTTPException(
            status_code=503,
            detail="Не удалось отправить чек на проверку. Попробуйте ещё раз.",
        ) from e
    route_name = str(routed.get("route") or "")
    message = _plain_receipt_message(str(routed.get("client_message") or ""))
    if route_name == "rejected":
        raise HTTPException(status_code=400, detail=message or "Чек не принят")
    if route_name in ("error", "video_failed", "reki_failed"):
        raise HTTPException(
            status_code=503,
            detail=message or "Не удалось отправить чек. Попробуйте ещё раз.",
        )
    return {
        "status": routed.get("status") or "AWAITING_CHECK",
        "message": message or "Receipt submitted",
        "receipt_submitted": True,
    }


def _ops_channel_note(order, detail: str = "") -> str:
    from order_source import channel_note

    source = order.get("order_source") if order is not None else None
    return channel_note(source, detail)


async def _safe_notify_ops(event: str, order: dict, **kwargs) -> None:
    """Ops-уведомление не должно ломать создание заявки на сайте."""
    try:
        from order_ops_notify import notify_ops_order

        await notify_ops_order(event, order, **kwargs)
    except Exception as e:
        logger.warning("ops notify failed event=%s order=%s: %s", event, order.get("order_id"), e)


async def notify_created_buy(row: dict) -> None:
    """Обычная заявка после удачного повтора. Черновик сюда не попадает."""
    await _safe_notify_ops("created", row, note=_ops_channel_note(row))


def _generate_order_id() -> str:
    return str(uuid.uuid4().int)[:8]


def _crypto_symbol(crypto: str, network: str | None) -> str:
    c = crypto.lower()
    if c == "usdt" and network:
        return f"USDT_{network.upper()}"
    return c.upper()


def _wallet_for_sell(crypto: str, network: str | None) -> str | None:
    """Постоянный адрес приёма из настроек. Пусто — адрес выдаёт оператор."""
    from runtime_settings import sell_deposit_address

    base = (crypto or "").lower().split("_")[0]
    # USDT/TRX многосетевые: единственный адрес без выбора сети опасен.
    if base != "btc" or network:
        return None
    return sell_deposit_address(base)


def buy_without_requisites_message(order_id: str) -> str:
    """Покупка без счёта: клиенту некуда платить, заявку забирает оператор."""
    support = (settings.chat_support_username or "focus_operator").strip().lstrip("@") or "focus_operator"
    return (
        f"Реквизитов сейчас нет. Напишите оператору @{support}, "
        f"номер заявки #{order_id} — попробуем что-нибудь придумать."
    )


def _snapshot_has_bill(row) -> bool:
    snap = _payment_snapshot_from_row(row)
    bill = snap.get("bill")
    if not isinstance(bill, dict):
        return False
    from payin_resolver import _bill_has_reciver

    return _bill_has_reciver(bill)


def buy_payment_for_active_row(row) -> dict | None:
    """Активная покупка: счёт из снимка, либо текст оператору, если счёта нет."""
    if str(row.get("direction") or "").lower() != "buy":
        return None
    if str(row.get("status") or "") == "OPERATOR_PENDING" and not _snapshot_has_bill(row):
        return {
            "type": "operator",
            "message": buy_without_requisites_message(str(row.get("order_id") or "")),
        }
    if payfast_requisites_are_closed(row):
        return None
    return _payment_from_row(row)


def _attach_buy_operator_message(out: dict, row, payment: dict | None) -> dict:
    if (
        payment
        and payment.get("type") == "operator"
        and str(row.get("direction") or "").lower() == "buy"
    ):
        out["operator_message"] = payment.get("message")
    return out


def _sell_payment_for_row(row) -> dict:
    """Продажа: постоянный адрес, если он настроен, иначе — оператор в чате."""
    support = settings.chat_support_username or "focus_operator"
    oid = row["order_id"]
    wallet = _wallet_for_sell(str(row.get("crypto") or ""), None)
    if wallet:
        return {
            "type": "deposit",
            "deposit_wallet": wallet,
            "message": (
                f"Отправьте {row['crypto_amount']} {str(row['crypto']).upper()} на адрес ниже "
                "и нажмите «Я оплатил». Рубли уйдут после подтверждения прихода."
            ),
        }
    message = (
        f"Заявка передана оператору. Напишите @{support} с номером #{oid} — "
        "оператор выдаст адрес для крипты и отправит рубли после поступления."
    )
    return {"type": "operator", "message": message}


async def _count_recent_orders(user_id: int, minutes: int = 15) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM orders
            WHERE user_id = $1
              AND created_at > now() - ($2 || ' minutes')::interval
              AND status NOT IN ('PAID', 'COMPLETED')
            """,
            user_id,
            str(minutes),
        )


async def _unpaid_cooldown_remaining_sec(user_id: int) -> int:
    """Сколько ещё ждать после отмены/истечения BUY, где реквизиты уже выдали."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT payment_snapshot,
                   EXTRACT(EPOCH FROM (now() - updated_at))::int AS age_sec
            FROM orders
            WHERE user_id = $1
              AND direction = 'buy'
              AND status IN ('CANCELED', 'EXPIRED')
              AND updated_at > now() - ($2 || ' minutes')::interval
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            user_id,
            str(UNPAID_COOLDOWN_MINUTES),
        )
    for row in rows:
        if not _snapshot_has_bill(row):
            continue
        remaining = UNPAID_COOLDOWN_MINUTES * 60 - int(row["age_sec"] or 0)
        if remaining > 0:
            return remaining
    return 0


def _unpaid_cooldown_detail(remaining_sec: int) -> str:
    minutes = max(1, (int(remaining_sec) + 59) // 60)
    support = (settings.chat_support_username or "focus_operator").strip().lstrip("@") or "focus_operator"
    return (
        f"Вы отменили заявку с выданными реквизитами. "
        f"Запросить реквизиты снова можно через {minutes} мин. "
        f"Если возникли трудности с переводом — напишите @{support}."
    )


async def _get_active_order(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT * FROM orders
            WHERE user_id = $1 AND status = ANY($2::varchar[])
            ORDER BY created_at DESC LIMIT 1
            """,
            user_id,
            list(ACTIVE_STATUSES),
        )


def _active_order_conflict(order_id: str, *, by_ip: bool = False) -> dict:
    if by_ip:
        msg = (
            f"С вашего IP уже есть активная заявка #{order_id}. "
            "Продолжите оплату по ней или отмените перед созданием новой."
        )
    else:
        msg = (
            f"У вас уже есть активная заявка #{order_id}. "
            "Продолжите оплату по ней или отмените перед созданием новой."
        )
    return {
        "code": "active_order_exists",
        "order_id": str(order_id),
        "message": msg,
    }


async def _fetch_order_row_for_web(
    order_id: str,
    user_id: int,
    client_ip: str | None = None,
):
    """Заявка доступна ТОЛЬКО владельцу (user_id).

    Доступ по совпадению client_ip убран: IP подделывается заголовками
    (X-Forwarded-For), что давало чтение/отмену/подтверждение чужих заявок (IDOR).
    """
    _ = client_ip
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
    if not row:
        return None
    if int(row["user_id"]) == int(user_id):
        return row
    return None


async def get_active_web_order(
    user_id: int, client_ip: str | None = None
) -> dict | None:
    # Только заявки владельца. Поиск по client_ip убран (IDOR через подделку IP).
    _ = client_ip
    row = await _get_active_order(user_id)
    if not row or row["status"] not in ACTIVE_STATUSES:
        return None
    payment = None
    if row["direction"] == "sell":
        payment = _sell_payment_for_row(row)
    elif row["direction"] == "buy":
        payment = buy_payment_for_active_row(row)
    return await _attach_wallet_confirm(
        _attach_buy_operator_message(_order_response(row, payment=payment), row, payment)
    )


def _validate_amounts(
    crypto: str,
    direction: str,
    fiat_amount: float | None,
    crypto_amount: float | None,
    market: dict,
    *,
    manual_buy: bool = False,
    buy_fiat_is_market_base: bool = False,
    operator_manual: bool = False,
    need: dict | None = None,
) -> tuple[Decimal, Decimal, Decimal]:
    from payout_sum_snap import snap_sell_fiat
    from runtime_settings import buy_markup, sell_discount

    price = market.get(crypto.lower())
    if not price:
        raise HTTPException(status_code=503, detail="Rate unavailable for this crypto")

    market_dec = Decimal(str(price))
    markup = Decimal("1")
    if direction == "buy":
        markup = Decimal(str(buy_markup(manual=manual_buy)))
        rate = market_dec * markup
    else:
        rate = market_dec * Decimal(str(sell_discount()))

    def _apply_auto_buy_markup(amount_rub: Decimal) -> None:
        nonlocal markup, rate
        if direction != "buy" or manual_buy:
            return
        markup = Decimal(str(buy_markup(manual=False, amount_rub=float(amount_rub))))
        rate = market_dec * markup

    if operator_manual:
        # Ручные заявки оператора — без лимитов суммы (только > 0 ниже).
        pass
    else:
        limits = settings.amount_limits.get(crypto.lower(), {})
        max_c = Decimal(str(limits.get("max_crypto", 1e18)))
        min_f = Decimal(str(limits.get("min_fiat", 0)))
        max_f = Decimal(str(limits.get("max_fiat", 1e18)))

    if direction == "buy" and buy_fiat_is_market_base:
        # Рубли — оценка крипты по CoinGecko; к оплате = объём × Rapira × наценка.
        # Ввод в монете: объём фиксирован, оплата по Rapira.
        if crypto_amount is not None and fiat_amount is None:
            base_fiat = (
                Decimal(str(crypto_amount)) * market_dec
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            _apply_auto_buy_markup(base_fiat)
            crypto_amt = (base_fiat / market_dec).quantize(
                Decimal("0.00000001"), rounding=ROUND_HALF_UP
            )
            fiat = int(
                (base_fiat * markup).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        elif fiat_amount is not None:
            try:
                need_price = Decimal(str((need or {}).get(crypto.lower()) or 0))
            except Exception:
                need_price = Decimal("0")
            if need_price <= 0:
                raise HTTPException(
                    status_code=503,
                    detail="Курс CoinGecko временно недоступен. Попробуйте позже.",
                )
            base_fiat = Decimal(str(fiat_amount)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            _apply_auto_buy_markup(base_fiat)
            try:
                crypto_amt, fiat, rate = quote_buy_rub_base(
                    base_fiat=base_fiat,
                    rapira=market_dec,
                    coingecko=need_price,
                    markup=markup,
                )
            except ValueError:
                raise HTTPException(
                    status_code=503,
                    detail="Курс CoinGecko временно недоступен. Попробуйте позже.",
                )
            fiat = int(fiat)
        else:
            raise HTTPException(status_code=400, detail="Specify fiat_amount or crypto_amount")
    elif fiat_amount is not None and crypto_amount is None:
        fiat = Decimal(str(fiat_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        _apply_auto_buy_markup(fiat)
        crypto_amt = (fiat / rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    elif crypto_amount is not None and fiat_amount is None:
        crypto_amt = Decimal(str(crypto_amount))
        _apply_auto_buy_markup(
            (crypto_amt * market_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        fiat = (crypto_amt * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif fiat_amount is not None and crypto_amount is not None:
        fiat = Decimal(str(fiat_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        crypto_amt = Decimal(str(crypto_amount))
    else:
        raise HTTPException(status_code=400, detail="Specify fiat_amount or crypto_amount")

    if direction == "buy" and not buy_fiat_is_market_base:
        if crypto_amount is not None and fiat_amount is None:
            # Если пользователь/оператор задал точную сумму крипты, она — источник истины.
            # Рубли округляем ВВЕРХ, чтобы оплата покрывала введённую крипту; крипту не режем.
            fiat = fiat.quantize(Decimal("1"), rounding=ROUND_CEILING)
        else:
            fiat = fiat.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    if direction == "sell" and not operator_manual:
        # Подгонка под открытый реквизит выплаты. Крипта клиента неизменна,
        # меняются рубли и эффективный курс — инвариант fiat = crypto × rate держится.
        snapped = snap_sell_fiat(fiat, crypto_amt, market_dec)
        if snapped:
            fiat, rate = snapped

    if operator_manual:
        if fiat <= 0 and crypto_amt <= 0:
            raise HTTPException(status_code=400, detail="Укажите сумму больше нуля")
        return crypto_amt, fiat, rate

    if crypto_amt > max_c:
        raise HTTPException(
            status_code=400,
            detail=f"Максимум: {max_c.normalize()} {crypto.upper()}",
        )
    if fiat < min_f or fiat > max_f:
        if fiat < min_f:
            detail = f"Минимум: {int(min_f):,} ₽".replace(",", " ")
        else:
            detail = f"Максимум: {int(max_f):,} ₽".replace(",", " ")
        raise HTTPException(status_code=400, detail=detail)

    return crypto_amt, fiat, rate


async def quote_sell(
    crypto: str,
    *,
    fiat_amount: float | None = None,
    crypto_amount: float | None = None,
) -> dict:
    """Финальная котировка SELL — ровно то, что попадёт в заявку (включая подгонку)."""
    from runtime_settings import sell_discount

    try:
        market = await get_sell_market_rates()
    except Exception as e:
        logger.error("sell quote rates unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Курс временно недоступен")

    crypto_amt, fiat, rate = _validate_amounts(
        crypto,
        "sell",
        fiat_amount,
        crypto_amount,
        market,
    )
    market_price = Decimal(str(market[crypto.lower()]))
    cents = Decimal("0.0001")
    base_rate = (market_price * Decimal(str(sell_discount()))).quantize(
        cents, rounding=ROUND_HALF_UP
    )
    return {
        "crypto": crypto.lower(),
        "crypto_amount": float(crypto_amt),
        "fiat_amount": float(fiat),
        "rate": float(rate),
        "base_rate": float(base_rate),
        "market": float(market_price),
        "adjusted": rate.quantize(cents, rounding=ROUND_HALF_UP) != base_rate,
        "currency": "RUB",
    }


async def _insert_order(
    *,
    order_id: str,
    user_id: int,
    crypto_sym: str,
    direction: str,
    crypto_amount: float,
    fiat_amount: float,
    rate: float,
    requisites: str,
    merchant_order_id: str | None = None,
    sub_token: str | None = None,
    expires_at=None,
    payment_snapshot: dict | None = None,
    economics_snapshot: dict | None = None,
    client_ip: str | None = None,
    order_source: str = "site",
) -> None:
    pool = await get_pool()
    snap = json.dumps(payment_snapshot) if payment_snapshot else None
    economics_json = json.dumps(economics_snapshot) if economics_snapshot else None
    from order_source import coerce_public_order_source

    merchant_id = (payment_snapshot or {}).get("merchant_id") if isinstance(payment_snapshot, dict) else None
    merchant_attempts = json.dumps((payment_snapshot or {}).get("merchant_attempts") or []) if isinstance(payment_snapshot, dict) else "[]"
    stored_source = coerce_public_order_source(order_source)
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO orders (
                    order_id, user_id, crypto, direction, crypto_amount, fiat_amount,
                    rate, requisites, status, created_at, expires_at, updated_at,
                    merchant_order_id, sub_token, payment_snapshot, economics_snapshot,
                    client_ip, order_source, merchant_id, merchant_attempts
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, 'CREATED', now(),
                    COALESCE($9::timestamptz, now() + interval '30 minutes'), now(),
                    $10, $11, $12::jsonb, $13::jsonb, $14::inet, $15, $16, $17::jsonb
                )
                """,
                order_id,
                user_id,
                crypto_sym,
                direction,
                crypto_amount,
                fiat_amount,
                rate,
                requisites,
                expires_at,
                merchant_order_id,
                sub_token,
                snap,
                economics_json,
                client_ip,
                stored_source,
                merchant_id,
                merchant_attempts,
            )
        except Exception:
            # до применения миграции add_merchant_attribution.sql
            await conn.execute(
                """
                INSERT INTO orders (
                    order_id, user_id, crypto, direction, crypto_amount, fiat_amount,
                    rate, requisites, status, created_at, expires_at, updated_at,
                    merchant_order_id, sub_token, payment_snapshot, economics_snapshot,
                    client_ip, order_source
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, 'CREATED', now(),
                    COALESCE($9::timestamptz, now() + interval '30 minutes'), now(),
                    $10, $11, $12::jsonb, $13::jsonb, $14::inet, $15
                )
                """,
                order_id,
                user_id,
                crypto_sym,
                direction,
                crypto_amount,
                fiat_amount,
                rate,
                requisites,
                expires_at,
                merchant_order_id,
                sub_token,
                snap,
                economics_json,
                client_ip,
                stored_source,
            )


def _payment_snapshot_from_row(row) -> dict:
    snap = row.get("payment_snapshot")
    if not snap:
        return {}
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except json.JSONDecodeError:
            return {}
    return snap if isinstance(snap, dict) else {}


def _payment_from_row(row) -> dict | None:
    snap = _payment_snapshot_from_row(row)
    return {"type": "buy", **snap} if snap else None


def _merchant_expires_at_from_row(row) -> datetime | None:
    raw = _payment_snapshot_from_row(row).get("merchant_expires_at")
    if not raw:
        return None
    try:
        merchant_end = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if merchant_end.tzinfo is None:
        return merchant_end.replace(tzinfo=timezone.utc)
    return merchant_end.astimezone(timezone.utc)


def _now_utc(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def payfast_recovery_window_is_active(row, *, now: datetime | None = None) -> bool:
    """Период между закрытием реквизитов FocusPay и сроком PayFast."""
    if str(row.get("direction") or "").lower() != "buy":
        return False
    requisites_end = row.get("expires_at")
    merchant_end = _merchant_expires_at_from_row(row)
    if not requisites_end or merchant_end is None:
        return False
    if requisites_end.tzinfo is None:
        requisites_end = requisites_end.replace(tzinfo=timezone.utc)
    current = _now_utc(now)
    return requisites_end.astimezone(timezone.utc) <= current < merchant_end


def payfast_cancellation_is_locked(row, *, now: datetime | None = None) -> bool:
    """Не позволяет отменить счёт во время recovery или повторной проверки видео."""
    if str(row.get("direction") or "").lower() != "buy":
        return False
    if int(row.get("required_receipt_type") or 0) == 3:
        return True
    return payfast_recovery_window_is_active(row, now=now)


def payfast_requisites_are_closed(row, *, now: datetime | None = None) -> bool:
    """Закрывает клиентские действия после внутреннего срока новых PayFast BUY."""
    if str(row.get("direction") or "").lower() != "buy":
        return False
    if int(row.get("required_receipt_type") or 0) == 3:
        return False
    merchant_raw = _payment_snapshot_from_row(row).get("merchant_expires_at")
    requisites_end = row.get("expires_at")
    if not merchant_raw or not requisites_end:
        return False
    try:
        merchant_end = datetime.fromisoformat(str(merchant_raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if merchant_end.tzinfo is None:
        merchant_end = merchant_end.replace(tzinfo=timezone.utc)
    if requisites_end.tzinfo is None:
        requisites_end = requisites_end.replace(tzinfo=timezone.utc)
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc >= requisites_end.astimezone(timezone.utc)


def _order_response(row, *, payment: dict | None = None) -> dict:
    r = dict(row)
    payment_snapshot = _payment_snapshot_from_row(r)
    merchant_expires_at = payment_snapshot.get("merchant_expires_at")
    requisites_closed = payfast_requisites_are_closed(r)
    payout_tx_hash = str(r.get("payout_tx_hash") or "").strip() or None
    payout_explorer_url = None
    if payout_tx_hash and str(r.get("direction") or "").lower() == "buy":
        try:
            from buyer_payout_notify import payout_explorer_url as build_payout_explorer_url

            payout_explorer_url = build_payout_explorer_url(dict(r)) or None
        except Exception:
            payout_explorer_url = None
    out = {
        "order_id": r["order_id"],
        "status": r["status"],
        "direction": r["direction"],
        "crypto": r["crypto"],
        "crypto_amount": float(r["crypto_amount"]),
        "fiat_amount": float(r["fiat_amount"]),
        "rate": float(r["rate"]),
        "requisites": r["requisites"],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
        "merchant_expires_at": merchant_expires_at,
        "requisites_closed": requisites_closed,
        "sub_token": r.get("sub_token"),
        "merchant_id": r.get("merchant_id") or payment_snapshot.get("merchant_id"),
        "required_receipt_type": int(r["required_receipt_type"]) if r.get("required_receipt_type") else None,
        "deposit_wallet": payment.get("deposit_wallet") if payment else None,
        "payment": payment,
        "payout_tx_hash": payout_tx_hash,
        "payout_explorer_url": payout_explorer_url,
        "order_source": r.get("order_source"),
        "receipt_submitted": bool(str(r.get("receipt_file") or "").strip()),
    }
    return out


async def create_web_order(
    *,
    user_id: int,
    direction: str,
    crypto: str,
    network: str | None,
    fiat_amount: float | None,
    crypto_amount: float | None,
    requisites: str,
    sub_token: str | None,
    plan_mode: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    fingerprint: str | None = None,
    payin_round_up: bool = False,
    order_source: str = "site",
) -> dict:
    if maintenance_mode():
        raise HTTPException(status_code=503, detail=MAINTENANCE_MESSAGE)

    direction = direction.lower()
    if direction not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="direction must be buy or sell")
    crypto = crypto.lower()
    if crypto not in ("btc", "usdt", "trx", "ltc"):
        raise HTTPException(status_code=400, detail="Unsupported crypto")

    from bot_status_bridge import is_user_banned as _is_banned
    _banned, _, _ban_type = await _is_banned(user_id)
    if _banned:
        if _ban_type == "soft":
            raise HTTPException(
                status_code=503,
                detail="Сейчас нет операторов на смене. Попробуйте позже.",
            )
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован.")

    req = (requisites or "").strip()
    if direction == "buy":
        try:
            validate_buy_wallet(crypto, network, req)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        req = req.split()[0].strip()
    else:
        try:
            validate_sell_fiat_requisites(req)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    await enforce_one_active_order_per_ip(client_ip, user_id, user_agent)

    from ip_order_guard import count_recent_orders_by_ip

    if client_ip and await count_recent_orders_by_ip(client_ip) >= 3:
        await log_ip_event(
            ip=client_ip,
            event="create_denied_ip_rate_limit",
            user_id=user_id,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=429,
            detail="Слишком много заявок с вашего IP. Попробуйте позже.",
        )

    # Антифрод по устройству: лимит заявок с одного fingerprint за окно
    if fingerprint:
        from ip_order_guard import count_recent_orders_by_fingerprint

        if await count_recent_orders_by_fingerprint(fingerprint) >= 3:
            if client_ip:
                await log_ip_event(
                    ip=client_ip,
                    event="create_denied_device_rate_limit",
                    user_id=user_id,
                    user_agent=user_agent,
                    extra={"fingerprint": fingerprint},
                )
            raise HTTPException(
                status_code=429,
                detail="Слишком много заявок с этого устройства. Попробуйте позже.",
            )

    active_row = await _get_active_order(user_id)
    if active_row:
        if client_ip:
            await log_ip_event(
                ip=client_ip,
                event="create_denied_user_active",
                order_id=active_row["order_id"],
                user_id=user_id,
                user_agent=user_agent,
            )
        raise HTTPException(
            status_code=409,
            detail=_active_order_conflict(str(active_row["order_id"])),
        )

    if await _count_recent_orders(user_id) >= 3:
        if client_ip:
            await log_ip_event(
                ip=client_ip,
                event="create_denied_rate_limit",
                user_id=user_id,
                user_agent=user_agent,
            )
        raise HTTPException(
            status_code=429,
            detail="Слишком много заявок за короткое время. Попробуйте позже.",
        )

    if direction == "buy":
        cooldown_sec = await _unpaid_cooldown_remaining_sec(user_id)
        if cooldown_sec > 0:
            if client_ip:
                await log_ip_event(
                    ip=client_ip,
                    event="create_denied_unpaid_cooldown",
                    user_id=user_id,
                    user_agent=user_agent,
                    extra={"retry_after_sec": cooldown_sec},
                )
            raise HTTPException(
                status_code=429,
                detail=_unpaid_cooldown_detail(cooldown_sec),
            )

    try:
        market = await (
            get_sell_market_rates() if direction == "sell" else get_rates_cached()
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Rates temporarily unavailable")

    need_rates: dict | None = None
    if direction == "buy" and (crypto_amount is None or fiat_amount is not None):
        try:
            need_rates = await get_need_rates_cached()
        except Exception:
            need_rates = {}

    crypto_amt, fiat, rate = _validate_amounts(
        crypto,
        direction,
        fiat_amount,
        crypto_amount,
        market,
        buy_fiat_is_market_base=(direction == "buy"),
        need=need_rates,
    )
    crypto_sym = _crypto_symbol(crypto, network)

    if direction == "sell":
        # Продажа без смены не автоматизируется. Покупку гейтит create_buy_web —
        # там известна итоговая сумма и ставится флаг auto_served.
        from auto_service_gate import resolve_no_shift_access

        gate = await resolve_no_shift_access(user_id, "sell", int(fiat))
        if gate.kind == "block":
            raise HTTPException(
                status_code=503,
                detail="Сейчас нет операторов на смене. Попробуйте позже.",
            )

        order_id = _generate_order_id()
        for _ in range(3):
            try:
                await _insert_order(
                    order_id=order_id,
                    user_id=user_id,
                    crypto_sym=crypto_sym,
                    direction="sell",
                    crypto_amount=float(crypto_amt),
                    fiat_amount=float(fiat),
                    rate=float(rate),
                    requisites=req,
                    economics_snapshot=build_economics_snapshot(
                        "sell",
                        crypto_sym,
                        float(fiat),
                        float(crypto_amt),
                        float(rate),
                    ),
                    client_ip=client_ip,
                    order_source=order_source,
                )
                break
            except asyncpg.UniqueViolationError:
                order_id = _generate_order_id()
        else:
            raise HTTPException(status_code=500, detail="Could not create order")

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET status = 'OPERATOR_PENDING', expires_at = now() + interval '24 hours'
                WHERE order_id = $1
                """,
                order_id,
            )
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1", order_id
            )
        if client_ip:
            await log_ip_event(
                ip=client_ip,
                event="create_ok",
                order_id=order_id,
                user_id=user_id,
                user_agent=user_agent,
                extra={
                    "direction": "sell",
                    "crypto": crypto_sym,
                    "mode": "operator",
                    "fingerprint": fingerprint,
                },
            )
        payment = _sell_payment_for_row(row)
        await _safe_notify_ops(
            "created",
            dict(row),
            note=_ops_channel_note(
                row,
                "продажа на постоянный адрес"
                if payment["type"] == "deposit"
                else "продажа на оператора",
            ),
        )
        out = _order_response(row, payment=payment)
        out["operator_message"] = payment["message"]
        return out

    if not sub_token:
        raise HTTPException(status_code=400, detail="sub_token required (CARDRUB or SBPRUB)")

    from buy_order_web import create_buy_web

    buy_result = await create_buy_web(
        user_id=user_id,
        crypto_sym=crypto_sym,
        crypto_amount=float(crypto_amt),
        fiat_amount=int(fiat),
        rate=float(rate),
        requisites=req,
        sub_token=sub_token,
        plan_mode=plan_mode,
        client_ip=client_ip,
        accept_round_up=bool(payin_round_up),
        order_source=order_source,
        buy_markup_override=(
            float(rate) / float(market.get(crypto.lower()) or 0)
            if float(market.get(crypto.lower()) or 0) > 0
            else None
        ),
    )
    if buy_result.get("requisite_retry") and not buy_result.get("row"):
        return buy_result

    if buy_result.get("status") == "OPERATOR_PENDING":
        row = buy_result["row"]
        await _safe_notify_ops(
            "created", dict(row), note=_ops_channel_note(row, "через оператора")
        )
        out = _order_response(row, payment={"type": "operator", "message": buy_result.get("operator_message")})
        out["operator_message"] = buy_result.get("operator_message")
        return out

    row = buy_result["row"]
    bill = buy_result.get("bill") or {}
    link = buy_result.get("link") or ""
    if client_ip:
        await log_ip_event(
            ip=client_ip,
            event="create_ok",
            order_id=row["order_id"],
            user_id=user_id,
            user_agent=user_agent,
            extra={
                "direction": "buy",
                "crypto": crypto_sym,
                "sub_token": sub_token,
                "fingerprint": fingerprint,
            },
        )
    await _safe_notify_ops("created", dict(row), note=_ops_channel_note(row))
    payment = _payment_from_row(row) or {
        "type": "buy",
        "bill": bill,
        "pay_link": link,
        "fiat_amount": int(row["fiat_amount"]),
        "parts_count": buy_result.get("parts_count", 1),
        "part_index": buy_result.get("part_index", 1),
    }
    return _order_response(row, payment=payment)


async def get_order_for_user(
    order_id: str, user_id: int, client_ip: str | None = None
) -> dict | None:
    row = await _fetch_order_row_for_web(order_id, user_id, client_ip)
    if not row:
        return None
    payment = None
    if row["status"] in ACTIVE_STATUSES:
        if row["direction"] == "sell":
            payment = _sell_payment_for_row(row)
        elif row["direction"] == "buy":
            payment = buy_payment_for_active_row(row)
    out = _attach_buy_operator_message(_order_response(row, payment=payment), row, payment)
    if row["direction"] == "sell":
        out["crypto_confirmed"] = row.get("crypto_confirmed_at") is not None
        available, confirmed = await _payout_receipt_state(order_id)
        out["payout_receipt_available"] = available
        out["payout_receipt_confirmed"] = confirmed
    return await _attach_wallet_confirm(out)


async def _attach_wallet_confirm(out: dict) -> dict:
    order_id = str(out.get("order_id") or "")
    if not order_id:
        return out
    try:
        from payout_wallet_confirm import wallet_confirm_for_order

        view = await wallet_confirm_for_order(order_id)
    except Exception as exc:
        logger.warning("wallet confirm view skipped order=%s: %s", order_id, exc)
        return out
    if view:
        out["wallet_confirm"] = view
    return out


async def _payout_receipt_state(order_id: str) -> tuple[bool, bool]:
    from payout_client_receipt import payout_receipt_state

    return await payout_receipt_state(order_id)


async def confirm_order_paid(
    order_id: str, user_id: int, client_ip: str | None = None
) -> dict:
    row_raw = await get_order_for_user(order_id, user_id, client_ip)
    if not row_raw:
        raise HTTPException(status_code=404, detail="Order not found")
    # Веб-SELL создаётся сразу OPERATOR_PENDING — для него это тоже «Я оплатил».
    allowed = ("CREATED", "OPERATOR_PENDING") if row_raw["direction"] == "sell" else ("CREATED",)
    if row_raw["status"] not in allowed:
        raise HTTPException(status_code=400, detail="Order cannot be confirmed in this status")
    if row_raw["direction"] == "buy" and row_raw.get("requisites_closed"):
        raise HTTPException(
            status_code=409,
            detail="Реквизиты закрыты. Если перевод уже отправлен, напишите оператору.",
        )

    pool = await get_pool()
    from bot_status_bridge import update_order_status as bot_set_status
    from bot_status_bridge import update_order_to_awaiting_check as bot_awaiting_check

    if row_raw["direction"] == "buy":
        req_type = 2
        if not await bot_awaiting_check(order_id, req_type):
            raise HTTPException(status_code=409, detail="Cannot update order status")
        async with pool.acquire() as conn:
            refreshed = await conn.fetchrow(
                "SELECT * FROM orders WHERE order_id = $1 AND user_id = $2",
                order_id,
                user_id,
            )
        if refreshed:
            await _safe_notify_ops(
                "awaiting_receipt",
                dict(refreshed),
                note=_ops_channel_note(refreshed, "пользователь нажал «Оплатил»"),
            )
        msg = "Upload PDF receipt"
        return {
            "status": "AWAITING_CHECK",
            "message": msg,
            "requires_receipt": True,
            "required_receipt_type": req_type,
        }

    if not await bot_set_status(order_id, "PENDING"):
        raise HTTPException(status_code=409, detail="Cannot update order status")
    from callback_signatures import sign_order

    async with pool.acquire() as conn:
        refreshed = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1 AND user_id = $2",
            order_id,
            user_id,
        )
    if refreshed:
        await _safe_notify_ops(
            "awaiting_payout",
            dict(refreshed),
            note=_ops_channel_note(refreshed, "продажа"),
            pay_signature=sign_order(order_id),
            sell=True,
        )
    return {"status": "PENDING", "message": "Sent for review", "requires_receipt": False}


async def cancel_web_order(
    order_id: str, user_id: int, client_ip: str | None = None
) -> dict:
    row = await _fetch_order_row_for_web(order_id, user_id, client_ip)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    if row["status"] not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled")
    if payfast_cancellation_is_locked(row):
        raise HTTPException(
            status_code=409,
            detail="Отменить заявку сейчас нельзя: обратитесь к оператору.",
        )

    from payin_requisite_rail import is_payin_order

    if (
        row["direction"] == "buy"
        and not is_payin_order(row)
        and (row.get("merchant_order_id") or row.get("order_id"))
    ):
        try:
            from merchant_api_helpers import cancel_payin_for_order

            await cancel_payin_for_order(dict(row))
        except Exception as e:
            logger.warning("merchant cancel failed: %s", e)

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "CANCELED"):
        raise HTTPException(
            status_code=503,
            detail="Order cancellation temporarily unavailable",
        )
    return {"status": "CANCELED"}


async def attach_receipt(
    order_id: str,
    user_id: int,
    receipt_url: str,
    client_ip: str | None = None,
    receipt_file: str | None = None,
) -> dict:
    row = await _fetch_order_row_for_web(order_id, user_id, client_ip)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            order_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        if row["status"] != "AWAITING_CHECK":
            raise HTTPException(status_code=400, detail="Receipt not expected now")
        if row["direction"] != "buy":
            raise HTTPException(status_code=400, detail="Receipt only for buy orders")
        if payfast_requisites_are_closed(row):
            raise HTTPException(
                status_code=409,
                detail="Реквизиты закрыты. Если перевод уже отправлен, напишите оператору.",
            )
        from payin_requisite_rail import is_payin_order

        payin_rail = is_payin_order(row)
        if not payin_rail and not row.get("order_id") and not row.get("merchant_order_id"):
            raise HTTPException(status_code=400, detail="No merchant order id")

        # Сохраняем имя файла, чтобы админ мог посмотреть чек.
        if receipt_file:
            await conn.execute(
                "UPDATE orders SET receipt_file = $1, updated_at = now() WHERE order_id = $2",
                receipt_file,
                order_id,
            )

    order = dict(row)
    if receipt_file:
        order["receipt_file"] = receipt_file
    from order_source import uses_bot_receipt_route
    from payin_requisite_rail import order_reki_payfast_id

    if uses_bot_receipt_route(order.get("order_source")) or order_reki_payfast_id(order):
        return await _attach_bot_receipt(order, receipt_file)

    if not payin_rail:
        from merchant_api_helpers import payin_set_check_for_order, payfast_set_check_already_paid

        result = await payin_set_check_for_order(dict(row), receipt_url)
        if int(result.get("status") or 500) >= 400 and not payfast_set_check_already_paid(result):
            body = result.get("body") if isinstance(result.get("body"), dict) else {}
            err = str((body or {}).get("error") or "Merchant rejected receipt")
            if err.startswith("receipt_url_not_fetchable"):
                raise HTTPException(
                    status_code=503,
                    detail=f"Чек не удалось отдать мерчанту ({err}). Проверьте файл и секреты подписи.",
                )
            raise HTTPException(status_code=502, detail="Merchant rejected receipt")

    from bot_status_bridge import update_order_status as bot_set_status

    if not await bot_set_status(order_id, "PENDING"):
        raise HTTPException(status_code=409, detail="Cannot update order status")
    async with pool.acquire() as conn:
        refreshed = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1 AND user_id = $2",
            order_id,
            user_id,
        )
    if refreshed:
        await _safe_notify_ops(
            "receipt_attached",
            dict(refreshed),
            note=_ops_channel_note(
                refreshed,
                "ждём подтверждения оператора"
                if payin_rail
                else "ждём подтверждения мерчанта",
            ),
        )
    if not payin_rail:
        try:
            from bot_status_bridge import try_complete_if_payfast_settled

            await try_complete_if_payfast_settled(order_id)
        except Exception as e:
            logger.warning("payfast settle after web receipt failed order=%s: %s", order_id, e)
    return {"status": "PENDING", "message": "Receipt submitted"}

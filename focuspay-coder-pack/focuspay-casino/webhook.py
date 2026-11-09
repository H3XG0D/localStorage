"""Webhook для подписанных callback-ов о статусе FocusPay сделок."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Request

from bot import bot
from config import FOCUSPAY_EXCHANGER_SECRET
from focuspay_client import get_focuspay_client
from wagering import wagering_hint

logger = logging.getLogger(__name__)

app = FastAPI(title="FocusCasino Webhook")

_CLIENT_TRANSACTION_ID_RE = re.compile(
    r"^casino-dep-([1-9]\d*)-([A-Za-z0-9_-]{1,96})$"
)
CALLBACK_MAX_SKEW_SECONDS = 5 * 60
_CALLBACK_REPLAY_TTL_SECONDS = CALLBACK_MAX_SKEW_SECONDS + 60
_CALLBACK_REPLAY_MAX_SIZE = 10_000


class CallbackReplayCache:
    """Краткоживущая защита от повторной доставки одного callback-а."""

    def __init__(self, *, ttl_seconds: int, max_size: int):
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def clear(self) -> None:
        self._seen.clear()

    def _purge(self, now: float) -> None:
        while self._seen:
            _, seen_at = next(iter(self._seen.items()))
            if now - seen_at <= self.ttl_seconds and len(self._seen) <= self.max_size:
                break
            self._seen.popitem(last=False)

    def seen_or_add(self, key: str, *, now: float | None = None) -> bool:
        current = float(time.time() if now is None else now)
        self._purge(current)
        if key in self._seen:
            return True
        self._seen[key] = current
        return False

    def discard(self, key: str) -> None:
        self._seen.pop(key, None)


callback_replay_cache = CallbackReplayCache(
    ttl_seconds=_CALLBACK_REPLAY_TTL_SECONDS,
    max_size=_CALLBACK_REPLAY_MAX_SIZE,
)


def verify_callback_signature(
    body: bytes,
    *,
    secret: str,
    timestamp: str | None,
    signature: str | None,
    now: int | None = None,
) -> bool:
    """Проверить HMAC(timestamp + raw body), совместимый с Exchanger API."""
    configured_secret = secret.strip()
    if not configured_secret or not timestamp or not signature:
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(time.time() if now is None else now)
    if abs(current - timestamp_value) > CALLBACK_MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(
        configured_secret.encode("utf-8"),
        timestamp.encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def extract_telegram_id(client_tx_id: object) -> int:
    """Извлечь Telegram ID из server-stored casino-dep transaction ID."""
    match = _CLIENT_TRANSACTION_ID_RE.fullmatch(str(client_tx_id or "").strip())
    if not match:
        raise ValueError("Invalid casino client_transaction_id")
    return int(match.group(1))


def _positive_deal_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("deal_id must be a positive integer")
    return value


def _positive_amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount_rub must be a number") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("amount_rub must be > 0")
    return amount


def _callback_replay_key(timestamp: str, body: bytes) -> str:
    return hashlib.sha256(timestamp.encode("utf-8") + b"\0" + body).hexdigest()


def _callback_event(payload: Mapping[str, Any]) -> str:
    event = str(payload.get("event") or "").strip().lower()
    if event not in {"credited", "cancelled"}:
        raise HTTPException(status_code=400, detail="Unsupported callback event")
    return event


async def _authoritative_deal(client: Any, deal_id: int) -> Mapping[str, Any]:
    """Загрузить сделку в HMAC-scoped exchanger API, не доверяя callback body."""
    try:
        deal = await client.get_deal_status(deal_id)
        if not isinstance(deal, Mapping):
            raise ValueError("Deal response must be an object")
        authoritative_id = _positive_deal_id(deal.get("deal_id") or deal.get("id"))
    except Exception as exc:
        logger.warning("Unable to load authoritative casino deal=%s", deal_id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Unable to load authoritative deal",
        ) from exc

    if authoritative_id != deal_id:
        raise HTTPException(status_code=409, detail="Callback deal does not match authoritative deal")
    return deal


def _verify_authoritative_event(deal: Mapping[str, Any], event: str) -> int:
    expected_status = "confirmed" if event == "credited" else "cancelled"
    status = str(deal.get("status") or "").strip().lower()
    if status != expected_status:
        raise HTTPException(status_code=409, detail="Callback event does not match authoritative deal")
    try:
        return extract_telegram_id(deal.get("client_transaction_id"))
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="Authoritative deal has invalid casino transaction id",
        ) from exc


def _credit_notification_data(
    result: object,
    *,
    deal_id: int,
    telegram_id: int,
) -> Decimal:
    if not isinstance(result, Mapping):
        raise HTTPException(status_code=503, detail="Durable casino deposit credit is not available")
    try:
        credited_deal_id = _positive_deal_id(result.get("deal_id"))
        credited_telegram_id = _positive_deal_id(result.get("telegram_id"))
        amount_rub = _positive_amount(result.get("amount_rub"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Invalid durable casino deposit credit response") from exc
    if credited_deal_id != deal_id or credited_telegram_id != telegram_id:
        raise HTTPException(status_code=409, detail="Durable casino deposit credit conflicts")
    return amount_rub


@app.post("/webhook")
async def focuspay_webhook(request: Request):
    """Обработать подписанный сигнал о статусе сделки FocusPay."""
    body = await request.body()
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")
    secret = FOCUSPAY_EXCHANGER_SECRET.strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Callback signature is not configured")
    if not verify_callback_signature(
        body,
        secret=secret,
        timestamp=timestamp,
        signature=signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid callback signature")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = _callback_event(payload)
    try:
        deal_id = _positive_deal_id(payload.get("deal_id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    replay_key = _callback_replay_key(timestamp or "", body)
    if callback_replay_cache.seen_or_add(replay_key):
        raise HTTPException(status_code=409, detail="Callback replay rejected")

    try:
        client = await get_focuspay_client()
        deal = await _authoritative_deal(client, deal_id)
        telegram_id = _verify_authoritative_event(deal, event)

        if event == "credited":
            try:
                credit_result = await client.credit_deposit(deal_id=deal_id)
            except Exception as exc:
                logger.warning("Casino deposit credit failed deal=%s", deal_id, exc_info=True)
                raise HTTPException(
                    status_code=503,
                    detail="Durable casino deposit credit is not available",
                ) from exc
            amount_rub = _credit_notification_data(
                credit_result,
                deal_id=deal_id,
                telegram_id=telegram_id,
            )
            try:
                wagering_data = await client.get_wagering(telegram_id)
                progress_hint = wagering_hint(wagering_data, currency_symbol="₽")
            except Exception:
                logger.debug("Wagering progress unavailable after deposit for %s", telegram_id, exc_info=True)
                progress_hint = ""
            try:
                await bot.send_message(
                    telegram_id,
                    f"✅ Пополнение успешно!\n\n"
                    f"Сумма: {amount_rub:.2f} ₽\n"
                    f"Номер сделки: #{deal_id}\n\n"
                    f"Теперь вы можете начать игру!{progress_hint}",
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Failed to send deposit notification to user %s", telegram_id)

            logger.info("Casino deposit credited: deal_id=%s telegram_id=%s", deal_id, telegram_id)
            return {
                "success": True,
                "event": "credited",
                "deal_id": deal_id,
                "idempotent": bool(credit_result.get("idempotent", False)),
            }

        try:
            await bot.send_message(
                telegram_id,
                f"❌ Заявка на пополнение #{deal_id} отменена.\n\n"
                f"Если это ошибка, обратитесь в поддержку.",
            )
        except Exception:
            logger.exception("Failed to notify user about cancellation")
        return {"success": True, "event": "cancelled", "deal_id": deal_id}
    except HTTPException:
        callback_replay_cache.discard(replay_key)
        raise
    except Exception as exc:
        callback_replay_cache.discard(replay_key)
        logger.exception("Unexpected casino callback failure deal=%s", deal_id)
        raise HTTPException(status_code=503, detail="Unable to process callback") from exc


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from config import WEBHOOK_PORT

    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT)

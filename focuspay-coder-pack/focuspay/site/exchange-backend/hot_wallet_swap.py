"""Отправка BTC/LTC с горячего кошелька старшим финансистом и запись комиссии свапа.

Это не выплата по заявке: вид payout_requests — swap_send, рекон смены не пишется.
Комиссия попадает в swap_commission_entries только после tx подписанта.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from config import settings
from project_wallet_payout import (
    PREVIEW_TTL_SEC,
    Check,
    WalletPayoutError,
    consume_totp,
    fingerprint,
    limit_checks,
    notify_admin,
    operator_lock,
    own_addresses,
    rate_close,
    wallet_checks,
)
from wallet_validation import validate_buy_wallet

logger = logging.getLogger("hot_wallet_swap")

SWAP_SEND_KIND = "swap_send"
SEND_COINS = ("btc", "ltc")
FEE_COINS = ("usdt", "btc", "ltc", "trx", "rub")

INSERT_PANEL_COMMISSION_SQL = """
INSERT INTO swap_commission_entries (
    chat_id, message_id, part_index, raw_text, crypto, crypto_amount,
    rate_rub, amount_rub, operator_id, send_request_id, dest_address
)
VALUES (NULL, NULL, 0, $1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (send_request_id) DO NOTHING
RETURNING id
"""


class SwapPreviewIn(BaseModel):
    coin: Literal["btc", "ltc"]
    address: str = Field(..., min_length=10, max_length=200)
    crypto_amount: Decimal = Field(..., gt=0)
    fee_crypto: Literal["usdt", "btc", "ltc", "trx", "rub"]
    fee_amount: Decimal = Field(..., gt=0)

    @field_validator("crypto_amount", "fee_amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: Any) -> Decimal:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("Введите число") from None
        if not amount.is_finite():
            raise ValueError("Введите число")
        return amount


class SwapConfirmIn(SwapPreviewIn):
    preview_token: str = Field(..., min_length=10, max_length=4000)
    totp_code: str = Field(..., min_length=6, max_length=8)


@dataclass(frozen=True)
class SwapQuote:
    coin: str
    address: str
    crypto_amount: Decimal
    send_rate: float
    send_rub: float
    fee_crypto: str
    fee_amount: Decimal
    fee_rate: float
    fee_rub: float

    def form_fp(self) -> str:
        return fingerprint(
            {
                "coin": self.coin,
                "address": self.address,
                "amount": f"{self.crypto_amount:.8f}",
                "fee_crypto": self.fee_crypto,
                "fee_amount": f"{self.fee_amount:.8f}",
            }
        )


def _secret() -> bytes:
    key = (settings.secret_key or "").encode()
    if not key:
        raise WalletPayoutError(503, "not_configured", "Сервер не настроен (secret_key)")
    return hashlib.sha256(b"hot-wallet-swap:" + key).digest()


def _q8(amount: Decimal, label: str) -> Decimal:
    if not amount.is_finite() or amount <= 0:
        raise WalletPayoutError(400, "bad_amount", f"{label} должна быть больше нуля")
    quant = amount.quantize(Decimal("0.00000001"))
    if quant != amount:
        raise WalletPayoutError(400, "bad_amount", f"{label}: не больше 8 знаков после запятой")
    return quant


def clean_address(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    return text.split()[0]


async def assert_destination(coin: str, address: str) -> str:
    addr = clean_address(address)
    wrong_network = (
        (coin == "btc" and (addr.startswith("ltc1") or addr.startswith("0x") or addr.startswith("T")))
        or (coin == "ltc" and (addr.startswith("bc1") or addr.startswith("0x") or addr.startswith("T")))
    )
    if wrong_network:
        raise WalletPayoutError(
            400,
            "bad_address",
            f"Похоже на адрес другой сети. Для {coin.upper()} нужен адрес {coin.upper()}.",
        )
    try:
        validate_buy_wallet(coin, None, addr)
    except ValueError as exc:
        raise WalletPayoutError(400, "bad_address", str(exc)) from None
    own = {item.strip().lower() for item in await own_addresses() if item and item.strip()}
    if addr.lower() in own:
        raise WalletPayoutError(400, "address_own", "Это адрес пополнения проекта")
    return addr


async def market_rub_per_unit(crypto: str) -> float:
    coin = (crypto or "").strip().lower()
    if coin == "rub":
        return 1.0
    if coin not in FEE_COINS:
        raise WalletPayoutError(400, "bad_fee_crypto", "Неизвестная валюта комиссии")
    from routers.public import get_exchanger_rates_cached, get_need_rates_cached, merge_sell_market

    need: dict = {}
    rapira: dict = {}
    try:
        need = await get_need_rates_cached()
    except Exception:
        logger.warning("swap send: coingecko rate unavailable", exc_info=True)
    try:
        rapira = await get_exchanger_rates_cached()
    except Exception:
        logger.warning("swap send: rapira rate unavailable", exc_info=True)
    price = float(merge_sell_market(need, rapira).get(coin) or 0)
    if price <= 0:
        raise WalletPayoutError(503, "no_rate", f"Нет курса для {coin.upper()}")
    return price


def _rub(rate: float, amount: Decimal) -> float:
    value = round(float(rate) * float(amount), 2)
    if value <= 0 or value > 9_999_999_999_999:
        raise WalletPayoutError(400, "bad_amount", "Сумма в рублях вне допустимого диапазона")
    return value


async def quote_swap(body: SwapPreviewIn) -> SwapQuote:
    coin = body.coin.strip().lower()
    if coin not in SEND_COINS:
        raise WalletPayoutError(400, "bad_coin", "С горячего кошелька отправляются BTC и LTC")
    fee_crypto = body.fee_crypto.strip().lower()
    if fee_crypto not in FEE_COINS:
        raise WalletPayoutError(400, "bad_fee_crypto", "Валюта комиссии: USDT, BTC, LTC, TRX или рубли")
    address = await assert_destination(coin, body.address)
    crypto_amount = _q8(body.crypto_amount, "Сумма отправки")
    fee_amount = _q8(body.fee_amount, "Комиссия")
    send_rate = await market_rub_per_unit(coin)
    fee_rate = 1.0 if fee_crypto == "rub" else await market_rub_per_unit(fee_crypto)
    return SwapQuote(
        coin=coin,
        address=address,
        crypto_amount=crypto_amount,
        send_rate=send_rate,
        send_rub=_rub(send_rate, crypto_amount),
        fee_crypto=fee_crypto,
        fee_amount=fee_amount,
        fee_rate=fee_rate,
        fee_rub=_rub(fee_rate, fee_amount),
    )


def make_swap_token(*, operator_id: int, shift_id: int, request_id: str, quote: SwapQuote) -> str:
    payload = {
        "op": int(operator_id),
        "shift": int(shift_id),
        "fp": quote.form_fp(),
        "req": request_id,
        "coin": quote.coin,
        "addr": quote.address,
        "amt": f"{quote.crypto_amount:.8f}",
        "rub": quote.send_rub,
        "rate": quote.send_rate,
        "fee_cur": quote.fee_crypto,
        "fee_amt": f"{quote.fee_amount:.8f}",
        "fee_rub": quote.fee_rub,
        "fee_rate": quote.fee_rate,
        "exp": int(time.time()) + PREVIEW_TTL_SEC,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def read_swap_token(token: str, *, operator_id: int, fp: str) -> dict[str, Any]:
    try:
        raw, sig = str(token or "").rsplit(".", 1)
    except ValueError:
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново") from None
    expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново")
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, json.JSONDecodeError):
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново") from None
    if int(payload.get("op") or 0) != int(operator_id):
        raise WalletPayoutError(403, "bad_token", "Окно подтверждения открыто другим оператором")
    if int(payload.get("exp") or 0) < time.time():
        raise WalletPayoutError(409, "token_expired", "Окно устарело — откройте подтверждение заново")
    if payload.get("fp") != fp:
        raise WalletPayoutError(
            409,
            "data_changed",
            "Сумма или адрес изменились — откройте подтверждение заново",
        )
    if not str(payload.get("req") or "").startswith(f"swap:{int(operator_id)}:"):
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново")
    return payload


def new_request_id(operator_id: int) -> str:
    return f"swap:{int(operator_id)}:{uuid.uuid4().hex}"


async def run_swap_checks(conn, *, operator_id: int, quote: SwapQuote) -> tuple[list[Check], dict]:
    try:
        limits, limit_info = await limit_checks(
            conn, operator_id=operator_id, amount_rub=quote.send_rub
        )
    except Exception:
        logger.warning("swap send limit checks failed", exc_info=True)
        limits = [Check("limit_wallet_day", False, "лимиты кошелька недоступны")]
        limit_info = {}
    try:
        wallet, wallet_info = await wallet_checks(
            conn,
            coin=quote.coin,
            crypto_amount=float(quote.crypto_amount),
            rate_rub=quote.send_rate,
        )
    except Exception:
        logger.warning("swap send wallet checks failed", exc_info=True)
        wallet = [Check("signer", False, "кошелёк не на связи")]
        wallet_info = {}
    return limits + wallet, {**limit_info, **wallet_info}


def _public_quote(quote: SwapQuote, checks: list[Check], info: dict, *, token: str | None, request_id: str) -> dict:
    ok = all(item.ok for item in checks)
    return {
        "ok": ok and bool(token),
        "preview_token": token,
        "expires_in": PREVIEW_TTL_SEC if token else 0,
        "request_id": request_id,
        "coin": quote.coin,
        "address": quote.address,
        "crypto_amount": float(quote.crypto_amount),
        "amount_rub": quote.send_rub,
        "market_rate": round(quote.send_rate, 2),
        "fee_crypto": quote.fee_crypto,
        "fee_amount": float(quote.fee_amount),
        "fee_rate_rub": round(quote.fee_rate, 2),
        "fee_amount_rub": quote.fee_rub,
        "checks": [item.out() for item in checks],
        **info,
    }


async def preview(*, operator_id: int, shift_id: int, body: SwapPreviewIn) -> dict:
    quote = await quote_swap(body)
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        checks, info = await run_swap_checks(conn, operator_id=operator_id, quote=quote)
    ok = all(item.ok for item in checks)
    request_id = new_request_id(operator_id)
    token = make_swap_token(
        operator_id=operator_id, shift_id=shift_id, request_id=request_id, quote=quote
    ) if ok else None
    return _public_quote(quote, checks, info, token=token, request_id=request_id)


def _pinned_quote(payload: dict[str, Any]) -> SwapQuote:
    return SwapQuote(
        coin=str(payload["coin"]),
        address=str(payload["addr"]),
        crypto_amount=Decimal(str(payload["amt"])),
        send_rate=float(payload["rate"]),
        send_rub=float(payload["rub"]),
        fee_crypto=str(payload["fee_cur"]),
        fee_amount=Decimal(str(payload["fee_amt"])),
        fee_rate=float(payload["fee_rate"]),
        fee_rub=float(payload["fee_rub"]),
    )


def _result(payload: dict[str, Any], *, txid: str, already_sent: bool) -> dict:
    quote = _pinned_quote(payload)
    return {
        "txid": txid,
        "request_id": str(payload["req"]),
        "coin": quote.coin,
        "crypto_amount": float(quote.crypto_amount),
        "amount_rub": quote.send_rub,
        "fee_crypto": quote.fee_crypto,
        "fee_amount": float(quote.fee_amount),
        "fee_amount_rub": quote.fee_rub,
        "address": quote.address,
        "already_sent": already_sent,
    }


async def insert_panel_commission(conn, *, operator_id: int, quote: SwapQuote, request_id: str) -> int | None:
    raw = f"{quote.fee_amount:.8f} {quote.fee_crypto.upper()}"
    row_id = await conn.fetchval(
        INSERT_PANEL_COMMISSION_SQL,
        raw[:2000],
        quote.fee_crypto,
        float(quote.fee_amount),
        quote.fee_rate,
        quote.fee_rub,
        int(operator_id),
        request_id,
        quote.address,
    )
    return int(row_id) if row_id is not None else None


async def _load_request(conn, request_id: str) -> dict | None:
    row = await conn.fetchrow(
        "SELECT request_id, status, txid FROM payout_requests WHERE request_id = $1",
        request_id,
    )
    return dict(row) if row else None


async def _insert_request(conn, *, request_id: str, shift_id: int, operator_id: int, quote: SwapQuote) -> None:
    inserted = await conn.fetchval(
        """
        INSERT INTO payout_requests (
            request_id, kind, ref_id, user_id, coin, address,
            amount_crypto, amount_rub, status, operator_id
        )
        VALUES ($1, $2, $3, NULL, $4, $5, $6, $7, 'queued', $8)
        ON CONFLICT (request_id) DO NOTHING
        RETURNING request_id
        """,
        request_id,
        SWAP_SEND_KIND,
        str(int(shift_id)),
        quote.coin,
        quote.address,
        quote.crypto_amount,
        round(float(quote.send_rub), 2),
        int(operator_id),
    )
    if not inserted:
        raise WalletPayoutError(
            409,
            "already_sent",
            "Эта отправка уже создана. Дождитесь проверки админом — повторно не отправляйте.",
        )


async def _record_fee_or_raise(conn, *, operator_id: int, quote: SwapQuote, request_id: str, txid: str) -> None:
    try:
        await insert_panel_commission(
            conn, operator_id=operator_id, quote=quote, request_id=request_id
        )
    except Exception as exc:
        logger.exception("swap commission insert failed request=%s", request_id)
        await notify_admin(
            f"❗️ Размен {request_id}: крипта ушла (tx <code>{txid}</code>), "
            f"комиссия свапа не записалась: {exc}"
        )
        raise WalletPayoutError(
            500,
            "fee_not_recorded",
            f"Крипта отправлена (tx {txid}), комиссия не записалась — админ проверит. "
            "Повторно не отправляйте.",
        ) from None


async def _finish_sent(
    *,
    operator_id: int,
    quote: SwapQuote,
    request_id: str,
    txid: str,
    already_sent: bool,
    payload: dict[str, Any],
) -> dict:
    from auto_payout_worker import _mark_request
    from db import get_pool
    from project_wallet_payout import mark_confirmed

    pool = await get_pool()
    async with pool.acquire() as conn:
        if not already_sent:
            await _mark_request(conn, request_id, "sent", txid)
        await _record_fee_or_raise(
            conn, operator_id=operator_id, quote=quote, request_id=request_id, txid=txid
        )
    await mark_confirmed(request_id)
    if not already_sent:
        await notify_admin(
            f"Размен: оператор #{operator_id} отправил {float(quote.crypto_amount):.8f} {quote.coin.upper()} "
            f"на <code>{quote.address}</code>. tx <code>{txid}</code>. "
            f"Комиссия свапа: {float(quote.fee_amount):.8f} {quote.fee_crypto.upper()} "
            f"→ {quote.fee_rub:,.2f} ₽".replace(",", " ")
        )
    return _result(payload, txid=txid, already_sent=already_sent)


async def confirm(*, operator_id: int, shift_id: int, body: SwapConfirmIn) -> dict:
    from auto_payout_audit_log import audit_payout_event
    from db import get_pool
    from signer_client import submit_signer_payout

    async with operator_lock(operator_id):
        draft = SwapQuote(
            coin=body.coin.strip().lower(),
            address=clean_address(body.address),
            crypto_amount=_q8(body.crypto_amount, "Сумма отправки"),
            send_rate=0,
            send_rub=0,
            fee_crypto=body.fee_crypto.strip().lower(),
            fee_amount=_q8(body.fee_amount, "Комиссия"),
            fee_rate=0,
            fee_rub=0,
        )
        payload = read_swap_token(body.preview_token, operator_id=operator_id, fp=draft.form_fp())
        if int(payload.get("shift") or 0) != int(shift_id):
            raise WalletPayoutError(409, "shift_changed", "Смена изменилась — откройте подтверждение заново")
        fresh = await quote_swap(body)
        if fresh.form_fp() != draft.form_fp() or fresh.address != str(payload.get("addr")):
            raise WalletPayoutError(409, "data_changed", "Адрес изменился — откройте подтверждение заново")
        if not rate_close(fresh.send_rate, float(payload.get("rate") or 0)):
            raise WalletPayoutError(409, "rate_moved", "Курс отправки изменился — откройте подтверждение заново")
        if not rate_close(fresh.fee_rate, float(payload.get("fee_rate") or 0)):
            raise WalletPayoutError(409, "rate_moved", "Курс комиссии изменился — откройте подтверждение заново")
        pinned = _pinned_quote(payload)
        request_id = str(payload["req"])

        pool = await get_pool()
        async with pool.acquire() as conn:
            checks, _info = await run_swap_checks(conn, operator_id=operator_id, quote=pinned)
            failed = [item for item in checks if not item.ok]
            if failed:
                raise WalletPayoutError(
                    409,
                    "checks_failed",
                    "Проверка не прошла: " + ", ".join(f"{item.key} {item.detail}".strip() for item in failed),
                )
            await consume_totp(conn, operator_id, body.totp_code)
            created = False
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"sw:{request_id}")
                prev = await _load_request(conn, request_id)
                if prev is None:
                    await _insert_request(
                        conn,
                        request_id=request_id,
                        shift_id=int(payload["shift"]),
                        operator_id=operator_id,
                        quote=pinned,
                    )
                    created = True
                    prev = await _load_request(conn, request_id)

        if not prev:
            raise WalletPayoutError(500, "enqueue_failed", "Не удалось создать отправку")
        status = str(prev.get("status") or "")
        txid = str(prev.get("txid") or "").strip()
        if status in ("sent", "confirmed") and txid:
            return await _finish_sent(
                operator_id=operator_id,
                quote=pinned,
                request_id=request_id,
                txid=txid,
                already_sent=True,
                payload=payload,
            )
        if not created:
            if status == "failed":
                raise WalletPayoutError(
                    409,
                    "rejected",
                    "Кошелёк отклонил эту отправку. Откройте проверку заново.",
                )
            raise WalletPayoutError(
                409,
                "already_sent",
                "Эта отправка уже создана. Дождитесь проверки админом — повторно не отправляйте.",
            )
        if status != "queued" or txid:
            raise WalletPayoutError(
                409,
                "already_sent",
                "Эта отправка уже создана. Дождитесь проверки админом — повторно не отправляйте.",
            )

        await audit_payout_event(request_id, "swap_send", {"operator_id": operator_id})
        st, resp = await submit_signer_payout(
            {
                "request_id": request_id,
                "coin": pinned.coin,
                "address": pinned.address,
                "amount": float(pinned.crypto_amount),
                "amount_rub": round(pinned.send_rub, 2),
                "order_ref": request_id,
                "kind": SWAP_SEND_KIND,
            }
        )
        await audit_payout_event(request_id, f"signer_{st}", resp)
        if st == "duplicate":
            st = "accepted" if resp.get("txid") else "unknown"
        if st == "rejected":
            from auto_payout_worker import _mark_request

            async with pool.acquire() as conn:
                await _mark_request(conn, request_id, "failed")
                await conn.execute(
                    "UPDATE payout_requests SET reject_reason = $2 WHERE request_id = $1",
                    request_id,
                    str(resp.get("reason") or resp.get("error") or "rejected")[:200],
                )
            reason = str(resp.get("reason") or resp.get("error") or "rejected")
            raise WalletPayoutError(
                409,
                "rejected",
                f"Кошелёк проекта отклонил отправку ({reason}). Крипта не ушла.",
            )
        txid = str(resp.get("txid") or "").strip()
        if st != "accepted" or not txid:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE payout_requests
                    SET reject_reason = 'signer_unknown', updated_at = now()
                    WHERE request_id = $1
                    """,
                    request_id,
                )
            await notify_admin(
                f"❗️ Размен {request_id}: отправка без ответа "
                f"({pinned.coin.upper()} {float(pinned.crypto_amount):.8f} → <code>{pinned.address}</code>). "
                "Проверьте по ноде, повторно не отправляйте."
            )
            raise WalletPayoutError(
                502,
                "signer_unknown",
                "Кошелёк не подтвердил отправку. Повторно не отправляйте — админ проверит.",
            )
        return await _finish_sent(
            operator_id=operator_id,
            quote=pinned,
            request_id=request_id,
            txid=txid,
            already_sent=False,
            payload=payload,
        )

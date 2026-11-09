"""focuspay-signer — isolated payout API (WireGuard only)."""
from __future__ import annotations

import hmac
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

import store
import runtime_policy
from config import settings
from receive_address import ensure_receive_address
from policy import (
    validate_address,
    validate_amount,
    validate_daily_cap,
    validate_not_blocked,
)
from wallet_rpc import (
    CASINO_DEPOSIT_LABEL,
    RpcError,
    audit_fee,
    broadcast_fee_bump,
    estimate_fee,
    fast_spend_enabled,
    get_balances,
    unconfirmed_is_spendable,
    get_node_status,
    list_confirmed_incoming,
    new_labeled_address,
    quote_fee_bump,
    quote_fee_bumps,
    presend_reject_reason,
    send_payout,
    topup_status,
    tx_fee,
    wallet_tx,
)

logger = logging.getLogger("focuspay-signer")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FocusPay Signer", docs_url=None, redoc_url=None)

_MAX_SKEW_SEC = 300
_TXID = re.compile(r"^[0-9a-fA-F]{64}$")


@app.on_event("startup")
async def _startup() -> None:
    store.init()
    runtime_policy.load()
    caps = runtime_policy.snapshot()
    logger.info(
        "signer started dry_run=%s max_tx_ltc=%.8f daily_cap_ltc=%.8f",
        settings.dry_run,
        caps["max_tx_ltc"],
        caps["daily_cap_ltc"],
    )


class RotateDepositBody(BaseModel):
    coin: str = Field(..., min_length=3, max_length=8)


class ReceiveAddressBody(BaseModel):
    coin: str = Field(..., min_length=3, max_length=8)


class ReceiveIncomingBody(BaseModel):
    coin: str = Field(..., min_length=3, max_length=8)
    addresses: list[str] = Field(..., min_length=1, max_length=500)


# order:/wd: — выплаты по заявке и выводу. swap:<оператор>:<uuid> — отправка на размен.
REQUEST_ID_PATTERN = r"^(?:(?:wd|order):[A-Za-z0-9_-]+|swap:[0-9]+:[a-f0-9]{32})$"


class PayoutBody(BaseModel):
    request_id: str = Field(..., min_length=3, max_length=128, pattern=REQUEST_ID_PATTERN)
    coin: str
    address: str
    amount: float = Field(..., gt=0)
    amount_rub: float = 0.0
    order_ref: str = ""
    kind: str = "withdrawal"
    # Потолки из админки (в монете). Если заданы — проверяем по ним.
    max_tx: float | None = Field(None, gt=0)
    daily_cap: float | None = Field(None, gt=0)


class PolicyBody(BaseModel):
    max_tx_btc: float | None = Field(None, gt=0, le=50)
    max_tx_ltc: float | None = Field(None, gt=0, le=500)
    daily_cap_btc: float | None = Field(None, gt=0, le=200)
    daily_cap_ltc: float | None = Field(None, gt=0, le=5_000)


def _audit(line: dict[str, Any]) -> None:
    path = Path(settings.audit_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.exception("audit write failed")


def _verify_hmac(request: Request, body: bytes, *, anti_replay: bool) -> None:
    api_key = (request.headers.get("x-api-key") or "").strip()
    ts = (request.headers.get("x-timestamp") or "").strip()
    sig = (request.headers.get("x-signature") or "").strip()
    secret = (settings.signer_secret_key or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Signer not configured")
    if not hmac.compare_digest(api_key, settings.signer_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        ts_i = int(ts)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid timestamp") from None
    if abs(time.time() - ts_i) > _MAX_SKEW_SEC:
        raise HTTPException(status_code=401, detail="Timestamp expired")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}".encode("utf-8") + body,
        digestmod="sha256",
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")
    # Подпись одноразовая: перехваченный запрос нельзя проиграть повторно
    # внутри окна допустимого скоса часов.
    if anti_replay and not store.remember_signature(sig):
        raise HTTPException(status_code=401, detail="Signature already used")


@app.get("/v1/health")
async def health(request: Request):
    _verify_hmac(request, await request.body(), anti_replay=False)
    return {
        "status": "ok",
        "dry_run": settings.dry_run,
        "nodes": await get_node_status(),
        "policy": runtime_policy.snapshot(),
    }


@app.post("/v1/policy")
async def set_policy(request: Request):
    """Подтянуть потолки из админки автопилота (HMAC, только с основного сервера)."""
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = PolicyBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    patch = data.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="empty_policy")
    caps = runtime_policy.save(patch)
    _audit({"event": "policy_update", "patch": patch, "policy": caps})
    return {"ok": True, "policy": caps}


@app.get("/v1/balance")
async def balance(request: Request):
    _verify_hmac(request, await request.body(), anti_replay=False)
    coins = await get_balances()
    return {"coins": coins}


@app.get("/v1/fee-estimate")
async def fee_estimate(request: Request, coin: str = "btc"):
    _verify_hmac(request, await request.body(), anti_replay=False)
    try:
        return await estimate_fee(coin)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:120]) from None


def _publish_deposit(coin: str, address: str | None, changed: bool) -> None:
    if changed and address:
        _audit({"event": "deposit_address", "coin": coin, "address": address})


@app.get("/v1/deposit-address")
async def deposit_addresses(request: Request):
    """Следующий свободный адрес. Если на текущий уже приходили монеты — новый.

    Сменённые адреса остаются в кошельке и в поле known.
    """
    _verify_hmac(request, await request.body(), anti_replay=False)
    out: dict[str, str | None] = {}
    for coin in ("btc", "ltc"):
        try:
            addr, changed = await ensure_receive_address(coin)
        except Exception:
            logger.warning("deposit address for %s unavailable", coin, exc_info=True)
            addr, changed = store.deposit_address(coin), False
        _publish_deposit(coin, addr, changed)
        out[coin] = addr
    return {"addresses": out, "known": store.list_deposit_addresses()}


@app.post("/v1/deposit-address")
async def rotate_deposit_address(request: Request):
    """Сменить показанный адрес до прихода монет. Прежний продолжает принимать."""
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = RotateDepositBody.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(status_code=400, detail="invalid_body") from None
    coin = data.coin.lower().strip()
    try:
        addr, changed = await ensure_receive_address(coin, force=True)
    except Exception as exc:
        logger.warning("deposit rotate failed for %s", coin, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)[:120]) from None
    if not addr:
        raise HTTPException(status_code=400, detail="address_unavailable")
    _publish_deposit(coin, addr, changed)
    return {
        "ok": True,
        "coin": coin,
        "address": addr,
        "known": store.list_deposit_addresses(),
    }


def _coin_or_400(coin: str) -> str:
    name = (coin or "").lower().strip()
    if name not in ("btc", "ltc"):
        raise HTTPException(status_code=400, detail="unsupported_coin")
    return name


@app.post("/v1/receive-address")
async def receive_address(request: Request):
    """Адрес клиента казино. Текущий адрес дома не меняется и в known не пишется."""
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = ReceiveAddressBody.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(status_code=400, detail="invalid_body") from None
    coin = _coin_or_400(data.coin)
    try:
        addr = await new_labeled_address(coin, CASINO_DEPOSIT_LABEL)
    except RpcError as exc:
        logger.warning("casino receive address failed for %s", coin, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)[:120]) from None
    _audit({"event": "casino_receive_address", "coin": coin, "address": addr})
    return {"ok": True, "coin": coin, "address": addr, "label": CASINO_DEPOSIT_LABEL}


@app.post("/v1/receive-incoming")
async def receive_incoming(request: Request):
    """Подтверждённые входы на переданные адреса. 0-conf сюда не попадает."""
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=False)
    try:
        data = ReceiveIncomingBody.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(status_code=400, detail="invalid_body") from None
    coin = _coin_or_400(data.coin)
    addresses: list[str] = []
    for raw_addr in data.addresses:
        addr = raw_addr.strip()
        decision = validate_address(coin, addr)
        if not decision.ok:
            raise HTTPException(status_code=400, detail=decision.reason)
        addresses.append(addr)
    try:
        items = await list_confirmed_incoming(coin, addresses, minconf=1)
    except RpcError as exc:
        logger.warning("casino incoming scan failed for %s", coin, exc_info=True)
        raise HTTPException(status_code=503, detail=str(exc)[:120]) from None
    return {"ok": True, "coin": coin, "items": items}


@app.get("/v1/payouts/{request_id}")
async def payout_status(request_id: str, request: Request):
    _verify_hmac(request, await request.body(), anti_replay=False)
    row = store.get(request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@app.post("/v1/payouts")
async def create_payout(request: Request):
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = PayoutBody.model_validate_json(raw)
    except ValidationError as exc:
        # Невалидное тело — однозначный отказ (400), отправки не было.
        _audit({"event": "bad_body", "error": str(exc)[:300]})
        raise HTTPException(status_code=400, detail="invalid_body") from None
    rid = data.request_id.strip()
    coin = data.coin.lower().strip()
    address = data.address.strip()
    amount = float(data.amount)

    claimed, existing = store.reserve(rid, coin, address, amount)
    if not claimed:
        prev = existing or {}
        _audit({"event": "duplicate", "request_id": rid, "prev": prev})
        if prev.get("status") == store.STATUS_REJECTED:
            return {
                "status": "rejected",
                "reason": prev.get("reason") or "previously_rejected",
                "request_id": rid,
            }
        return {
            "status": "duplicate",
            "txid": prev.get("txid"),
            "request_id": rid,
            "prev_status": prev.get("status"),
        }

    for check in (
        validate_address(coin, address),
        validate_not_blocked(address),
        validate_amount(coin, amount, max_tx=data.max_tx),
        validate_daily_cap(
            coin,
            amount,
            store.daily_total(coin) - amount,
            daily_cap=data.daily_cap,
        ),
    ):
        if not check.ok:
            store.finish(rid, store.STATUS_REJECTED, reason=check.reason)
            _audit({"event": "rejected", "request_id": rid, "reason": check.reason})
            return {"status": "rejected", "reason": check.reason, "request_id": rid}

    if not settings.dry_run:
        # Пока нода догоняет сеть, кошелёк не видит свежие входы и может
        # собрать транзакцию из устаревших данных — не отправляем.
        node = (await get_node_status()).get(coin) or {}
        if not node.get("ok") or node.get("syncing"):
            store.finish(rid, store.STATUS_REJECTED, reason="node_not_ready")
            _audit({"event": "rejected", "request_id": rid, "reason": "node_not_ready"})
            return {"status": "rejected", "reason": "node_not_ready", "request_id": rid}

    try:
        txid = await send_payout(coin, address, amount)
    except Exception as exc:
        definite = presend_reject_reason(exc)
        if definite:
            # Нода отказала до broadcast: монеты не уходили, заявку можно отдать оператору.
            store.finish(rid, store.STATUS_REJECTED, reason=definite)
            _audit({"event": "rejected", "request_id": rid, "reason": definite})
            logger.warning("send rejected before broadcast request_id=%s reason=%s", rid, definite)
            return {"status": "rejected", "reason": definite, "request_id": rid}
        # Отправка могла состояться (broadcast прошёл, ответ потерян).
        # Это НЕ отказ: помечаем unknown, резерв не снимаем, разбирается человек.
        store.finish(rid, store.STATUS_UNKNOWN, reason=str(exc)[:200])
        _audit({"event": "unknown", "request_id": rid, "error": str(exc)[:200]})
        logger.exception("send failed request_id=%s", rid)
        return {"status": "unknown", "reason": "send_failed", "request_id": rid}

    store.finish(rid, store.STATUS_SENT, txid=txid)
    fee_info = None
    try:
        fee_info = await tx_fee(coin, txid)
    except Exception:
        logger.warning("fee lookup failed request_id=%s", rid, exc_info=True)
    if fee_info:
        store.set_fee(rid, fee_info["fee"], fee_info.get("vsize"))
        await audit_fee(coin, txid, amount, fee_info["fee"])
    row = {
        "status": "accepted",
        "txid": txid,
        "request_id": rid,
        "coin": coin,
        "amount": amount,
        "fee": (fee_info or {}).get("fee"),
        "vsize": (fee_info or {}).get("vsize"),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _audit({"event": "accepted", **row})
    return row


class TxBody(BaseModel):
    coin: str = "btc"
    txid: str = Field(min_length=64, max_length=64)


class BumpBody(TxBody):
    fee_rate_btc_kvb: float = Field(gt=0, le=0.05)


def _txid_or_400(txid: str) -> str:
    raw = (txid or "").strip()
    if not _TXID.fullmatch(raw):
        raise HTTPException(status_code=400, detail="invalid_txid")
    return raw


@app.post("/v1/tx/status")
async def tx_status(request: Request):
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=False)
    try:
        data = TxBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    if data.coin.lower() != "btc":
        return {"found": False, "reason": "not_btc"}
    txid = _txid_or_400(data.txid)
    try:
        return await wallet_tx("btc", txid)
    except Exception as exc:
        logger.exception("tx status failed")
        return {"found": False, "reason": "rpc_error", "detail": str(exc)[:120]}


class BumpQuotesBody(TxBody):
    targets_sat_vb: list[float] = Field(default_factory=list, max_length=3)


@app.post("/v1/tx/bump-quotes")
async def tx_bump_quotes(request: Request):
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=False)
    try:
        data = BumpQuotesBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    if data.coin.lower() != "btc":
        return {"ok": False, "reason": "not_btc", "definite": True, "quotes": []}
    txid = _txid_or_400(data.txid)
    try:
        return await quote_fee_bumps(txid, data.targets_sat_vb)
    except Exception as exc:
        logger.exception("bump quotes failed")
        return {"ok": False, "reason": "rpc_error", "definite": True, "detail": str(exc)[:120], "quotes": []}


@app.post("/v1/tx/bump-quote")
async def tx_bump_quote(request: Request):
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=False)
    try:
        data = TxBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    if data.coin.lower() != "btc":
        return {"ok": False, "reason": "not_btc", "definite": True}
    txid = _txid_or_400(data.txid)
    try:
        return await quote_fee_bump("btc", txid)
    except Exception as exc:
        logger.exception("bump quote failed")
        return {"ok": False, "reason": "rpc_error", "definite": True, "detail": str(exc)[:120]}


class TrustTopupBody(TxBody):
    note: str = Field("", max_length=200)


async def _topup_rows(coin: str) -> list[dict[str, Any]]:
    rows = []
    for row in store.trusted_topups(coin):
        try:
            live = await topup_status(coin, row["txid"])
        except Exception as exc:
            live = {"status": "rpc_error", "detail": str(exc)[:120]}
        rows.append({**row, **live, "amount": row["amount"]})
    return rows


@app.get("/v1/topups")
async def list_topups(request: Request, coin: str = "btc"):
    _verify_hmac(request, await request.body(), anti_replay=False)
    c = coin.lower()
    return {
        "coin": c,
        "enabled": fast_spend_enabled(c),
        "max_pending": settings.trusted_topup_max_btc,
        "items": await _topup_rows(c),
    }


@app.post("/v1/topups/trust")
async def trust_topup(request: Request):
    """Админ подтвердил: это его пополнение, его можно тратить до подтверждения."""
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = TrustTopupBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    coin = data.coin.lower()
    txid = _txid_or_400(data.txid).lower()

    def _reject(reason: str, **extra: Any) -> dict[str, Any]:
        _audit({"event": "topup_rejected", "txid": txid, "reason": reason, **extra})
        return {"ok": False, "reason": reason, "txid": txid, **extra}

    if not fast_spend_enabled(coin):
        return _reject("disabled")
    try:
        live = await topup_status(coin, txid)
    except Exception as exc:
        logger.exception("topup status failed")
        return _reject("rpc_error", detail=str(exc)[:120])
    if not live.get("found"):
        return _reject("not_in_wallet")
    if live["status"] != "pending":
        return _reject(
            "already_confirmed" if live["status"] == "confirmed" else live["status"]
        )
    if not unconfirmed_is_spendable(live):
        return _reject("replaceable")
    amount = float(live.get("amount") or 0)
    if amount <= 0:
        return _reject("not_incoming")
    waiting = sum(
        float(r["amount"] or 0)
        for r in await _topup_rows(coin)
        if r.get("status") == "pending" and r["txid"] != txid
    )
    cap = float(settings.trusted_topup_max_btc)
    if waiting + amount > cap + 1e-12:
        return _reject("cap_exceeded", waiting=round(waiting, 8), cap=cap)
    added = store.add_trusted_topup(coin, txid, amount, data.note.strip())
    _audit({"event": "topup_trusted", "txid": txid, "amount": amount, "new": added})
    return {"ok": True, "txid": txid, "amount": amount, "already": not added, **live}


@app.post("/v1/tx/bump")
async def tx_bump(request: Request):
    raw = await request.body()
    _verify_hmac(request, raw, anti_replay=True)
    try:
        data = BumpBody.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_body") from exc
    if data.coin.lower() != "btc":
        return {"ok": False, "reason": "not_btc", "definite": True}
    txid = _txid_or_400(data.txid)
    result = await broadcast_fee_bump("btc", txid, data.fee_rate_btc_kvb)
    _audit({"event": "fee_bump", "txid": data.txid, **result})
    return result

"""bitcoind / litecoind JSON-RPC (или dry-run заглушка)."""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import logging
import math
import uuid
from typing import Any

import aiohttp

from config import settings

logger = logging.getLogger("wallet_rpc")

_SUPPORTED = ("btc", "ltc")
HOUSE_DEPOSIT_LABEL = "focuspay-deposit"
CASINO_DEPOSIT_LABEL = "casino-deposit"
_SATOSHI = Decimal("0.00000001")


class RpcError(RuntimeError):
    pass


def _node(coin: str) -> dict[str, Any]:
    c = coin.lower()
    if c == "btc":
        return {
            "url": settings.btc_rpc_url,
            "user": settings.btc_rpc_user,
            "password": settings.btc_rpc_password,
            "wallet": settings.btc_rpc_wallet,
        }
    if c == "ltc":
        return {
            "url": settings.ltc_rpc_url,
            "user": settings.ltc_rpc_user,
            "password": settings.ltc_rpc_password,
            "wallet": settings.ltc_rpc_wallet,
        }
    raise RpcError(f"unsupported_coin:{coin}")


async def _rpc(
    coin: str,
    method: str,
    params: list | None = None,
    *,
    timeout: float = 120,
) -> Any:
    node = _node(coin)
    if not node["user"] or not node["password"]:
        raise RpcError(f"rpc_credentials_missing:{coin}")
    url = node["url"].rstrip("/")
    if node["wallet"]:
        url = f"{url}/wallet/{node['wallet']}"
    payload = {"jsonrpc": "1.0", "id": method, "method": method, "params": params or []}
    auth = aiohttp.BasicAuth(node["user"], node["password"])
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg, auth=auth) as session:
        async with session.post(url, json=payload) as resp:
            text = await resp.text()
    try:
        import json

        data = json.loads(text)
    except ValueError as exc:
        raise RpcError(f"bad_rpc_response:{resp.status}:{text[:200]}") from exc
    if data.get("error"):
        raise RpcError(str(data["error"])[:200])
    return data.get("result")


async def send_to_address(coin: str, address: str, amount: float) -> str:
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    if settings.dry_run:
        fake = hashlib.sha256(
            f"{c}:{address}:{amount}:{uuid.uuid4()}".encode()
        ).hexdigest()
        logger.info("DRY RUN payout %s %s -> %s", c, amount, address)
        return fake

    # subtractfeefromamount=false: получатель получает ровно сумму выплаты,
    # сетевую комиссию платит компания (она уже удержана с баланса в рублях).
    params: list[Any] = [address, round(float(amount), 8), "focuspay auto payout", "", False, True]
    if c == "btc":
        # Явная ставка: та же, что оператор видит в окне отправки.
        params += [None, "unset", None, await payout_fee_rate_sat_vb(c)]
    else:
        params += [int(settings.conf_target), settings.estimate_mode]
    txid = await _rpc(c, "sendtoaddress", params)
    if not txid or not isinstance(txid, str):
        raise RpcError("sendtoaddress_returned_no_txid")
    return txid


def fast_spend_enabled(coin: str) -> bool:
    return coin.lower() == "btc" and bool(settings.trusted_topups_enabled)


def pick_fast_utxos(unspent: list[dict[str, Any]], allowed_txids: set[str]) -> list[dict[str, Any]]:
    """Неподтверждённые выходы, которые кошелёк считает unsafe, но мы им доверяем.

    Подтверждённые и собственные trusted-выходы кошелёк выберет сам, их тут нет.
    """
    out = []
    for u in unspent or []:
        if not isinstance(u, dict):
            continue
        if u.get("safe") or not u.get("spendable"):
            continue
        if is_casino_deposit_utxo(u):
            continue
        if int(u.get("confirmations") or 0) != 0:
            continue
        if str(u.get("txid") or "").lower() not in allowed_txids:
            continue
        out.append(u)
    return out


def is_casino_deposit_utxo(utxo: dict[str, Any]) -> bool:
    """Адрес казино нельзя тратить до блока: это чужие деньги, их могут заменить."""
    return str(utxo.get("label") or "") == CASINO_DEPOSIT_LABEL


def group_incoming_unconfirmed(unspent: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Сумма неподтверждённых чужих выходов по txid. Подтверждённые и свои — не сюда."""
    totals: dict[str, float] = {}
    for u in unspent or []:
        if not isinstance(u, dict) or u.get("safe") or not u.get("spendable"):
            continue
        if is_casino_deposit_utxo(u):
            continue
        if int(u.get("confirmations") or 0) != 0:
            continue
        txid = str(u.get("txid") or "").lower()
        amount = float(u.get("amount") or 0)
        if not txid or amount <= 0:
            continue
        totals[txid] = totals.get(txid, 0.0) + amount
    return sorted(totals.items())


def fit_topups(
    groups: list[tuple[str, float]],
    *,
    waiting: float,
    cap: float,
    already: set[str],
) -> list[tuple[str, float]]:
    """Сколько новых пополнений влезает в лимит неподтверждённого BTC."""
    left = cap - waiting
    out: list[tuple[str, float]] = []
    for txid, amount in groups:
        if txid in already or amount > left + 1e-12:
            continue
        out.append((txid, round(amount, 8)))
        left -= amount
    return out


def unconfirmed_is_spendable(live: dict[str, Any] | None) -> bool:
    """0-conf тратим только если нода явно сказала, что RBF уже нельзя.

    yes и unknown ждут блок: замену такого пополнения утащит и выплату из него.
    """
    if not isinstance(live, dict) or live.get("status") != "pending":
        return False
    return str(live.get("bip125") or "") == "no"


_logged_unspendable: set[str] = set()


async def _spendable_unconfirmed(coin: str, txid: str) -> bool:
    try:
        live = await topup_status(coin, txid)
    except Exception:
        logger.warning("unconfirmed spend check failed %s", txid, exc_info=True)
        return False
    if unconfirmed_is_spendable(live):
        return True
    if txid not in _logged_unspendable:
        _logged_unspendable.add(txid)
        logger.info(
            "unconfirmed btc waits for a block %s bip125=%s status=%s",
            txid,
            live.get("bip125"),
            live.get("status"),
        )
    return False


async def adopt_incoming_topups(coin: str) -> list[str]:
    """Входящий неподтверждённый BTC на горячий кошелёк можно тратить сразу, без пометки в панели.

    Заменяемый перевод (RBF или неизвестный флаг) не записываем: он ждёт блок.
    Лимит `trusted_topup_max_btc` остаётся. Для LTC этого режима нет.
    """
    if not fast_spend_enabled(coin) or not _has_rpc():
        return []
    import store

    unspent = await _rpc(coin, "listunspent", [0, 0])
    if not isinstance(unspent, list):
        return []
    pending_ids = {
        str(u.get("txid") or "").lower()
        for u in unspent
        if isinstance(u, dict) and int(u.get("confirmations") or 0) == 0
    }
    known = store.trusted_topups(coin, limit=200)
    waiting = sum(
        float(r.get("amount") or 0) for r in known if str(r.get("txid") or "").lower() in pending_ids
    )
    already = {str(r.get("txid") or "").lower() for r in known}
    chosen = fit_topups(
        group_incoming_unconfirmed(unspent),
        waiting=waiting,
        cap=float(settings.trusted_topup_max_btc),
        already=already,
    )
    added: list[str] = []
    for txid, amount in chosen:
        if not await _spendable_unconfirmed(coin, txid):
            continue
        if store.add_trusted_topup(coin, txid, amount, "само"):
            added.append(txid)
            logger.info("auto-trusted unconfirmed btc %s %.8f", txid, amount)
    return added


async def fast_utxos(coin: str) -> list[dict[str, Any]]:
    if not fast_spend_enabled(coin) or not _has_rpc():
        return []
    import store

    try:
        await adopt_incoming_topups(coin)
    except Exception:
        logger.warning("adopt incoming topups failed for %s", coin, exc_info=True)
    allowed = store.fast_spend_txids(coin)
    if not allowed:
        return []
    unspent = await _rpc(coin, "listunspent", [0, 0])
    picked = pick_fast_utxos(unspent if isinstance(unspent, list) else [], allowed)
    allowed_now: dict[str, bool] = {}
    out = []
    for utxo in picked:
        txid = str(utxo.get("txid") or "").lower()
        if txid not in allowed_now:
            allowed_now[txid] = await _spendable_unconfirmed(coin, txid)
        if allowed_now[txid]:
            out.append(utxo)
    return out


async def send_with_fast_inputs(coin: str, address: str, amount: float) -> str:
    """Выплата, где часть входов — доверенные неподтверждённые выходы.

    include_unsafe не включаем: чужие неподтверждённые монеты кошелёк не возьмёт,
    добрать недостающее он может только безопасными выходами (add_inputs).
    """
    utxos = await fast_utxos(coin)
    if not utxos:
        raise RpcError("Insufficient funds")
    res = await _rpc(
        coin,
        "send",
        [
            [{address: round(float(amount), 8)}],
            None,
            "unset",
            await payout_fee_rate_sat_vb(coin),
            {
                "inputs": [{"txid": u["txid"], "vout": int(u["vout"])} for u in utxos],
                "add_inputs": True,
                # Саму выплату из 0-conf тоже нельзя заменить: RBF утащил бы её из сети.
                "replaceable": False,
            },
        ],
    )
    if not isinstance(res, dict) or not res.get("complete") or not res.get("txid"):
        raise RpcError("send_incomplete")
    return str(res["txid"])


async def send_payout(coin: str, address: str, amount: float) -> str:
    """Обычная отправка; если подтверждённых монет мало — с доверенными входами."""
    try:
        return await send_to_address(coin, address, amount)
    except Exception as exc:
        if settings.dry_run or presend_reject_reason(exc) != "insufficient_funds":
            raise
        if not fast_spend_enabled(coin):
            raise
    return await send_with_fast_inputs(coin, address, amount)


async def topup_status(coin: str, txid: str) -> dict[str, Any]:
    """pending | confirmed | conflicted | dropped | not_in_wallet."""
    try:
        tx = await _rpc(coin, "gettransaction", [txid], timeout=20)
    except RpcError as exc:
        if classify_bump_error(str(exc)) == "not_in_wallet":
            return {"found": False, "status": "not_in_wallet"}
        raise
    if not isinstance(tx, dict):
        return {"found": False, "status": "not_in_wallet"}
    confirmations = int(tx.get("confirmations") or 0)
    amount = float(tx.get("amount") or 0)
    if confirmations > 0:
        status = "confirmed"
    elif confirmations < 0:
        status = "conflicted"
    else:
        try:
            await _rpc(coin, "getmempoolentry", [txid], timeout=20)
            status = "pending"
        except RpcError:
            status = "dropped"
    return {
        "found": True,
        "status": status,
        "confirmations": confirmations,
        "amount": amount,
        "replaceable": str(tx.get("bip125-replaceable") or "").lower() == "yes",
        "bip125": str(tx.get("bip125-replaceable") or "").lower(),
    }


# P2WPKH: 1 вход + 2 выхода (получатель и сдача).
TYPICAL_VSIZE = 141
_FALLBACK_FEERATE_KVB = {"btc": 0.00002, "ltc": 0.00001}

# Последняя оценка, которую нода реально посчитала. Нужна, чтобы при её недоступности
# не падать на нижнюю ставку в разгар шторма и не отправлять заведомо медленную tx.
_LAST_ESTIMATED_KVB: dict[str, float] = {}


def _estimate_params(coin: str) -> tuple[int, str]:
    if coin == "btc":
        return int(settings.btc_conf_target), settings.btc_estimate_mode
    return int(settings.conf_target), settings.estimate_mode


async def estimate_fee(coin: str) -> dict[str, Any]:
    """Оценка комиссии типовой отправки в монете (платим мы, клиент получает полную сумму)."""
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    conf_target, mode = _estimate_params(c)
    if not _has_rpc():
        feerate_kvb = 0.0001 if c == "btc" else 0.00001
        estimated = False
    else:
        res = await _rpc(c, "estimatesmartfee", [conf_target, mode])
        feerate_kvb = float((res or {}).get("feerate") or 0)
        estimated = feerate_kvb > 0
        if estimated:
            _LAST_ESTIMATED_KVB[c] = feerate_kvb
        else:
            # Нода ещё не набрала статистику (например, при синхронизации) —
            # ставка релея занижает реальную комиссию, поэтому не ниже типовой.
            info = await _rpc(c, "getnetworkinfo")
            relay = float((info or {}).get("relayfee") or 0.00001)
            feerate_kvb = max(
                relay,
                _FALLBACK_FEERATE_KVB[c],
                _LAST_ESTIMATED_KVB.get(c, 0.0),
            )
    if c == "btc":
        feerate_kvb = max(feerate_kvb, sat_vb_to_btc_kvb(float(settings.btc_min_fee_rate_sat_vb)))
        feerate_kvb = min(feerate_kvb, sat_vb_to_btc_kvb(float(settings.btc_max_fee_rate_sat_vb)))
    fee = feerate_kvb * TYPICAL_VSIZE / 1000
    return {
        "coin": c,
        "feerate_sat_vb": round(feerate_kvb * 1e8 / 1000, 2),
        "vsize": TYPICAL_VSIZE,
        "fee": round(fee, 8),
        "conf_target": conf_target,
        "mode": mode,
        "estimated": estimated,
    }


async def payout_fee_rate_sat_vb(coin: str) -> float:
    """Ставка выплаты: оценка ноды, но не ниже порога из signer.env."""
    return float((await estimate_fee(coin))["feerate_sat_vb"])


async def tx_fee(coin: str, txid: str) -> dict[str, Any] | None:
    """Фактическая комиссия отправленной транзакции из кошелька."""
    if settings.dry_run or not _has_rpc():
        return None
    tx = await _rpc(coin, "gettransaction", [txid])
    fee = abs(float((tx or {}).get("fee") or 0))
    decoded = None
    try:
        decoded = await _rpc(coin, "decoderawtransaction", [tx.get("hex")])
    except Exception:
        logger.debug("decode tx failed %s", txid, exc_info=True)
    vsize = int((decoded or {}).get("vsize") or 0)
    return {"fee": fee, "vsize": vsize or None}


async def audit_fee(coin: str, txid: str, amount: float, fee: float) -> None:
    """Пост-фактум проверка комиссии: отменить нельзя, но важно знать."""
    if amount <= 0 or fee <= 0:
        return
    pct = fee / amount * 100
    if pct > float(settings.fee_pct_cap):
        logger.error(
            "fee cap exceeded %s tx=%s fee=%.8f (%.2f%% > %.2f%%)",
            coin,
            txid,
            fee,
            pct,
            settings.fee_pct_cap,
        )


async def get_node_status() -> dict[str, dict[str, Any]]:
    """Синхронизация нод: пока нода догоняет сеть, отправлять нельзя."""
    if not _has_rpc():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for coin in _SUPPORTED:
        try:
            info = await _rpc(coin, "getblockchaininfo")
        except Exception as exc:
            out[coin] = {"ok": False, "error": str(exc)[:120]}
            continue
        blocks = int(info.get("blocks") or 0)
        headers = int(info.get("headers") or 0)
        out[coin] = {
            "ok": True,
            "blocks": blocks,
            "headers": headers,
            "progress": round(float(info.get("verificationprogress") or 0), 6),
            "syncing": bool(info.get("initialblockdownload")) or blocks < headers,
        }
    return out


async def new_labeled_address(coin: str, label: str) -> str:
    """Новый bech32-адрес в горячем кошельке. Слот «текущий адрес дома» не трогает."""
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    if label not in (HOUSE_DEPOSIT_LABEL, CASINO_DEPOSIT_LABEL):
        raise RpcError("unsupported_label")
    addr = await _rpc(c, "getnewaddress", [label, "bech32"])
    if not addr or not isinstance(addr, str):
        raise RpcError("getnewaddress_returned_nothing")
    return addr


async def new_deposit_address(coin: str) -> str:
    return await new_labeled_address(coin, HOUSE_DEPOSIT_LABEL)


def _coin_sats(amount: object) -> int:
    try:
        value = Decimal(str(amount))
    except Exception:
        return 0
    if value <= 0:
        return 0
    return int((value / _SATOSHI).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def group_confirmed_incoming(
    unspent: list[dict[str, Any]] | None,
    addresses: list[str],
    *,
    minconf: int = 1,
) -> list[dict[str, Any]]:
    """Сумма подтверждённых выходов по паре (txid, адрес) из запрошенного списка."""
    wanted = {str(addr) for addr in addresses if addr}
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for utxo in unspent or []:
        if not isinstance(utxo, dict):
            continue
        address = str(utxo.get("address") or "")
        if address not in wanted:
            continue
        confirmations = int(utxo.get("confirmations") or 0)
        if confirmations < minconf:
            continue
        txid = str(utxo.get("txid") or "").lower()
        sats = _coin_sats(utxo.get("amount"))
        if not txid or sats <= 0:
            continue
        key = (txid, address)
        row = totals.get(key)
        if row is None:
            totals[key] = {"txid": txid, "address": address, "sats": sats, "confirmations": confirmations}
        else:
            row["sats"] += sats
            row["confirmations"] = min(int(row["confirmations"]), confirmations)
    items = [
        {
            "txid": row["txid"],
            "address": row["address"],
            "amount": format((Decimal(row["sats"]) * _SATOSHI).quantize(_SATOSHI), "f"),
            "confirmations": int(row["confirmations"]),
        }
        for row in totals.values()
    ]
    items.sort(key=lambda row: (row["address"], row["txid"]))
    return items


async def list_confirmed_incoming(
    coin: str,
    addresses: list[str],
    *,
    minconf: int = 1,
) -> list[dict[str, Any]]:
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    if not addresses:
        return []
    unspent = await _rpc(c, "listunspent", [minconf, 9999999, addresses], timeout=30)
    if not isinstance(unspent, list):
        raise RpcError("listunspent_returned_nothing")
    return group_confirmed_incoming(unspent, addresses, minconf=minconf)


async def address_received(coin: str, address: str) -> float:
    """Сколько монет уже приходило на адрес, включая неподтверждённые.

    Ноль, если ноды нет: без неё адрес не считаем использованным.
    """
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    if not _has_rpc():
        return 0.0
    val = await _rpc(c, "getreceivedbyaddress", [address, 0], timeout=15)
    return float(val or 0)


def _has_rpc() -> bool:
    return bool(settings.btc_rpc_user or settings.ltc_rpc_user)


async def get_balances() -> dict[str, dict[str, float]]:
    if settings.dry_run and not _has_rpc():
        return {
            "btc": {"confirmed": 0.01, "unconfirmed": 0.0, "spendable": 0.01},
            "ltc": {"confirmed": 1.0, "unconfirmed": 0.0, "spendable": 1.0},
        }
    out: dict[str, dict[str, float]] = {}
    for coin in _SUPPORTED:
        try:
            res = await _rpc(coin, "getbalances")
        except Exception:
            logger.warning("getbalances failed for %s", coin, exc_info=True)
            continue
        mine = (res or {}).get("mine") or {}
        trusted = float(mine.get("trusted") or 0)
        fast = 0.0
        if fast_spend_enabled(coin):
            try:
                fast = sum(float(u.get("amount") or 0) for u in await fast_utxos(coin))
            except Exception:
                logger.warning("fast utxos unavailable for %s", coin, exc_info=True)
        out[coin] = {
            "confirmed": trusted,
            "unconfirmed": float(mine.get("untrusted_pending") or 0),
            "spendable": trusted,
            "spendable_fast": round(trusted + fast, 8),
            "fast_enabled": fast_spend_enabled(coin),
        }
    return out


# Ускорение только Bitcoin и только до следующего блока.
BUMP_CONF_TARGET = 1
MAX_BUMP_DELTA_BTC = 0.002
MAX_FEE_RATE_BTC_KVB = 0.05


def presend_reject_reason(exc: BaseException) -> str | None:
    """Отказ ноды до broadcast. Такие ошибки можно повторять другим request_id.

    Таймаут и обрыв сюда не входят: транзакция могла уже уйти.
    """
    text = str(exc or "").lower()
    if "too-long-mempool-chain" in text or "chain of transactions" in text:
        return "mempool_chain_limit"
    if "send_incomplete" in text:
        return "send_incomplete"
    if "insufficient funds" in text:
        return "insufficient_funds"
    if "amount too small" in text or "transaction amount too small" in text:
        return "amount_too_small"
    return None


def classify_bump_error(message: str) -> str:
    text = (message or "").lower()
    if "non-wallet" in text or "not in the wallet" in text or "not in wallet" in text:
        return "not_in_wallet"
    if "bip 125" in text or "not replaceable" in text or "not opt-in" in text:
        return "not_replaceable"
    if "has been confirmed" in text or "already confirmed" in text or "not in mempool" in text:
        return "already_confirmed"
    if "already" in text and "fee" in text:
        return "already_fast"
    if "too low" in text or "insufficient fee" in text or "min relay" in text or "fee rate" in text:
        return "fee_rejected"
    return "rpc_error"


def fee_rate_btc_kvb(fee_btc: float, vsize: int) -> float:
    """BTC/kvB, округление вверх, чтобы bumpfee не отклонил ставку из-за округления."""
    size = int(vsize) if int(vsize) > 0 else TYPICAL_VSIZE
    raw = float(fee_btc) * 1000.0 / size
    return math.ceil(raw * 1e8) / 1e8


def _feerate_sat_vb(fee_btc: float, vsize: int) -> float | None:
    if fee_btc <= 0 or vsize <= 0:
        return None
    return round(fee_btc * 1e8 / vsize, 2)


async def wallet_tx(coin: str, txid: str, *, timeout: float = 20) -> dict[str, Any]:
    """Транзакция горячего кошелька. found=false, если её там нет."""
    c = coin.lower()
    if c not in _SUPPORTED:
        raise RpcError(f"unsupported_coin:{coin}")
    if settings.dry_run and not _has_rpc():
        return {"found": False, "reason": "node_unavailable"}
    try:
        tx = await _rpc(c, "gettransaction", [txid, False, True], timeout=timeout)
    except RpcError as exc:
        if classify_bump_error(str(exc)) == "not_in_wallet":
            return {"found": False, "reason": "not_in_wallet"}
        try:
            tx = await _rpc(c, "gettransaction", [txid], timeout=timeout)
        except RpcError as retry_exc:
            if classify_bump_error(str(retry_exc)) == "not_in_wallet":
                return {"found": False, "reason": "not_in_wallet"}
            raise
    if not isinstance(tx, dict):
        return {"found": False, "reason": "not_in_wallet"}
    fee = abs(float(tx.get("fee") or 0))
    decoded = tx.get("decoded") if isinstance(tx.get("decoded"), dict) else {}
    vsize = int((decoded or {}).get("vsize") or 0)
    if vsize <= 0 and tx.get("hex"):
        try:
            raw = await _rpc(c, "decoderawtransaction", [tx.get("hex")], timeout=timeout)
            vsize = int((raw or {}).get("vsize") or 0)
        except RpcError:
            logger.debug("decode tx failed %s", txid, exc_info=True)
    confirmations = int(tx.get("confirmations") or 0)
    replaceable = str(tx.get("bip125-replaceable") or "").lower() == "yes"
    return {
        "found": True,
        "confirmations": confirmations,
        "fee": fee,
        "vsize": vsize or None,
        "feerate_sat_vb": _feerate_sat_vb(fee, vsize),
        "replaceable": replaceable,
    }


async def _next_block_feerate_sat_vb(coin: str, *, timeout: float = 20) -> float | None:
    res = await _rpc(coin, "estimatesmartfee", [BUMP_CONF_TARGET, "conservative"], timeout=timeout)
    feerate_kvb = float((res or {}).get("feerate") or 0)
    if feerate_kvb <= 0:
        return None
    return round(feerate_kvb * 1e8 / 1000, 2)


def sat_vb_to_btc_kvb(sat_vb: float) -> float:
    """1 sat/vB = 0.00001 BTC/kvB. Округление вверх до 1e-8, как у bumpfee."""
    raw = Decimal(str(sat_vb)) * Decimal("0.00001")
    if raw <= 0:
        return 0.0
    return float(raw.quantize(Decimal("0.00000001"), rounding=ROUND_CEILING))


async def _quote_psbt_at_rate(txid: str, status: dict[str, Any], fee_rate_sat_vb: float) -> dict[str, Any]:
    """psbtbumpfee с явной ставкой. В цену идёт фактическая доплата ноды."""
    current = status.get("feerate_sat_vb")
    rate_kvb = sat_vb_to_btc_kvb(fee_rate_sat_vb)
    if rate_kvb <= 0 or rate_kvb > MAX_FEE_RATE_BTC_KVB:
        return {"ok": False, "reason": "fee_too_high", "definite": True, "target_feerate_sat_vb": fee_rate_sat_vb}
    try:
        bumped = await _rpc(
            "btc",
            "psbtbumpfee",
            [txid, {"fee_rate": rate_kvb}],
            timeout=20,
        )
    except RpcError as exc:
        return {
            "ok": False,
            "reason": classify_bump_error(str(exc)),
            "definite": True,
            "target_feerate_sat_vb": fee_rate_sat_vb,
        }
    if not isinstance(bumped, dict):
        return {"ok": False, "reason": "rpc_error", "definite": True, "target_feerate_sat_vb": fee_rate_sat_vb}
    errors = bumped.get("errors") or []
    if errors and not bumped.get("psbt"):
        text = errors if isinstance(errors, str) else " ".join(str(item) for item in errors)
        return {
            "ok": False,
            "reason": classify_bump_error(text),
            "definite": True,
            "target_feerate_sat_vb": fee_rate_sat_vb,
        }
    orig = abs(float(bumped.get("origfee") or status.get("fee") or 0))
    fee = abs(float(bumped.get("fee") or 0))
    delta = round(fee - orig, 8)
    if delta <= 0:
        return {
            "ok": False,
            "reason": "already_fast",
            "definite": True,
            "feerate_sat_vb": current,
            "target_feerate_sat_vb": fee_rate_sat_vb,
        }
    if delta > MAX_BUMP_DELTA_BTC:
        return {"ok": False, "reason": "fee_too_high", "definite": True, "target_feerate_sat_vb": fee_rate_sat_vb}
    vsize = int(status.get("vsize") or 0)
    rate = fee_rate_btc_kvb(fee, vsize)
    if rate <= 0 or rate > MAX_FEE_RATE_BTC_KVB:
        return {"ok": False, "reason": "fee_too_high", "definite": True, "target_feerate_sat_vb": fee_rate_sat_vb}
    return {
        "ok": True,
        "orig_fee": orig,
        "fee": fee,
        "delta_fee": delta,
        "fee_rate_btc_kvb": rate,
        "confirmations": 0,
        "feerate_sat_vb": current,
        "target_feerate_sat_vb": float(fee_rate_sat_vb),
        "vsize": vsize or None,
        "definite": True,
    }


async def quote_fee_bumps(txid: str, targets_sat_vb: list[float]) -> dict[str, Any]:
    """Несколько котировок одной транзакции. Сеть не трогаем."""
    if settings.dry_run and not _has_rpc():
        return {"ok": False, "reason": "node_unavailable", "definite": True, "quotes": []}
    status = await wallet_tx("btc", txid)
    if not status.get("found"):
        return {
            "ok": False,
            "reason": status.get("reason") or "not_in_wallet",
            "definite": True,
            "quotes": [],
        }
    confirmations = int(status.get("confirmations") or 0)
    if confirmations > 0:
        return {"ok": False, "reason": "already_confirmed", "definite": True, "quotes": []}
    if confirmations < 0:
        return {"ok": False, "reason": "conflicted", "definite": True, "quotes": []}
    quotes = []
    for target in targets_sat_vb[:3]:
        try:
            target_f = float(target)
        except (TypeError, ValueError):
            continue
        if target_f <= 0:
            continue
        quotes.append(await _quote_psbt_at_rate(txid, status, target_f))
    return {
        "ok": any(item.get("ok") for item in quotes),
        "quotes": quotes,
        "feerate_sat_vb": status.get("feerate_sat_vb"),
        "vsize": status.get("vsize"),
        "definite": True,
    }


async def quote_fee_bump(coin: str, txid: str) -> dict[str, Any]:
    """Котировка ускорения без отправки в сеть (psbtbumpfee)."""
    c = coin.lower()
    if c != "btc":
        return {"ok": False, "reason": "not_btc", "definite": True}
    if settings.dry_run and not _has_rpc():
        return {"ok": False, "reason": "node_unavailable", "definite": True}
    status = await wallet_tx(c, txid)
    if not status.get("found"):
        return {"ok": False, "reason": status.get("reason") or "not_in_wallet", "definite": True}
    confirmations = int(status.get("confirmations") or 0)
    if confirmations > 0:
        return {
            "ok": False,
            "reason": "already_confirmed",
            "confirmations": confirmations,
            "definite": True,
        }
    if confirmations < 0:
        return {"ok": False, "reason": "conflicted", "definite": True}
    current = status.get("feerate_sat_vb")
    target = None
    try:
        target = await _next_block_feerate_sat_vb(c)
    except RpcError:
        logger.debug("next-block fee estimate failed", exc_info=True)
    if target and current and float(current) + 1e-9 >= float(target):
        return {
            "ok": False,
            "reason": "already_fast",
            "confirmations": 0,
            "feerate_sat_vb": current,
            "target_feerate_sat_vb": target,
            "definite": True,
        }
    try:
        bumped = await _rpc(
            c,
            "psbtbumpfee",
            [txid, {"conf_target": BUMP_CONF_TARGET, "estimate_mode": "conservative"}],
            timeout=20,
        )
    except RpcError as exc:
        return {"ok": False, "reason": classify_bump_error(str(exc)), "definite": True}
    if not isinstance(bumped, dict):
        return {"ok": False, "reason": "rpc_error", "definite": True}
    errors = bumped.get("errors") or []
    if errors and not bumped.get("psbt"):
        text = errors if isinstance(errors, str) else " ".join(str(item) for item in errors)
        return {"ok": False, "reason": classify_bump_error(text), "definite": True}
    orig = abs(float(bumped.get("origfee") or status.get("fee") or 0))
    fee = abs(float(bumped.get("fee") or 0))
    delta = round(fee - orig, 8)
    if delta <= 0:
        return {
            "ok": False,
            "reason": "already_fast",
            "confirmations": 0,
            "feerate_sat_vb": current,
            "definite": True,
        }
    if delta > MAX_BUMP_DELTA_BTC:
        return {"ok": False, "reason": "fee_too_high", "definite": True}
    vsize = int(status.get("vsize") or 0)
    rate = fee_rate_btc_kvb(fee, vsize)
    if rate <= 0 or rate > MAX_FEE_RATE_BTC_KVB:
        return {"ok": False, "reason": "fee_too_high", "definite": True}
    return {
        "ok": True,
        "orig_fee": orig,
        "fee": fee,
        "delta_fee": delta,
        "fee_rate_btc_kvb": rate,
        "confirmations": 0,
        "feerate_sat_vb": current,
        "target_feerate_sat_vb": target,
        "vsize": vsize or None,
        "definite": True,
    }


async def broadcast_fee_bump(coin: str, txid: str, fee_rate_btc_kvb: float) -> dict[str, Any]:
    """Заменяет комиссию и публикует новую транзакцию. Получатель и сумма не меняются."""
    c = coin.lower()
    if c != "btc":
        return {"ok": False, "reason": "not_btc", "definite": True}
    if settings.dry_run:
        return {"ok": False, "reason": "dry_run", "definite": True}
    rate = float(fee_rate_btc_kvb)
    if rate <= 0 or rate > MAX_FEE_RATE_BTC_KVB:
        return {"ok": False, "reason": "fee_too_high", "definite": True}
    try:
        bumped = await _rpc(
            c,
            "bumpfee",
            [txid, {"fee_rate": rate, "replaceable": True}],
            timeout=60,
        )
    except RpcError as exc:
        return {"ok": False, "reason": classify_bump_error(str(exc)), "definite": True}
    except Exception as exc:
        logger.exception("bumpfee outcome unknown tx=%s", txid)
        return {"ok": False, "reason": "unknown", "definite": False, "detail": str(exc)[:200]}
    if not isinstance(bumped, dict) or not bumped.get("txid"):
        return {"ok": False, "reason": "rpc_error", "definite": False}
    orig = abs(float(bumped.get("origfee") or 0))
    fee = abs(float(bumped.get("fee") or 0))
    delta = round(fee - orig, 8)
    if delta > MAX_BUMP_DELTA_BTC:
        logger.error("bumpfee delta %.8f exceeds cap tx=%s", delta, txid)
    return {
        "ok": True,
        "txid": str(bumped.get("txid")),
        "orig_fee": orig,
        "fee": fee,
        "delta_fee": delta,
        "definite": True,
    }

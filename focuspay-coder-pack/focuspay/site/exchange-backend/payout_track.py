"""Подтверждения выплаты и платное ускорение Bitcoin в мини-приложении.

Цена покупателя = себестоимость сетевой комиссии в рублях × 1.2.
Чужой txid (кошелёк оператора) ускорить нельзя.
"""
from __future__ import annotations

import html
import logging
import math
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import aiohttp

from db import get_pool
from user_balance_transfer import TransferError, split_sources
from user_cashback_db import get_cashback_balance_conn
from user_unified_balance import (
    _partner_parts,
    _pending_user_withdrawal_rub,
    unified_available,
)

logger = logging.getLogger("payout_track")

MARKUP = Decimal("1.20")
DRIFT_RUB = Decimal("1.00")
_TXID = re.compile(r"^[0-9a-fA-F]{64}$")
_OPERATOR_BY = re.compile(r"^operator:(\d+)$")
_BLOCK_MINUTES = {"btc": 10.0, "ltc": 2.5}
_EXPLORER_ORIGIN = {
    "btc": "https://mempool.space",
    "ltc": "https://litecoinspace.org",
}
_TRON = "https://apilist.tronscanapi.com/api/transaction-info?hash={txid}"


class PushError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def buyer_price(cost_rub: Decimal | float | int | str) -> Decimal:
    """30 ₽ сети → 36 ₽ покупателю."""
    cost = money(cost_rub)
    if cost <= 0:
        return Decimal("0.00")
    return money(cost * MARKUP)


def cost_from_delta(delta_btc: Decimal | float | str, rate_rub: Decimal | float | str) -> Decimal:
    delta = Decimal(str(delta_btc))
    rate = Decimal(str(rate_rub))
    if delta <= 0 or rate <= 0:
        return Decimal("0.00")
    return money(delta * rate)


def resolve_charge(confirmed_rub: Decimal | float | str, fresh_rub: Decimal | float | str) -> Decimal:
    """Не списывать, если свежая цена выросла больше чем на 1 ₽."""
    confirmed = money(confirmed_rub)
    fresh = money(fresh_rub)
    if fresh > confirmed + DRIFT_RUB:
        raise PushError(
            "price_changed",
            "Цена изменилась",
            push_price_rub=float(fresh),
        )
    return fresh if fresh < confirmed else confirmed


def refund_delta(charged_rub: Decimal | float | str, actual_cost_rub: Decimal | float | str) -> Decimal:
    """Вернуть разницу, если фактическая цена с наценкой меньше уже списанной."""
    charged = money(charged_rub)
    actual_price = buyer_price(actual_cost_rub)
    if actual_price >= charged:
        return Decimal("0.00")
    return money(charged - actual_price)


def settlement(
    charged_rub: Decimal | float | str,
    actual_cost_rub: Decimal | float | str,
    *,
    bump_ok: bool,
    definite: bool,
) -> dict[str, Decimal | str]:
    charged = money(charged_rub)
    if not bump_ok and definite:
        return {"refund": charged, "keep": Decimal("0.00"), "status": "failed"}
    if not bump_ok:
        return {"refund": Decimal("0.00"), "keep": charged, "status": "unknown"}
    refund = refund_delta(charged, actual_cost_rub)
    return {"refund": refund, "keep": money(charged - refund), "status": "sent"}


def refund_split(
    cashback: Decimal | float | str,
    referral: Decimal | float | str,
    partner: Decimal | float | str,
    refund: Decimal | float | str,
) -> tuple[Decimal, Decimal, Decimal]:
    """Возврат в обратном порядке списания: партнёрские, реферальные, кэшбэк."""
    left = money(refund)
    back_partner = min(money(partner), left)
    left = money(left - back_partner)
    back_ref = min(money(referral), left)
    left = money(left - back_ref)
    back_cb = min(money(cashback), left)
    left = money(left - back_cb)
    if left > 0:
        back_cb = money(back_cb + left)
    return back_cb, back_ref, back_partner


def confirmation_label(count: int | None, *, confirmed: bool) -> str:
    if count is None:
        return "Проверяем подтверждения"
    n = abs(int(count))
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        word = "подтверждение"
    elif n10 in (2, 3, 4) and n100 not in (12, 13, 14):
        word = "подтверждения"
    else:
        word = "подтверждений"
    if confirmed:
        return f"В сети · {n} {word}"
    return f"{n} {word}"


def projected_minutes(coin: str, feerate_sat_vb: float | None, blocks: list | None) -> float | None:
    if coin in ("usdt", "trx"):
        return 1.0
    if not feerate_sat_vb or feerate_sat_vb <= 0 or not blocks:
        return None
    block_min = _BLOCK_MINUTES.get(coin, 10.0)
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        fee_range = block.get("feeRange") or []
        try:
            floor = float(fee_range[0]) if fee_range else float(block.get("medianFee") or 0)
        except (TypeError, ValueError):
            continue
        if float(feerate_sat_vb) + 1e-9 >= floor:
            return block_min * (index + 1)
    return block_min * (len(blocks) + 1)


def eta_label(coin: str, minutes: float | None, *, confirmed: bool) -> str | None:
    if confirmed or minutes is None:
        return None
    if coin in ("usdt", "trx"):
        return "около минуты"
    if minutes <= 10:
        return "около 10 минут"
    if minutes <= 30:
        return "около 20–30 минут"
    if minutes <= 60:
        return "около часа"
    return "больше часа"


# Быстрее, чем просто ждать: ближайший блок, полчаса, час.
_SPEED_CAPS_MIN = (10.0, 30.0, 60.0)


def _block_floor(block) -> float | None:
    if not isinstance(block, dict):
        return None
    fee_range = block.get("feeRange") or []
    try:
        floor = float(fee_range[0]) if fee_range else float(block.get("medianFee") or 0)
    except (TypeError, ValueError):
        return None
    return floor if floor > 0 else None


def bump_speed_targets(current_sat_vb: float | None, blocks: list | None) -> list[dict[str, Any]]:
    """Самая дешёвая ставка, которая всё ещё укладывается в каждый срок.

    Вариант медленнее текущего ожидания не предлагаем.
    """
    current = float(current_sat_vb or 0)
    if current <= 0 or not blocks:
        return []
    current_minutes = projected_minutes("btc", current, blocks)
    if current_minutes is None:
        current_minutes = _BLOCK_MINUTES["btc"] * (len(blocks) + 1)
    found: list[dict[str, Any]] = []
    block_min = _BLOCK_MINUTES["btc"]
    for cap in _SPEED_CAPS_MIN:
        best_floor: float | None = None
        best_minutes: float | None = None
        for index, block in enumerate(blocks):
            minutes = block_min * (index + 1)
            if minutes > cap + 1e-9:
                break
            floor = _block_floor(block)
            if floor is None or floor <= current + 1e-9:
                continue
            if minutes + 1e-9 >= current_minutes:
                continue
            if best_floor is None or floor < best_floor - 1e-9:
                best_floor = floor
                best_minutes = minutes
            elif best_minutes is not None and abs(floor - best_floor) <= 1e-9 and minutes < best_minutes:
                best_minutes = minutes
        if best_floor is None or best_minutes is None:
            continue
        label = eta_label("btc", best_minutes, confirmed=False)
        if any(item["eta_label"] == label for item in found):
            continue
        found.append(
            {
                "target_sat_vb": best_floor,
                "minutes": best_minutes,
                "eta_label": label,
            }
        )
    return found


def label_for_quoted_rate(
    target_label: str | None,
    fee_rate_btc_kvb: float | None,
    blocks: list | None,
) -> str | None:
    """Срок по фактической ставке ноды: RBF может поднять её выше запрошенной."""
    try:
        actual_sat = float(fee_rate_btc_kvb or 0) * 1e5
    except (TypeError, ValueError):
        actual_sat = 0.0
    minutes = projected_minutes("btc", actual_sat, blocks) if actual_sat > 0 else None
    return eta_label("btc", minutes, confirmed=False) or target_label


def collapse_push_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Одинаковый срок — оставляем дешевле. Разница цены до 1 ₽ — оставляем более быстрый."""
    rank = {
        "около 10 минут": 0,
        "около 20–30 минут": 1,
        "около часа": 2,
        "больше часа": 3,
    }
    ordered = sorted(options, key=lambda item: rank.get(str(item.get("eta_label") or ""), 9))
    kept: list[dict[str, Any]] = []
    for opt in ordered:
        price = float(opt.get("price_rub") or 0)
        if price <= 0:
            continue
        if kept and opt.get("eta_label") == kept[-1].get("eta_label"):
            if price + 1 < float(kept[-1]["price_rub"]):
                kept[-1] = opt
            continue
        if kept and abs(price - float(kept[-1]["price_rub"])) <= 1:
            continue
        kept.append(opt)
    return kept[:3]


def push_decision(
    *,
    coin: str,
    ours: bool,
    confirmed: bool,
    quote_ok: bool,
    price: Decimal | None,
    pending: bool = False,
    pending_kind: str | None = None,
    ask_operator: bool = False,
) -> dict[str, Any]:
    if pending:
        reason = "operator" if pending_kind == "asked" else "busy"
        return {"can_push": False, "push_reason": reason, "push_price_rub": None, "push_pending": True}
    if confirmed:
        return {"can_push": False, "push_reason": "already_confirmed", "push_price_rub": None, "push_pending": False}
    if coin != "btc":
        return {"can_push": False, "push_reason": "not_btc", "push_price_rub": None, "push_pending": False}
    if not ours and not ask_operator:
        return {"can_push": False, "push_reason": "not_our_wallet", "push_price_rub": None, "push_pending": False}
    if not quote_ok or price is None or price <= 0:
        return {"can_push": False, "push_reason": "already_fast", "push_price_rub": None, "push_pending": False}
    return {
        "can_push": True,
        "push_reason": None if ours else "operator",
        "push_price_rub": float(money(price)),
        "push_pending": False,
    }


def next_block_sat_vb(blocks: list | None) -> float | None:
    """Нижняя ставка ближайшего прогнозного блока: ниже неё транзакция не в следующем блоке."""
    if not blocks:
        return None
    first = blocks[0] if isinstance(blocks[0], dict) else None
    if not first:
        return None
    fee_range = first.get("feeRange") or []
    try:
        if fee_range:
            rate = float(fee_range[0])
        else:
            rate = float(first.get("medianFee") or 0)
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def mempool_bump_delta_btc(current_sat_vb, target_sat_vb, vsize: int) -> Decimal:
    """Сколько BTC добавить к комиссии, чтобы дотянуть до следующего блока."""
    current = Decimal(str(current_sat_vb or 0))
    target = Decimal(str(target_sat_vb or 0))
    size = Decimal(int(vsize or 0))
    if current <= 0 or target <= 0 or size <= 0 or current >= target:
        return Decimal("0")
    sats = (target - current) * size
    if sats <= 0:
        return Decimal("0")
    return (sats / Decimal("100000000")).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def operator_prompt_text(
    *,
    order_id: str,
    crypto_amount,
    charged_rub: Decimal,
    explorer: str,
) -> str:
    amount = f"{Decimal(str(crypto_amount or 0)):.8f}".rstrip("0").rstrip(".") or "0"
    price = f"{money(charged_rub):.2f}".replace(".", ",")
    return (
        "<b>Пропушить транзакцию?</b>\n"
        f"Заявка: <code>{html.escape(str(order_id))}</code>\n"
        f"Сумма: <b>{html.escape(amount)} BTC</b>\n"
        f"Клиент оплатил ускорение: <b>{price} ₽</b>\n"
        f'<a href="{html.escape(explorer, quote=True)}">Открыть транзакцию</a>'
    )


def operator_prompt_keyboard(bump_id: int) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "Пропушить", "callback_data": f"oppush:{int(bump_id)}:1"},
            {"text": "Не надо", "callback_data": f"oppush:{int(bump_id)}:0"},
        ]]
    }


def payout_coin(crypto: str) -> str:
    return (crypto or "").lower().split("_")[0]


def explorer_url(crypto: str, txid: str) -> str:
    coin = payout_coin(crypto)
    h = (txid or "").strip()
    if coin == "btc":
        return f"https://mempool.space/tx/{h}"
    if coin == "ltc":
        return f"https://blockchair.com/litecoin/transaction/{h}"
    if coin in ("trx", "usdt"):
        return f"https://tronscan.org/#/transaction/{h}"
    return f"https://blockchair.com/search?q={h}"


def shortfall_rub(price: Decimal, available: Decimal | float) -> Decimal:
    gap = money(price - money(available))
    return gap if gap > 0 else Decimal("0.00")


def _empty() -> dict[str, Any]:
    return {"visible": False}


async def _btc_rate() -> Decimal:
    from routers.public import get_rates_cached

    try:
        rates = await get_rates_cached() or {}
        return Decimal(str(rates.get("btc") or 0))
    except Exception:
        logger.debug("btc rate unavailable", exc_info=True)
        return Decimal("0")


async def _latest_payout(conn, user_id: int, order_id: str | None = None):
    if order_id:
        return await conn.fetchrow(
            """
            SELECT order_id, crypto, crypto_amount, payout_tx_hash, status, direction,
                   payout_confirmed_by
            FROM orders
            WHERE user_id = $1
              AND order_id = $2
              AND lower(direction) = 'buy'
              AND status = 'PAID'
              AND COALESCE(payout_tx_hash, '') <> ''
              AND COALESCE(payout_confirmed_at, updated_at, created_at) >= now() - interval '1 day'
            """,
            user_id,
            order_id,
        )
    return await conn.fetchrow(
        """
        SELECT order_id, crypto, crypto_amount, payout_tx_hash, status, direction,
               payout_confirmed_by
        FROM orders
        WHERE user_id = $1
          AND lower(direction) = 'buy'
          AND status = 'PAID'
          AND COALESCE(payout_tx_hash, '') <> ''
          AND COALESCE(payout_confirmed_at, updated_at, created_at) >= now() - interval '1 day'
        ORDER BY COALESCE(payout_confirmed_at, updated_at, created_at) DESC
        LIMIT 1
        """,
        user_id,
    )


async def _our_btc(conn, order_id: str, txid: str) -> bool:
    row = await conn.fetchval(
        """
        SELECT 1
        FROM payout_requests
        WHERE ref_id = $1
          AND txid = $2
          AND lower(coin) = 'btc'
          AND status IN ('sent', 'confirmed')
        LIMIT 1
        """,
        order_id,
        txid,
    )
    return bool(row)


async def _open_bump(conn, order_id: str):
    return await conn.fetchrow(
        """
        SELECT id, status
        FROM payout_fee_bumps
        WHERE order_id = $1 AND status IN ('pending', 'unknown', 'asked')
        ORDER BY id DESC
        LIMIT 1
        """,
        order_id,
    )


async def chain_snapshot(coin: str, txid: str) -> dict[str, Any]:
    if not _TXID.fullmatch(txid or ""):
        return {}
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if coin in ("usdt", "trx"):
                return await _tron_snapshot(session, txid)
            if coin not in _EXPLORER_ORIGIN:
                return {}
            return await _esplora_snapshot(session, coin, txid)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.debug("chain snapshot failed %s %s", coin, txid, exc_info=True)
        return {}


async def _esplora_snapshot(session: aiohttp.ClientSession, coin: str, txid: str) -> dict[str, Any]:
    origin = _EXPLORER_ORIGIN[coin]
    async with session.get(f"{origin}/api/tx/{txid}") as resp:
        if resp.status == 404:
            return {"confirmations": 0, "feerate_sat_vb": None, "vsize": None, "blocks": None}
        if resp.status != 200:
            return {}
        data = await resp.json(content_type=None)
    if not isinstance(data, dict):
        return {}
    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    feerate = None
    vsize = None
    try:
        fee_sats = float(data.get("fee")) if data.get("fee") is not None else None
        weight = data.get("weight")
        parsed = int(data.get("vsize") or 0) or (int(math.ceil(float(weight) / 4)) if weight else 0)
        vsize = parsed or None
        if fee_sats and vsize:
            feerate = fee_sats / vsize
    except (TypeError, ValueError):
        feerate = None
        vsize = None
    if not status.get("confirmed"):
        blocks = await _mempool_blocks(session, origin)
        return {"confirmations": 0, "feerate_sat_vb": feerate, "vsize": vsize, "blocks": blocks}
    height = status.get("block_height")
    tip = await _tip_height(session, origin)
    if height is None or tip is None:
        confirmations = 1
    else:
        confirmations = max(1, int(tip) - int(height) + 1)
    return {"confirmations": confirmations, "feerate_sat_vb": feerate, "vsize": vsize, "blocks": None}


async def _tip_height(session: aiohttp.ClientSession, origin: str) -> int | None:
    async with session.get(f"{origin}/api/blocks/tip/height") as resp:
        if resp.status != 200:
            return None
        text = await resp.text()
    try:
        return int(text.strip())
    except ValueError:
        return None


async def _mempool_blocks(session: aiohttp.ClientSession, origin: str) -> list | None:
    async with session.get(f"{origin}/api/v1/fees/mempool-blocks") as resp:
        if resp.status != 200:
            return None
        data = await resp.json(content_type=None)
    return data if isinstance(data, list) else None


async def _tron_snapshot(session: aiohttp.ClientSession, txid: str) -> dict[str, Any]:
    async with session.get(_TRON.format(txid=txid)) as resp:
        if resp.status != 200:
            return {}
        data = await resp.json(content_type=None)
    if not isinstance(data, dict) or not data.get("hash"):
        return {"confirmations": 0, "feerate_sat_vb": None, "blocks": None}
    if data.get("confirmations") is None:
        confirmations = 1 if data.get("confirmed") else 0
    else:
        confirmations = int(data.get("confirmations") or 0)
    return {"confirmations": confirmations, "feerate_sat_vb": None, "blocks": None}


def _track_payload(
    order,
    *,
    confirmations: int | None,
    eta: str | None,
    decision: dict[str, Any],
    available: Decimal,
) -> dict[str, Any]:
    confirmed = confirmations is not None and confirmations >= 1
    price = decision.get("push_price_rub")
    gap = shortfall_rub(Decimal(str(price)), available) if price else Decimal("0.00")
    amount = order["crypto_amount"]
    return {
        "visible": True,
        "order_id": order["order_id"],
        "coin": payout_coin(order["crypto"]),
        "crypto": order["crypto"],
        "crypto_amount": float(amount) if amount is not None else None,
        "txid": order["payout_tx_hash"],
        "explorer_url": explorer_url(order["crypto"], order["payout_tx_hash"]),
        "confirmations": confirmations,
        "confirmed": confirmed,
        "confirmations_label": confirmation_label(confirmations, confirmed=confirmed),
        "eta_label": eta,
        "can_push": bool(decision.get("can_push")),
        "push_price_rub": price,
        "push_reason": decision.get("push_reason"),
        "push_pending": bool(decision.get("push_pending")),
        "push_pending_label": (
            "Передали оператору"
            if decision.get("push_pending") and decision.get("push_reason") == "operator"
            else None
        ),
        "available_rub": float(money(available)),
        "shortfall_rub": float(gap),
        "push_options": list(decision.get("push_options") or []),
    }


async def _operator_contact(conn, order) -> tuple[int | None, int | None]:
    raw = str(order.get("payout_confirmed_by") or "").strip().lower()
    match = _OPERATOR_BY.fullmatch(raw)
    if not match:
        return None, None
    operator_id = int(match.group(1))
    telegram_id = await conn.fetchval(
        """
        SELECT telegram_user_id
        FROM operator_accounts
        WHERE id = $1 AND is_active = TRUE
        """,
        operator_id,
    )
    try:
        tg = int(telegram_id) if telegram_id is not None else 0
    except (TypeError, ValueError):
        tg = 0
    if tg <= 0:
        return operator_id, None
    return operator_id, tg


async def _quote_push_options(
    txid: str,
    feerate: float | None,
    blocks: list | None,
    rate: Decimal,
) -> list[dict[str, Any]]:
    targets = bump_speed_targets(feerate, blocks)
    if not targets or rate <= 0:
        return []
    from signer_client import quote_signer_bump, quote_signer_bumps

    raw = await quote_signer_bumps(txid, [float(item["target_sat_vb"]) for item in targets])
    quotes = list(raw.get("quotes") or [])
    if not quotes and raw.get("reason") == "signer_unavailable":
        single = await quote_signer_bump(txid)
        if single.get("ok"):
            priced = buyer_price(cost_from_delta(single.get("delta_fee") or 0, rate))
            if priced > 0:
                return [
                    {
                        "eta_label": "около 10 минут",
                        "price_rub": float(priced),
                        "fee_rate_sat_vb": float(
                            single.get("target_feerate_sat_vb") or single.get("feerate_sat_vb") or 0
                        ),
                    }
                ]
        return []
    by_target: dict[float, dict[str, Any]] = {}
    for quote in quotes:
        try:
            key = round(float(quote.get("target_feerate_sat_vb") or 0), 4)
        except (TypeError, ValueError):
            continue
        by_target[key] = quote
    options: list[dict[str, Any]] = []
    for target in targets:
        quote = by_target.get(round(float(target["target_sat_vb"]), 4))
        if not quote or not quote.get("ok"):
            continue
        priced = buyer_price(cost_from_delta(quote.get("delta_fee") or 0, rate))
        if priced <= 0:
            continue
        label = label_for_quoted_rate(target["eta_label"], quote.get("fee_rate_btc_kvb"), blocks)
        if not label:
            continue
        options.append(
            {
                "eta_label": label,
                "price_rub": float(priced),
                "fee_rate_sat_vb": float(target["target_sat_vb"]),
            }
        )
    return collapse_push_options(options)


def _operator_price(chain: dict[str, Any], rate: Decimal) -> Decimal | None:
    target = next_block_sat_vb(chain.get("blocks"))
    delta = mempool_bump_delta_btc(
        chain.get("feerate_sat_vb"),
        target,
        int(chain.get("vsize") or 0),
    )
    if delta <= 0 or rate <= 0:
        return None
    priced = buyer_price(cost_from_delta(delta, rate))
    return priced if priced > 0 else None


async def payout_track_for_user(user_id: int) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await _latest_payout(conn, user_id)
        if not order:
            return _empty()
        coin = payout_coin(order["crypto"])
        txid = str(order["payout_tx_hash"])
        ours = await _our_btc(conn, order["order_id"], txid) if coin == "btc" else False
        pending = await _open_bump(conn, order["order_id"])
        operator_tg = None
        if coin == "btc" and not ours:
            _operator_id, operator_tg = await _operator_contact(conn, order)
        available = Decimal(str(await unified_available(conn, user_id)))

    signer_status: dict[str, Any] = {}
    options: list[dict[str, Any]] = []
    if ours and not pending:
        from signer_client import fetch_signer_tx

        signer_status = await fetch_signer_tx("btc", txid)

    chain = await chain_snapshot(coin, txid)
    confirmations = chain.get("confirmations")
    feerate = chain.get("feerate_sat_vb")
    if signer_status.get("found"):
        confirmations = int(signer_status.get("confirmations") or 0)
        if signer_status.get("feerate_sat_vb"):
            feerate = signer_status.get("feerate_sat_vb")
    confirmed = confirmations is not None and int(confirmations) >= 1
    minutes = projected_minutes(
        coin,
        float(feerate) if feerate else None,
        chain.get("blocks"),
    )
    eta = eta_label(coin, minutes, confirmed=confirmed)
    price = None
    quote_ok = False
    ask_operator = False
    ours_live = ours and bool(signer_status.get("found"))
    needs_rate = (ours_live and not confirmed and not pending) or (
        coin == "btc" and not ours and operator_tg and not confirmed and not pending
    )
    rate = await _btc_rate() if needs_rate else Decimal("0")
    if ours_live and not confirmed and not pending and rate > 0:
        options = await _quote_push_options(txid, float(feerate) if feerate else None, chain.get("blocks"), rate)
        if options:
            quote_ok = True
            price = options[0]["price_rub"]
    if not quote_ok and (
        coin == "btc"
        and not ours
        and operator_tg
        and not confirmed
        and not pending
    ):
        price = _operator_price(chain, rate)
        quote_ok = price is not None
        ask_operator = quote_ok
    decision = push_decision(
        coin=coin,
        ours=ours_live,
        confirmed=confirmed,
        quote_ok=quote_ok,
        price=price,
        pending=bool(pending),
        pending_kind=str(pending["status"]) if pending else None,
        ask_operator=ask_operator,
    )
    decision["push_options"] = options
    return _track_payload(order, confirmations=confirmations, eta=eta, decision=decision, available=available)


async def _spendable(conn, user_id: int) -> tuple[float, float, float]:
    cashback = float(await get_cashback_balance_conn(conn, user_id) or 0)
    referral = float(
        await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)::float
            FROM user_referral_ledger WHERE referrer_user_id = $1
            """,
            user_id,
        )
        or 0
    )
    pending = await _pending_user_withdrawal_rub(conn, user_id)
    client_avail = max(0.0, cashback + referral - pending)
    spendable_cb = min(max(cashback, 0.0), client_avail)
    spendable_ref = max(0.0, client_avail - spendable_cb)
    partner = await _partner_parts(conn, user_id)
    return spendable_cb, spendable_ref, float(partner.get("available_rub") or 0)


def push_debit_key(order_id: str) -> str:
    """Не order_id заявки: на нём уже висит начисление кешбэка, колонка UNIQUE."""
    return f"btc-push:{order_id}:{uuid.uuid4().hex[:12]}"


def push_refund_key(bump_id: int) -> str:
    return f"btc-push-refund:{int(bump_id)}"


async def _debit(
    conn,
    user_id: int,
    amount: Decimal,
    order_id: str,
    *,
    ledger_key: str,
) -> tuple[Decimal, Decimal, Decimal]:
    cashback, referral, partner_avail = await _spendable(conn, user_id)
    try:
        from_cb, from_ref, from_partner = split_sources(cashback, referral, partner_avail, amount)
    except TransferError as exc:
        raise PushError("funds", "Недостаточно средств") from exc
    note = f"Ускорение Bitcoin {order_id}"
    if from_cb > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            """,
            user_id,
            -from_cb,
            ledger_key,
            note,
        )
    if from_ref > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'payout', $2, $3, $4)
            """,
            user_id,
            -from_ref,
            ledger_key,
            note,
        )
    if from_partner > 0:
        partner = await _partner_parts(conn, user_id)
        campaign_id = partner.get("campaign_id")
        if not campaign_id:
            raise PushError("funds", "Недостаточно средств")
        await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", int(campaign_id))
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
            VALUES ($1, 'payout', $2, $3)
            """,
            int(campaign_id),
            -from_partner,
            note,
        )
    return from_cb, from_ref, from_partner


async def _credit(
    conn,
    user_id: int,
    order_id: str,
    cashback: Decimal,
    referral: Decimal,
    partner: Decimal,
    *,
    ledger_key: str,
) -> None:
    note = f"Возврат ускорения Bitcoin {order_id}"
    if cashback > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            """,
            user_id,
            cashback,
            ledger_key,
            note,
        )
    if referral > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'adjustment', $2, $3, $4)
            """,
            user_id,
            referral,
            ledger_key,
            note,
        )
    if partner > 0:
        campaign = await _partner_parts(conn, user_id)
        campaign_id = campaign.get("campaign_id")
        if campaign_id:
            await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", int(campaign_id))
            await conn.execute(
                """
                INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
                VALUES ($1, 'adjustment', $2, $3)
                """,
                int(campaign_id),
                partner,
                note,
            )


async def _refund_bump_conn(
    conn,
    row,
    refund: Decimal,
    *,
    status: str,
    error: str | None,
) -> None:
    if row["status"] not in ("pending", "unknown", "asked"):
        return
    if refund <= 0 and status == "sent":
        return
    user_id = int(row["user_id"])
    order_id = str(row["order_id"])
    already = money(row["refunded_rub"] or 0)
    room = money(money(row["debited_rub"]) - already)
    give = min(money(refund), room)
    back_cb, back_ref, back_partner = refund_split(
        row["cashback_rub"],
        row["referral_rub"],
        row["partner_rub"],
        give,
    )
    if give > 0:
        await _credit(
            conn,
            user_id,
            order_id,
            back_cb,
            back_ref,
            back_partner,
            ledger_key=push_refund_key(int(row["id"])),
        )
    await conn.execute(
        """
        UPDATE payout_fee_bumps
        SET status = $2,
            error = $3,
            refunded_rub = refunded_rub + $4,
            charged_rub = debited_rub - (refunded_rub + $4),
            cashback_rub = cashback_rub - $5,
            referral_rub = referral_rub - $6,
            partner_rub = partner_rub - $7,
            updated_at = now()
        WHERE id = $1
        """,
        int(row["id"]),
        status,
        error,
        give,
        back_cb,
        back_ref,
        back_partner,
    )


async def _refund_bump(bump_id: int, user_id: int, order_id: str, refund: Decimal, *, status: str, error: str | None) -> None:
    _ = user_id, order_id
    if refund <= 0 and status == "sent":
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM payout_fee_bumps WHERE id = $1 FOR UPDATE",
                bump_id,
            )
            if not row:
                return
            await _refund_bump_conn(conn, row, refund, status=status, error=error)


async def _reserve_charge(
    *,
    user_id: int,
    order_id: str,
    txid: str,
    charge: Decimal,
    status: str,
    fee_rate: Decimal | None,
    operator_id: int | None,
    fee_delta_crypto: Decimal | None = None,
    fee_delta_rub: Decimal | None = None,
) -> tuple[int, tuple[Decimal, Decimal, Decimal]]:
    parts = (Decimal("0"), Decimal("0"), Decimal("0"))
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", int(user_id))
                locked = await conn.fetchrow(
                    """
                    SELECT payout_tx_hash
                    FROM orders
                    WHERE order_id = $1 AND user_id = $2
                    FOR UPDATE
                    """,
                    order_id,
                    user_id,
                )
                if not locked or str(locked["payout_tx_hash"]) != txid:
                    raise PushError("changed", "Транзакция уже обновилась")
                if await _open_bump(conn, order_id):
                    raise PushError("busy", "Ускорение уже выполняется")
                available = Decimal(str(await unified_available(conn, user_id)))
                if available + Decimal("0.001") < charge:
                    gap = shortfall_rub(charge, available)
                    raise PushError(
                        "funds",
                        f"На балансе не хватает {gap} ₽",
                        shortfall_rub=float(gap),
                    )
                parts = await _debit(
                    conn, user_id, charge, order_id, ledger_key=push_debit_key(order_id)
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO payout_fee_bumps (
                        order_id, user_id, old_txid, coin, debited_rub,
                        cashback_rub, referral_rub, partner_rub, fee_rate_btc_kvb,
                        fee_delta_crypto, fee_delta_rub, operator_id, status
                    )
                    VALUES ($1, $2, $3, 'btc', $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING id
                    """,
                    order_id,
                    user_id,
                    txid,
                    charge,
                    parts[0],
                    parts[1],
                    parts[2],
                    fee_rate,
                    fee_delta_crypto,
                    fee_delta_rub,
                    operator_id,
                    status,
                )
                return int(row["id"]), parts
    except PushError:
        raise
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise PushError("busy", "Ускорение уже выполняется") from exc
        raise


async def _notify_operator(telegram_id: int, bump_id: int, order, charge: Decimal, txid: str) -> bool:
    from telegram_notify import send_user_message

    text = operator_prompt_text(
        order_id=str(order["order_id"]),
        crypto_amount=order["crypto_amount"],
        charged_rub=charge,
        explorer=explorer_url(str(order["crypto"] or "btc"), txid),
    )
    return await send_user_message(
        int(telegram_id),
        text,
        reply_markup=operator_prompt_keyboard(bump_id),
    )


async def _push_via_operator(
    *,
    user_id: int,
    order,
    txid: str,
    confirmed_price: Decimal,
    operator_id: int,
    operator_tg: int,
) -> dict[str, Any]:
    chain = await chain_snapshot("btc", txid)
    if chain.get("confirmations") is not None and int(chain["confirmations"]) >= 1:
        raise PushError("already_confirmed", "Транзакция уже в сети")
    rate = await _btc_rate()
    if rate <= 0:
        raise PushError("rate", "Курс временно недоступен")
    target = next_block_sat_vb(chain.get("blocks"))
    delta = mempool_bump_delta_btc(chain.get("feerate_sat_vb"), target, int(chain.get("vsize") or 0))
    fresh_cost = cost_from_delta(delta, rate)
    fresh_price = buyer_price(fresh_cost)
    charge = resolve_charge(confirmed_price, fresh_price)
    if charge <= 0 or delta <= 0:
        raise PushError("already_fast", "Ускорение не требуется")
    order_id = str(order["order_id"])
    bump_id, _parts = await _reserve_charge(
        user_id=user_id,
        order_id=order_id,
        txid=txid,
        charge=charge,
        status="asked",
        fee_rate=None,
        operator_id=operator_id,
        fee_delta_crypto=delta,
        fee_delta_rub=fresh_cost,
    )
    sent = await _notify_operator(operator_tg, bump_id, order, charge, txid)
    if not sent:
        await _refund_bump(bump_id, user_id, order_id, charge, status="failed", error="notify_failed")
        raise PushError("unavailable", "Не удалось спросить оператора, деньги вернулись на баланс")
    track = await payout_track_for_user(user_id)
    return {"ok": True, "charged_rub": float(charge), "txid": txid, "asked": True, "track": track}


async def answer_operator_push(bump_id: int, telegram_user_id: int, accept: bool) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM payout_fee_bumps WHERE id = $1 FOR UPDATE",
                int(bump_id),
            )
            if not row:
                raise PushError("not_found", "Запрос не найден")
            if str(row["status"]) != "asked":
                return {"ok": True, "already": True, "text": "Уже ответили."}
            linked = await conn.fetchval(
                """
                SELECT telegram_user_id
                FROM operator_accounts
                WHERE id = $1 AND is_active = TRUE
                """,
                row["operator_id"],
            )
            try:
                linked_id = int(linked) if linked is not None else 0
            except (TypeError, ValueError):
                linked_id = 0
            if linked_id <= 0 or linked_id != int(telegram_user_id):
                raise PushError("forbidden", "Это не ваша выплата")
            if accept:
                await conn.execute(
                    """
                    UPDATE payout_fee_bumps
                    SET status = 'accepted',
                        charged_rub = debited_rub,
                        updated_at = now()
                    WHERE id = $1 AND status = 'asked'
                    """,
                    int(bump_id),
                )
                return {"ok": True, "status": "accepted", "text": "Ок, пропушьте транзакцию в своём кошельке."}
            await _refund_bump_conn(
                conn,
                row,
                money(row["debited_rub"]),
                status="failed",
                error="operator_declined",
            )
            return {"ok": True, "status": "failed", "text": "Клиенту вернули оплату."}


async def push_payout(
    user_id: int,
    order_id: str,
    quote_rub: float,
    fee_rate_sat_vb: float | None = None,
) -> dict[str, Any]:
    confirmed_price = money(quote_rub)
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await _latest_payout(conn, user_id, order_id)
    if not order:
        raise PushError("not_found", "Заявка не найдена")
    coin = payout_coin(order["crypto"])
    txid = str(order["payout_tx_hash"])
    if coin != "btc":
        raise PushError("not_btc", "Ускорение доступно только для Bitcoin")

    async with pool.acquire() as conn:
        ours = await _our_btc(conn, order_id, txid)
        if await _open_bump(conn, order_id):
            raise PushError("busy", "Ускорение уже выполняется")
        operator_id, operator_tg = (None, None)
        if not ours:
            operator_id, operator_tg = await _operator_contact(conn, order)

    if not ours:
        if not operator_tg or operator_id is None:
            raise PushError("not_our_wallet", "Ускорение недоступно")
        return await _push_via_operator(
            user_id=user_id,
            order=order,
            txid=txid,
            confirmed_price=confirmed_price,
            operator_id=operator_id,
            operator_tg=operator_tg,
        )

    from signer_client import quote_signer_bump, quote_signer_bumps, submit_signer_bump

    if fee_rate_sat_vb and float(fee_rate_sat_vb) > 0:
        raw = await quote_signer_bumps(txid, [float(fee_rate_sat_vb)])
        items = list(raw.get("quotes") or [])
        ok_items = [item for item in items if item.get("ok")]
        if ok_items:
            quote = ok_items[0]
        elif raw.get("reason") == "signer_unavailable":
            quote = await quote_signer_bump(txid)
        elif items:
            quote = items[0]
        else:
            quote = {"ok": False, "reason": raw.get("reason") or "unavailable"}
    else:
        quote = await quote_signer_bump(txid)
    if not quote.get("ok"):
        reason = str(quote.get("reason") or "unavailable")
        if reason == "already_confirmed":
            raise PushError("already_confirmed", "Транзакция уже в сети")
        raise PushError("unavailable", "Ускорение сейчас недоступно")
    rate = await _btc_rate()
    if rate <= 0:
        raise PushError("rate", "Курс временно недоступен")
    fresh_cost = cost_from_delta(quote.get("delta_fee") or 0, rate)
    fresh_price = buyer_price(fresh_cost)
    charge = resolve_charge(confirmed_price, fresh_price)
    if charge <= 0:
        raise PushError("already_fast", "Ускорение не требуется")
    fee_rate = float(quote.get("fee_rate_btc_kvb") or 0)
    if fee_rate <= 0:
        raise PushError("unavailable", "Ускорение сейчас недоступно")

    bump_id = None
    parts = (Decimal("0"), Decimal("0"), Decimal("0"))
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", int(user_id))
                locked = await conn.fetchrow(
                    """
                    SELECT payout_tx_hash
                    FROM orders
                    WHERE order_id = $1 AND user_id = $2
                    FOR UPDATE
                    """,
                    order_id,
                    user_id,
                )
                if not locked or str(locked["payout_tx_hash"]) != txid:
                    raise PushError("changed", "Транзакция уже обновилась")
                if await _open_bump(conn, order_id):
                    raise PushError("busy", "Ускорение уже выполняется")
                available = Decimal(str(await unified_available(conn, user_id)))
                if available + Decimal("0.001") < charge:
                    gap = shortfall_rub(charge, available)
                    raise PushError(
                        "funds",
                        f"На балансе не хватает {gap} ₽",
                        shortfall_rub=float(gap),
                    )
                parts = await _debit(
                    conn, user_id, charge, order_id, ledger_key=push_debit_key(order_id)
                )
                row = await conn.fetchrow(
                    """
                    INSERT INTO payout_fee_bumps (
                        order_id, user_id, old_txid, coin, debited_rub,
                        cashback_rub, referral_rub, partner_rub, fee_rate_btc_kvb, status
                    )
                    VALUES ($1, $2, $3, 'btc', $4, $5, $6, $7, $8, 'pending')
                    RETURNING id
                    """,
                    order_id,
                    user_id,
                    txid,
                    charge,
                    parts[0],
                    parts[1],
                    parts[2],
                    Decimal(str(fee_rate)),
                )
                bump_id = int(row["id"])
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise PushError("busy", "Ускорение уже выполняется") from exc
        raise

    try:
        result = await submit_signer_bump(txid, fee_rate)
    except Exception:
        logger.exception("bump outcome unknown order=%s", order_id)
        result = {"ok": False, "definite": False, "reason": "unknown"}
    done = settlement(
        charge,
        cost_from_delta(result.get("delta_fee") or 0, rate) if result.get("ok") else 0,
        bump_ok=bool(result.get("ok")),
        definite=bool(result.get("definite", True)),
    )
    if done["status"] != "sent":
        await _refund_bump(
            int(bump_id),
            user_id,
            order_id,
            Decimal(str(done["refund"])),
            status=str(done["status"]),
            error=str(result.get("reason") or "")[:200] or None,
        )
        if done["status"] == "unknown":
            raise PushError("unknown", "Платёж принят, проверяем транзакцию")
        raise PushError("unavailable", "Ускорение не прошло, деньги вернулись на баланс")

    new_txid = str(result.get("txid") or "")
    actual_cost = cost_from_delta(result.get("delta_fee") or 0, rate)
    refund = Decimal(str(done["refund"]))
    keep = Decimal(str(done["keep"]))
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if refund > 0:
                back_cb, back_ref, back_partner = refund_split(parts[0], parts[1], parts[2], refund)
                await _credit(
                    conn,
                    user_id,
                    order_id,
                    back_cb,
                    back_ref,
                    back_partner,
                    ledger_key=push_refund_key(int(bump_id)),
                )
            else:
                back_cb = back_ref = back_partner = Decimal("0")
            await conn.execute(
                """
                UPDATE payout_fee_bumps
                SET status = 'sent',
                    new_txid = $2,
                    fee_delta_crypto = $3,
                    fee_delta_rub = $4,
                    charged_rub = $5,
                    refunded_rub = $6,
                    cashback_rub = cashback_rub - $7,
                    referral_rub = referral_rub - $8,
                    partner_rub = partner_rub - $9,
                    updated_at = now()
                WHERE id = $1 AND status = 'pending'
                """,
                int(bump_id),
                new_txid or None,
                Decimal(str(result.get("delta_fee") or 0)),
                actual_cost,
                keep,
                refund,
                back_cb,
                back_ref,
                back_partner,
            )
            if new_txid:
                await conn.execute(
                    """
                    UPDATE orders
                    SET payout_tx_hash = $1, updated_at = now()
                    WHERE order_id = $2 AND payout_tx_hash = $3
                    """,
                    new_txid,
                    order_id,
                    txid,
                )
                await conn.execute(
                    """
                    UPDATE payout_requests
                    SET txid = $1, updated_at = now()
                    WHERE ref_id = $2 AND txid = $3
                    """,
                    new_txid,
                    order_id,
                    txid,
                )
    track = await payout_track_for_user(user_id)
    return {"ok": True, "charged_rub": float(keep), "txid": new_txid, "track": track}

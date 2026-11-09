"""Пополнение казино BTC/LTC на отдельный адрес клиента в горячем кошельке.

Текущий адрес дома ротируется сам и сюда не записывается. Баланс растёт
только после одного подтверждения, по курсу продажи фактически пришедшей суммы.
"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import Awaitable, Callable

from casino_finance import casino_operation_ref, money
from casino_wagering import record_crypto_deposit_lock

logger = logging.getLogger("casino_crypto_deposit")

COINS = ("btc", "ltc")
NETWORKS = {"btc": "Bitcoin", "ltc": "Litecoin"}
HINT = "Зачислим после 1 подтверждения по курсу продажи"
MIN_DEPOSIT_RUB = Decimal("100")
_POLL_SEC = 30
_CHUNK = 100
_SATOSHI = Decimal("0.00000001")
_BTC = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,62}$")
_LTC = re.compile(r"^(ltc1|[LM])[a-zA-HJ-NP-Z0-9]{25,62}$")
_TXID = re.compile(r"^[0-9a-f]{64}$")

QuoteFn = Callable[[str, Decimal], Awaitable[tuple[Decimal | None, Decimal | None, bool]]]


def min_deposit_rub(coin: str) -> Decimal:
    """Порог казино. Минимум обмена (1 000 ₽) на этот приём не распространяется."""
    _coin(coin)
    return money(MIN_DEPOSIT_RUB)


def address_ok(coin: str, address: str) -> bool:
    pattern = _BTC if coin == "btc" else _LTC
    return bool(pattern.match((address or "").strip()))


def ledger_order_id(coin: str, txid: str) -> str:
    """Ключ леджера короче VARCHAR(64): полный txid туда не помещается."""
    return casino_operation_ref(f"crypto-{coin}", txid)


def ledger_note(coin: str, txid: str) -> str:
    return f"Casino deposit: {coin} {txid}"


def _coin(coin: str) -> str:
    name = (coin or "").strip().lower()
    if name not in COINS:
        raise ValueError("Доступны только Bitcoin и Litecoin")
    return name


def _quantize_crypto(amount: Decimal) -> Decimal:
    return amount.quantize(_SATOSHI)


async def _indicative_sell_rate(coin: str) -> Decimal:
    """Курс продажи за 1 монету, без биржевого минимума и без подгонки реквизита."""
    from order_service import get_sell_market_rates
    from runtime_settings import sell_discount

    market = await get_sell_market_rates()
    price = market.get(coin) if isinstance(market, dict) else None
    if not price:
        raise RuntimeError("rate_unavailable")
    rate = Decimal(str(price)) * Decimal(str(sell_discount()))
    if rate <= 0:
        raise RuntimeError("rate_unavailable")
    return rate


async def quote_crypto_deposit(coin: str, amount_crypto: Decimal) -> tuple[Decimal | None, Decimal | None, bool]:
    """(рубли, курс, ниже минимума). RuntimeError — курс недоступен, строку не пишем."""
    from fastapi import HTTPException
    from order_service import quote_sell

    name = _coin(coin)
    quantized = _quantize_crypto(amount_crypto)
    try:
        quote = await quote_sell(name, crypto_amount=float(quantized))
    except HTTPException as exc:
        detail = str(exc.detail or "")
        if exc.status_code == 400 and "Минимум" in detail:
            rate = await _indicative_sell_rate(name)
            rub = money(quantized * rate)
            return rub, rate, rub < min_deposit_rub(name)
        raise RuntimeError(detail or "quote_failed") from exc
    rub = money(quote["fiat_amount"])
    rate = Decimal(str(quote["rate"]))
    if rub < min_deposit_rub(name):
        return rub, rate, True
    return rub, rate, False


async def credit_observed_payment(
    conn,
    *,
    user_id: int,
    coin: str,
    address: str,
    txid: str,
    amount_crypto: Decimal,
    confirmations: int,
    quote: QuoteFn | None = None,
) -> str:
    """Зачислить один подтверждённый вход. Повтор того же txid ничего не дописывает."""
    name = _coin(coin)
    payment_id = (txid or "").strip().lower()
    if user_id == 0 or not _TXID.match(payment_id) or int(confirmations) < 1:
        return "skipped"
    amount = _quantize_crypto(Decimal(amount_crypto))
    if amount <= 0 or not address_ok(name, address):
        return "skipped"
    pricer = quote or quote_crypto_deposit
    try:
        rub, rate, below = await pricer(name, amount)
    except Exception as exc:
        logger.warning("casino crypto quote failed %s %s: %s", name, payment_id, exc)
        return "skipped"
    if below:
        rub_value = rub
        rate_value = rate
        status = "below_minimum"
        order_id = None
    else:
        if rub is None or rate is None:
            return "skipped"
        rub_value = rub
        rate_value = rate
        status = "credited"
        order_id = ledger_order_id(name, payment_id)
        if len(order_id) > 64:
            raise RuntimeError("ledger order id exceeds 64 chars")

    async with conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"casino-crypto:{name}:{payment_id}",
        )
        existing = await conn.fetchrow(
            """
            SELECT id, status, address
            FROM casino_crypto_credits
            WHERE coin = $1 AND txid = $2
            """,
            name,
            payment_id,
        )
        if existing:
            if str(existing["address"]) != address:
                logger.error(
                    "casino crypto txid %s already stored for %s, not %s",
                    payment_id,
                    existing["address"],
                    address,
                )
            return "duplicate"
        inserted = await conn.fetchrow(
            """
            INSERT INTO casino_crypto_credits (
                user_id, coin, address, txid, amount_crypto, amount_rub, rate,
                confirmations, status, ledger_order_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (coin, txid) DO NOTHING
            RETURNING id
            """,
            user_id,
            name,
            address,
            payment_id,
            amount,
            rub_value,
            rate_value,
            int(confirmations),
            status,
            order_id,
        )
        if not inserted:
            return "duplicate"
        if status != "credited" or order_id is None or rub_value is None:
            return "below_minimum"
        ledger = await conn.fetchrow(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'accrual', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            RETURNING user_id, amount_rub
            """,
            user_id,
            rub_value,
            order_id,
            ledger_note(name, payment_id),
        )
        if ledger is None:
            stored = await conn.fetchrow(
                "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
                order_id,
            )
            if (
                not stored
                or int(stored["user_id"]) != user_id
                or money(stored["amount_rub"]) != rub_value
            ):
                raise RuntimeError("casino crypto ledger conflict")
        await record_crypto_deposit_lock(
            conn,
            crypto_credit_id=int(inserted["id"]),
            telegram_id=user_id,
            deposit_rub=rub_value,
        )
    return "credited"


async def _load_or_mint(conn, user_id: int, coin: str) -> str:
    from fastapi import HTTPException
    from signer_client import mint_signer_receive_address

    row = await conn.fetchrow(
        """
        SELECT address FROM casino_crypto_addresses
        WHERE user_id = $1 AND coin = $2
        """,
        user_id,
        coin,
    )
    if row:
        return str(row["address"])
    minted = await mint_signer_receive_address(coin)
    address = str(minted.get("address") or "").strip()
    if not minted.get("ok") or not address_ok(coin, address):
        raise HTTPException(status_code=503, detail="Адрес сейчас недоступен")
    inserted = await conn.fetchrow(
        """
        INSERT INTO casino_crypto_addresses (user_id, coin, address)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, coin) DO NOTHING
        RETURNING address
        """,
        user_id,
        coin,
        address,
    )
    if inserted:
        return str(inserted["address"])
    again = await conn.fetchrow(
        """
        SELECT address FROM casino_crypto_addresses
        WHERE user_id = $1 AND coin = $2
        """,
        user_id,
        coin,
    )
    if not again:
        raise HTTPException(status_code=503, detail="Адрес сейчас недоступен")
    return str(again["address"])


async def ensure_crypto_address(user_id: int, coin: str) -> dict:
    from db import get_pool

    name = _coin(coin)
    if user_id == 0:
        raise ValueError("Нет профиля клиента")
    pool = await get_pool()
    key = f"casino-addr:{user_id}:{name}"
    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock(hashtextextended($1, 0))", key)
        try:
            address = await _load_or_mint(conn, user_id, name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtextextended($1, 0))", key)
    rate: float | None
    try:
        rate = float(await _indicative_sell_rate(name))
    except Exception:
        logger.warning("indicative casino crypto rate failed for %s", name)
        rate = None
    return {
        "coin": name,
        "address": address,
        "network": NETWORKS[name],
        "min_rub": int(min_deposit_rub(name)),
        "rate": rate,
        "hint": HINT,
    }


def _deposit_out(row) -> dict:
    amount_rub = row["amount_rub"]
    created = row["created_at"]
    return {
        "coin": row["coin"],
        "txid": row["txid"],
        "address": row["address"],
        "amount_crypto": format(Decimal(row["amount_crypto"]), "f"),
        "amount_rub": None if amount_rub is None else format(money(amount_rub), "f"),
        "status": row["status"],
        "confirmations": int(row["confirmations"] or 0),
        "created_at": created.isoformat() if created is not None else None,
    }


async def list_user_crypto_deposits(user_id: int) -> list[dict]:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT coin, txid, address, amount_crypto, amount_rub, status,
                   confirmations, created_at
            FROM casino_crypto_credits
            WHERE user_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT 50
            """,
            user_id,
        )
    return [_deposit_out(row) for row in rows]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


async def scan_casino_crypto_deposits() -> int:
    from db import get_pool
    from signer_client import fetch_signer_receive_incoming, signer_configured

    if not signer_configured():
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, coin, address FROM casino_crypto_addresses"
        )
    owners: dict[tuple[str, str], int] = {}
    by_coin: dict[str, list[str]] = {}
    for row in rows:
        coin = str(row["coin"])
        address = str(row["address"])
        owners[(coin, address)] = int(row["user_id"])
        by_coin.setdefault(coin, []).append(address)
    credited = 0
    for coin, addresses in by_coin.items():
        for chunk in _chunks(addresses, _CHUNK):
            incoming = await fetch_signer_receive_incoming(coin, chunk)
            if not incoming.get("ok"):
                logger.warning("casino crypto scan %s: %s", coin, incoming.get("reason"))
                continue
            for item in incoming.get("items") or []:
                if not isinstance(item, dict):
                    continue
                address = str(item.get("address") or "")
                user_id = owners.get((coin, address))
                if user_id is None:
                    continue
                try:
                    amount = Decimal(str(item.get("amount") or "0"))
                    confirmations = int(item.get("confirmations") or 0)
                except Exception:
                    logger.warning("casino crypto item skipped %s", item, exc_info=True)
                    continue
                try:
                    async with pool.acquire() as conn:
                        result = await credit_observed_payment(
                            conn,
                            user_id=user_id,
                            coin=coin,
                            address=address,
                            txid=str(item.get("txid") or ""),
                            amount_crypto=amount,
                            confirmations=confirmations,
                        )
                except Exception:
                    logger.exception("casino crypto credit failed %s %s", coin, item.get("txid"))
                    continue
                if result == "credited":
                    credited += 1
    return credited


async def casino_crypto_deposit_loop() -> None:
    while True:
        try:
            await scan_casino_crypto_deposits()
        except Exception:
            logger.exception("casino crypto deposit scan failed")
        await asyncio.sleep(_POLL_SEC)

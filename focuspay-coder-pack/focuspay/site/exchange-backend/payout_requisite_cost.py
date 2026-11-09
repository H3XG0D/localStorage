"""Стоимость реквизита выплаты в финансовом журнале.

`cost_pct` может быть отрицательной: +3 = доплачиваем 3% за проход,
−3 = реквизит приносит нам 3%. Считаем от фактически выплаченного объёма,
поэтому проводку делаем только при финализации реквизита.

`economics_snapshot` заявок намеренно не трогаем — это иммутабельный снимок
тарифов на момент котировки (см. `economics_snapshot.FORMULA_VERSION`).
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

LEDGER_SOURCE = "payout_requisite"
LEDGER_ENTRY_TYPE = "expense"
RUB_CENTS = Decimal("0.01")

DEFAULT_CRYPTO = "usdt"
SUPPORTED_CRYPTO = ("usdt", "btc", "trx", "ltc")
DIRECTION_PAYOUT = "payout"
DIRECTION_PAYIN = "payin"
# Шаг округления выплаты реквизитчику по монетам.
CRYPTO_STEP = {
    "usdt": Decimal("0.01"),
    "btc": Decimal("0.00000001"),
    "ltc": Decimal("0.00000001"),
    "trx": Decimal("0.0001"),
}


def _direction(value: str | None) -> str:
    raw = (value or DIRECTION_PAYOUT).strip().lower()
    return DIRECTION_PAYIN if raw == DIRECTION_PAYIN else DIRECTION_PAYOUT


def cost_rub(paid_rub, cost_pct) -> Decimal:
    paid = Decimal(str(paid_rub or 0))
    pct = Decimal(str(cost_pct or 0))
    return (paid * pct / 100).quantize(RUB_CENTS)


def payoff_rub(paid_rub, cost_pct, direction: str = DIRECTION_PAYOUT) -> Decimal:
    """Рублёвый эквивалент крипты, которая меняется с реквизитчиком.

    payout: мы должны ему номинал плюс стоимость прохода.
    payin:  он получил рубли клиента и должен нам номинал минус стоимость —
            знак обратный, потому что поток крипты развернут.
    """
    paid = Decimal(str(paid_rub or 0))
    cost = cost_rub(paid_rub, cost_pct)
    if _direction(direction) == DIRECTION_PAYIN:
        return (paid - cost).quantize(RUB_CENTS)
    return (paid + cost).quantize(RUB_CENTS)


def payoff_crypto(rub, rate_rub, crypto: str = DEFAULT_CRYPTO) -> Decimal:
    """Рубли к выплате → крипта по курсу рубль-за-монету."""
    rate = Decimal(str(rate_rub or 0))
    if rate <= 0:
        raise ValueError("rate_rub must be positive")
    step = CRYPTO_STEP.get((crypto or "").lower(), CRYPTO_STEP[DEFAULT_CRYPTO])
    return (Decimal(str(rub or 0)) / rate).quantize(step)


def ledger_reference(requisite_id: int) -> str:
    return f"payout-requisite-{int(requisite_id)}"


async def post_requisite_cost(conn, row) -> int | None:
    """Идемпотентно провести стоимость реквизита. Возвращает id проводки.

    Payin не проводим: его стоимость уже сидит в `orders.card_fee_pct`
    (cost_pct/100) и попала бы в PnL второй раз.
    """
    if _direction(row.get("direction") if hasattr(row, "get") else None) == DIRECTION_PAYIN:
        return None
    amount = cost_rub(row["paid_rub"], row["cost_pct"])
    if amount == 0:
        return None

    reference = ledger_reference(int(row["id"]))
    existing = await conn.fetchval(
        "SELECT id FROM owner_finance_ledger WHERE reference = $1",
        reference,
    )
    if existing:
        return int(existing)

    note = (
        f"Реквизит выплаты #{int(row['id'])}: "
        f"{float(row['paid_rub'] or 0):.2f} ₽ под {float(row['cost_pct'] or 0):+.3f}%"
    )
    return await conn.fetchval(
        """
        INSERT INTO owner_finance_ledger (
            occurred_at, entry_type, amount, currency,
            source, reference, status, note
        )
        VALUES (now(), $1, $2, 'RUB', $3, $4, 'confirmed', $5)
        RETURNING id
        """,
        LEDGER_ENTRY_TYPE,
        amount,
        LEDGER_SOURCE,
        reference,
        note,
    )


async def safe_post_requisite_cost(conn, row) -> int | None:
    """Проводка не должна ломать закрытие реквизита."""
    try:
        return await post_requisite_cost(conn, row)
    except Exception:
        logger.exception("payout requisite cost posting failed")
        return None

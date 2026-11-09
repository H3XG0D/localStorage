"""Запас горячего BTC/LTC и срок, на который его хватит при текущем темпе.

Темп — исходящие за 7 дней: оплаченные покупки и оплаченные выводы баланса.
Продажи сюда не входят: они приходят на адрес приёма, не на этот кошелёк.
"""
from __future__ import annotations

from typing import Any

WINDOW_DAYS = 7
COINS = ("btc", "ltc")


def days_left(balance: float, outflow: float, *, window_days: int = WINDOW_DAYS) -> float | None:
    """Сколько дней продержится balance, если outflow копился window_days."""
    if outflow <= 0 or window_days <= 0:
        return None
    daily = outflow / window_days
    if daily <= 0:
        return None
    return float(balance) / daily


def days_phrase(days: float | None) -> str:
    if days is None:
        return "темпа нет"
    if days < 1:
        return "меньше суток"
    return f"хватит ≈ {max(1, int(round(days)))} дн"


def hours_left(days: float | None) -> float | None:
    """Тот же темп, что у days_left, в часах."""
    if days is None:
        return None
    return float(days) * 24


def hours_phrase(hours: float | None) -> str:
    if hours is None:
        return "темпа нет"
    if hours < 1:
        return "меньше часа"
    return f"хватит ≈ {max(1, int(round(hours)))} ч"


def fmt_crypto(amount: float) -> str:
    text = f"{float(amount):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_rub(amount: float) -> str:
    return f"{round(float(amount)):,.0f}".replace(",", " ")


def _flow(outflow: dict[str, dict[str, float]], coin: str) -> dict[str, float]:
    row = outflow.get(coin) or {}
    return {
        "buy_crypto": float(row.get("buy_crypto") or 0),
        "buy_rub": float(row.get("buy_rub") or 0),
        "withdraw_rub": float(row.get("withdraw_rub") or 0),
        "deals": float(row.get("deals") or 0),
    }


def assemble_runway(
    *,
    coins: list[dict[str, Any]],
    outflow: dict[str, dict[str, float]],
    min_hot_balance_rub: float,
    signer_ok: bool,
) -> dict[str, Any]:
    """Склеивает остатки подписанта и темп выплат. Сеть и БД снаружи."""
    by_name = {str(c.get("coin") or "").lower(): c for c in coins}
    rows: list[dict[str, Any]] = []
    total_rub = 0.0
    total_out_rub = 0.0
    for coin in COINS:
        src = by_name.get(coin) or {}
        spendable = float(src.get("spendable") or 0)
        try:
            rate = float(src.get("rate_rub") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        value_rub = round(spendable * rate, 2)
        total_rub += value_rub
        flow = _flow(outflow, coin)
        # В заявке на вывод нет суммы монеты — оцениваем её текущим курсом.
        withdraw_crypto = flow["withdraw_rub"] / rate if rate > 0 else 0.0
        out_crypto = flow["buy_crypto"] + withdraw_crypto
        out_rub = flow["buy_rub"] + flow["withdraw_rub"]
        total_out_rub += out_rub
        left = None if not signer_ok else days_left(spendable, out_crypto)
        hours = None if not signer_ok else hours_left(left)
        if not signer_ok:
            phrase = "нет данных"
            hour_text = "нет данных"
        elif spendable <= 0 and out_crypto > 0:
            phrase = "кончились"
            hour_text = "кончились"
        else:
            phrase = days_phrase(left)
            hour_text = hours_phrase(hours)
        rows.append(
            {
                "coin": coin,
                "spendable": spendable,
                "unconfirmed": float(src.get("unconfirmed") or 0),
                "rate_rub": rate,
                "value_rub": value_rub,
                "outflow_crypto_7d": round(out_crypto, 8),
                "outflow_rub_7d": round(out_rub, 2),
                "deals_7d": int(flow["deals"]),
                "days_left": left,
                "hours_left": hours,
                "phrase": phrase,
                "hours_phrase": hour_text,
                "line": f"{coin.upper()} {fmt_crypto(spendable)} · ≈ {fmt_rub(value_rub)} ₽ · {phrase}",
            }
        )

    floor = max(0.0, float(min_hot_balance_rub or 0))
    below = floor > 0 and total_rub + 0.01 < floor
    if not signer_ok:
        floor_phrase = "кошелёк не на связи"
        until_floor = None
    elif floor <= 0:
        floor_phrase = ""
        until_floor = None
    elif below:
        floor_phrase = f"ниже порога {fmt_rub(floor)} ₽ — новые авто-заявки не стартуют"
        until_floor = 0.0
    else:
        until_floor = days_left(total_rub - floor, total_out_rub)
        if until_floor is None:
            floor_phrase = f"порог {fmt_rub(floor)} ₽ · темпа нет"
        else:
            floor_phrase = f"до порога {fmt_rub(floor)} ₽ · {days_phrase(until_floor)}"

    return {
        "window_days": WINDOW_DAYS,
        "available": bool(signer_ok),
        "total_rub": round(total_rub, 2),
        "min_hot_balance_rub": floor,
        "below_floor": below if signer_ok else False,
        "days_until_floor": until_floor,
        "floor_phrase": floor_phrase,
        "outflow_rub_7d": round(total_out_rub, 2),
        "coins": rows,
    }


def empty_runway(reason: str = "нет данных") -> dict[str, Any]:
    return assemble_runway(
        coins=[],
        outflow={},
        min_hot_balance_rub=0,
        signer_ok=False,
    ) | {"floor_phrase": reason, "available": False}


async def load_coin_outflow(conn) -> dict[str, dict[str, float]]:
    """Покупки PAID и оплаченные выводы баланса BTC/LTC за окно."""
    buys = await conn.fetch(
        """
        SELECT lower(split_part(COALESCE(crypto, ''), '_', 1)) AS coin,
               COUNT(*)::int AS deals,
               COALESCE(SUM(crypto_amount), 0)::float AS buy_crypto,
               COALESCE(SUM(fiat_amount), 0)::float AS buy_rub
        FROM orders
        WHERE lower(direction) = 'buy'
          AND status = 'PAID'
          AND lower(split_part(COALESCE(crypto, ''), '_', 1)) IN ('btc', 'ltc')
          AND COALESCE(payout_confirmed_at, updated_at) >= now() - ($1 || ' days')::interval
        GROUP BY 1
        """,
        str(WINDOW_DAYS),
    )
    withdrawals = await conn.fetch(
        """
        SELECT lower(split_part(COALESCE(crypto, ''), '_', 1)) AS coin,
               COUNT(*)::int AS deals,
               COALESCE(SUM(COALESCE(payout_amount_rub, amount_rub)), 0)::float AS withdraw_rub
        FROM user_referral_withdrawals
        WHERE status = 'paid'
          AND method = 'crypto'
          AND COALESCE(source, 'balance') = 'balance'
          AND lower(split_part(COALESCE(crypto, ''), '_', 1)) IN ('btc', 'ltc')
          AND COALESCE(processed_at, created_at) >= now() - ($1 || ' days')::interval
        GROUP BY 1
        """,
        str(WINDOW_DAYS),
    )
    out: dict[str, dict[str, float]] = {}
    for row in buys:
        coin = str(row["coin"] or "")
        if coin not in COINS:
            continue
        out[coin] = {
            "buy_crypto": float(row["buy_crypto"] or 0),
            "buy_rub": float(row["buy_rub"] or 0),
            "withdraw_rub": 0.0,
            "deals": float(row["deals"] or 0),
        }
    for row in withdrawals:
        coin = str(row["coin"] or "")
        if coin not in COINS:
            continue
        slot = out.setdefault(
            coin,
            {"buy_crypto": 0.0, "buy_rub": 0.0, "withdraw_rub": 0.0, "deals": 0.0},
        )
        slot["withdraw_rub"] = float(row["withdraw_rub"] or 0)
        slot["deals"] = float(slot["deals"]) + float(row["deals"] or 0)
    return out


async def build_hot_wallet_runway(conn) -> dict[str, Any]:
    """Живой остаток подписанта плюс темп из базы. Ошибка связи не роняет отчёт."""
    import logging

    from auto_settings import auto_min_hot_balance_rub
    from hot_wallet_monitor import _coin_rates
    from signer_client import fetch_signer_balances, fetch_signer_health, signer_configured

    logger = logging.getLogger("hot_wallet_runway")
    floor = auto_min_hot_balance_rub()
    try:
        outflow = await load_coin_outflow(conn)
    except Exception:
        logger.warning("hot wallet outflow query failed", exc_info=True)
        outflow = {}

    if not signer_configured():
        report = assemble_runway(coins=[], outflow=outflow, min_hot_balance_rub=floor, signer_ok=False)
        report["floor_phrase"] = "кошелёк не подключён"
        return report

    try:
        health = await fetch_signer_health()
        balances = await fetch_signer_balances()
        rates = await _coin_rates()
    except Exception:
        logger.warning("hot wallet signer snapshot failed", exc_info=True)
        report = assemble_runway(coins=[], outflow=outflow, min_hot_balance_rub=floor, signer_ok=False)
        report["floor_phrase"] = "нет данных"
        return report

    signer_ok = health.get("http_status") == 200 and bool(balances.get("ok", health.get("http_status") == 200))
    raw = balances.get("coins") if isinstance(balances.get("coins"), dict) else {}
    coins: list[dict[str, Any]] = []
    for coin in COINS:
        row = raw.get(coin) if isinstance(raw.get(coin), dict) else {}
        if not row:
            signer_ok = False if health.get("http_status") != 200 else signer_ok
        try:
            rate = float((rates or {}).get(coin) or 0)
        except (TypeError, ValueError):
            rate = 0.0
        from hot_wallet_topups import effective_spendable, pending_unconfirmed

        coins.append(
            {
                "coin": coin,
                "spendable": effective_spendable(row),
                "unconfirmed": pending_unconfirmed(row),
                "rate_rub": rate,
            }
        )
    if health.get("http_status") != 200:
        signer_ok = False
    report = assemble_runway(
        coins=coins,
        outflow=outflow,
        min_hot_balance_rub=floor,
        signer_ok=signer_ok,
    )
    if not signer_ok:
        report["floor_phrase"] = "кошелёк не на связи"
    return report

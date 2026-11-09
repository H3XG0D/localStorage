from decimal import Decimal, ROUND_DOWN
import html

CRYPTO_DECIMALS = {
    "btc": 8,
    "usdt": 2,
    "trx": 2,
    "ltc": 8,
}


def base_crypto(symbol: str) -> str:
    """
    USDT_TRC20 → usdt
    BTC → btc
    """
    return symbol.split("_")[0].lower()


def _promo_admin_html(order: dict) -> str | None:
    promo_code = order.get("promo_code")
    if not promo_code:
        return None
    from services.promo_bonus import promo_bonus_note

    note = promo_bonus_note(
        bonus_percent=order.get("promo_bonus_percent"),
        bonus_fixed_rub=order.get("promo_bonus_fixed_rub"),
    )
    code = html.escape(str(promo_code))
    if note:
        return f"🎁 Промо: <code>{code}</code> — {note}"
    return f"🎁 Промо: <code>{code}</code>"


def fmt_crypto(value, crypto: str) -> str:
    """
    Форматирует крипту для отображения:
    - BTC → до 8 знаков
    - USDT / TRX → 2 знака; LTC → 5 знаков
    """
    crypto = crypto.lower()
    decimals = CRYPTO_DECIMALS.get(crypto, 8)

    q = Decimal("1") / (Decimal(10) ** decimals)
    d = Decimal(str(value)).quantize(q, rounding=ROUND_DOWN)

    return format(d, "f")


def _event_for_admin_card(order: dict) -> str:
    status = str(order.get("status") or "").upper()
    if status == "PAID":
        return "paid"
    if status == "CANCELED":
        return "canceled"
    if status == "COMPLETED":
        return "payout_reminder"
    return "awaiting_payout"


def render_admin_message(order: dict, reconciliation_sum: float | None = None) -> str:
    """Карточка BUY для /search и edit после «Выплачено» — тот же дизайн, что lifecycle."""
    from services.order_ops_notify import format_ops_message

    order_for = dict(order)
    if reconciliation_sum is not None:
        order_for["fiat_amount"] = reconciliation_sum

    status = str(order.get("status") or "").upper()
    note = None
    if status == "COMPLETED":
        # format_ops_message сам соберёт текст для payout_reminder без note
        note = None

    text = format_ops_message(
        _event_for_admin_card(order),
        order_for,
        note=note,
    )
    promo = _promo_admin_html(order)
    if promo:
        text = f"{text}\n\n{promo}"
    return text


def render_admin_message_sell(order: dict) -> str:
    """Карточка SELL для /search и pay/cancel — единый ops-каркас."""
    from services.order_ops_notify import format_ops_message

    text = format_ops_message(
        _event_for_admin_card(order)
        if str(order.get("status") or "").upper() in ("PAID", "CANCELED", "COMPLETED")
        else "awaiting_payout",
        dict(order),
        note="Проверьте поступление средств перед выплатой",
    )
    promo = _promo_admin_html(order)
    if promo:
        text = f"{text}\n\n{promo}"
    return text

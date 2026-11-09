"""Общий безопасный формат статуса wagering для сообщений казино-бота."""
from __future__ import annotations

from typing import Mapping


def _as_money(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def deposit_wagering_preview(
    deposit: float,
    *,
    wagering_percent: float,
    commission_percent: float,
) -> tuple[float, float]:
    """Вернуть (плюс казино, объём ставок) для суммы пополнения."""
    house = round(deposit * wagering_percent / 100.0, 2)
    if commission_percent <= 0:
        return house, 0.0
    return house, round(house * 100.0 / commission_percent, 2)


def deposit_wagering_rules(
    *,
    wagering_percent: float,
    commission_percent: float,
    currency_symbol: str,
) -> str:
    house, stake = deposit_wagering_preview(
        1000.0,
        wagering_percent=wagering_percent,
        commission_percent=commission_percent,
    )
    return (
        f"Для вывода казино должно получить {wagering_percent:.0f}% плюса с суммы пополнения. "
        f"Пример: 1000 {currency_symbol} → {house:.2f} {currency_symbol} комиссии "
        f"≈ {stake:.2f} {currency_symbol} ставок при комиссии {commission_percent:.0f}%."
    )


def deposit_wagering_for_amount(
    credit: float,
    *,
    wagering_percent: float,
    commission_percent: float,
    currency_symbol: str,
) -> str:
    house, stake = deposit_wagering_preview(
        credit,
        wagering_percent=wagering_percent,
        commission_percent=commission_percent,
    )
    return (
        "После зачисления средства доступны в играх. Для вывода казино должно получить "
        f"<b>{house:.2f} {currency_symbol}</b> комиссии ({wagering_percent:.0f}% от пополнения). "
        f"При комиссии {commission_percent:.0f}% поставьте примерно "
        f"<b>{stake:.2f} {currency_symbol}</b>."
    )


def help_wagering_line(
    *,
    wagering_percent: float,
    commission_percent: float,
    currency_symbol: str,
) -> str:
    house, stake = deposit_wagering_preview(
        1000.0,
        wagering_percent=wagering_percent,
        commission_percent=commission_percent,
    )
    return (
        f"• Отыгрыш пополнения: казино получает {wagering_percent:.0f}% плюса с депозита. "
        f"Пример: 1000 {currency_symbol} → {house:.2f} {currency_symbol} комиссии "
        f"≈ {stake:.2f} {currency_symbol} ставок при комиссии {commission_percent:.0f}%"
    )


def wagering_hint(data: Mapping[str, object], *, currency_symbol: str) -> str:
    """Вернуть текст текущего остатка отыгрыша без сетевых запросов."""
    remaining_stake = _as_money(
        data.get("remaining_stake_rub")
        if data.get("remaining_stake_rub") is not None
        else data.get("remaining_rub")
    )
    locked = _as_money(data.get("locked_rub"))
    if remaining_stake is None or locked is None:
        return ""
    if remaining_stake > 0 and locked > 0:
        house = _as_money(data.get("remaining_house_take_rub"))
        rate = _as_money(data.get("commission_rate_percent"))
        house_line = ""
        if house is not None and house > 0:
            rate_bit = f" при комиссии {rate:.0f}%" if rate else ""
            house_line = (
                f"Казино должно получить ещё <b>{house:.2f} {currency_symbol}</b> "
                f"комиссии с ваших ставок{rate_bit}.\n"
            )
        return (
            f"\n\n🔒 Для вывода за пределы игры удерживается "
            f"<b>{locked:.2f} {currency_symbol}</b>.\n"
            f"{house_line}"
            f"Поставьте ещё примерно на <b>{remaining_stake:.2f} {currency_symbol}</b>. "
            "Средства всё это время остаются доступны в играх."
        )
    return "\n\n✅ Отыгрыш выполнен. Комиссия игр снижена до 5%."

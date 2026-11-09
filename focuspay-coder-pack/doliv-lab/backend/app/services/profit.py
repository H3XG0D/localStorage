from decimal import Decimal
from typing import Any

from app.models import DealResult, Doliv, Requisite, Zaliv


def calc_zaliv_total(zalivs: list[Zaliv]) -> Decimal:
    return sum((z.amount for z in zalivs), Decimal("0"))


def calc_remaining(requisite: Requisite, zalivs: list[Zaliv]) -> Decimal:
    return (requisite.total_amount - calc_zaliv_total(zalivs)).quantize(Decimal("0.01"))


def calc_required_doliv_amount(requisite: Requisite, zalivs: list[Zaliv]) -> Decimal:
    remaining = calc_remaining(requisite, zalivs)
    return max(Decimal("0"), remaining).quantize(Decimal("0.01"))


def calc_avg_rate(zalivs: list[Zaliv]) -> Decimal | None:
    if not zalivs:
        return None
    total_amount = calc_zaliv_total(zalivs)
    if total_amount == 0:
        return None
    weighted = sum((z.amount * z.rate for z in zalivs), Decimal("0"))
    return (weighted / total_amount).quantize(Decimal("0.0001"))


def calc_zaliv_profit_usdt(zaliv: Zaliv, target_rate: Decimal) -> Decimal:
    """Profit of a single zaliv in USDT (RUB commission converted by the requisite rate)."""
    if target_rate <= 0:
        return Decimal("0")
    profit_rub = zaliv.amount * zaliv.profit_percent / Decimal("100")
    return (profit_rub / target_rate).quantize(Decimal("0.01"))


def calc_zaliv_profit(zalivs: list[Zaliv], target_rate: Decimal) -> Decimal:
    """Total profit of all zalivs in USDT."""
    if target_rate <= 0:
        return Decimal("0")
    profit_rub = sum(
        (z.amount * z.profit_percent / Decimal("100") for z in zalivs),
        Decimal("0"),
    )
    return (profit_rub / target_rate).quantize(Decimal("0.01"))


def calc_doliv_profit_loss(doliv: Doliv, target_rate: Decimal) -> Decimal:
    if doliv.rate <= 0 or target_rate <= 0:
        return Decimal("0")
    doliv_usdt = doliv.amount / doliv.rate
    target_usdt = doliv.amount / target_rate
    return (target_usdt - doliv_usdt).quantize(Decimal("0.01"))


def calc_current_profit(zalivs: list[Zaliv], target_rate: Decimal) -> Decimal:
    return calc_zaliv_profit(zalivs, target_rate)


def calc_turnover_usdt(zalivs: list[Zaliv], doliv: Doliv | None = None) -> Decimal:
    """Convert RUB turnover to USDT using each operation's own rate."""
    total = Decimal("0")
    for z in zalivs:
        if z.rate > 0:
            total += z.amount / z.rate
    if doliv is not None and doliv.rate > 0:
        total += doliv.amount / doliv.rate
    return total.quantize(Decimal("0.01"))


def calc_fake_check_loss(fake_checks: list[Any]) -> Decimal:
    """Total loss from fake checks in USDT."""
    return sum((fc.amount_usdt for fc in fake_checks), Decimal("0")).quantize(Decimal("0.01"))


def build_deal_result(
    requisite: Requisite, zalivs: list[Zaliv], doliv: Doliv, merged_path: str | None
) -> DealResult:
    zaliv_total = calc_zaliv_total(zalivs)
    total_turnover = zaliv_total + doliv.amount
    avg_rate = calc_avg_rate(zalivs) or doliv.rate
    zaliv_profit = calc_zaliv_profit(zalivs, requisite.target_rate)
    doliv_profit_loss = calc_doliv_profit_loss(doliv, requisite.target_rate)
    final_profit = (zaliv_profit + doliv_profit_loss).quantize(Decimal("0.01"))

    return DealResult(
        requisite_id=requisite.id,
        total_turnover=total_turnover,
        turnover_usdt=calc_turnover_usdt(zalivs, doliv),
        avg_rate=avg_rate,
        doliv_amount=doliv.amount,
        doliv_rate=doliv.rate,
        zaliv_profit=zaliv_profit,
        doliv_profit_loss=doliv_profit_loss,
        final_profit=final_profit,
        merged_receipt_path=merged_path,
    )

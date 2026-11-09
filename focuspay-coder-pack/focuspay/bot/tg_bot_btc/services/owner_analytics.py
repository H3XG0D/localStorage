"""Сбор метрик для панели владельца."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from services import config_rates
from services.db import (
    count_bot_active_users,
    count_bot_new_users,
    count_funnel_created_order,
    count_funnel_paid_users,
    count_funnel_starts,
    count_old_pending_orders,
    count_no_shift_requisites_blocks,
    count_stale_sell_operator_pending,
    count_terminal_orders_today,
    count_web_guest_sessions,
    count_web_new_registrations,
    count_web_unique_ips,
    get_active_operator_shifts,
    get_last_paid_order,
    get_max_open_order_fiat,
    get_no_shift_requisites_blocks,
    get_open_orders_summary,
    get_paid_orders_for_owner_date,
    get_paid_orders_for_owner_days,
    get_payfast_conversion_period,
    get_recent_bot_new_users,
    get_stale_completed_buy_orders,
    get_top_web_ips,
    sum_buy_network_fee_rub,
    sum_buy_network_fee_rub_for_date,
    sum_cashback_accrual_rub,
    sum_cashback_accrual_rub_for_date,
    sum_operator_wallet_payout_rub,
    sum_operator_wallet_payout_rub_for_date,
    sum_partner_accrual_rub,
    sum_partner_accrual_rub_for_date,
    sum_referral_accrual_rub,
    sum_referral_accrual_rub_for_date,
    sum_review_bonus_rub,
    sum_review_bonus_rub_for_date,
)
from services.economics_snapshot import order_economics
from services.stats_period import parse_stats_period_arg

logger = logging.getLogger(__name__)
_MSK = ZoneInfo("Europe/Moscow")


def _today_msk() -> date:
    return datetime.now(_MSK).date()


def aggregate_owner_profit(orders: list[Any]) -> tuple[int, float, float]:
    """count, turnover_rub, net_profit_rub (убытки не clamp'им в 0)."""
    count = len(orders)
    turnover = 0.0
    profit = 0.0
    for o in orders:
        fiat = float(o.get("fiat_amount") or 0)
        turnover += fiat
        profit += order_economics(dict(o), clamp=False)["service_profit_rub"]
    return count, turnover, profit


@dataclass
class MoneyPeriod:
    deals: int = 0
    turnover_rub: float = 0.0
    """Маржа сделок+внештат до начислений (= finance total.net_profit)."""
    profit_rub: float = 0.0
    review_bonus_rub: float = 0.0
    wallet_payout_rub: float = 0.0
    buy_network_fee_rub: float = 0.0
    cashback_accrual_rub: float = 0.0
    referral_accrual_rub: float = 0.0
    partner_accrual_rub: float = 0.0
    focus_lucky_rub: float = 0.0
    swap_commission_rub: float = 0.0
    operators_payroll_rub: float = 0.0
    admin_salary_rub: float = 0.0
    usdt_issued_rub: float = 0.0
    manual_expenses_rub: float = 0.0
    external_profit_rub: float = 0.0
    casino_profit_rub: float = 0.0
    vpn_profit_rub: float = 0.0
    profit_after_costs_rub: float = 0.0
    """Финальный остаток (= finance payroll.owner_residual)."""
    net_profit_rub: float = 0.0
    from_pnl: bool = False


def money_period_with_expenses(
    deals: int,
    turnover: float,
    profit: float,
    review_bonus: float,
    wallet_payout: float = 0.0,
    buy_network_fee: float = 0.0,
    cashback_accrual: float = 0.0,
    referral_accrual: float = 0.0,
    partner_accrual: float = 0.0,
) -> MoneyPeriod:
    rb = max(0.0, float(review_bonus or 0))
    wp = max(0.0, float(wallet_payout or 0))
    nf = max(0.0, float(buy_network_fee or 0))
    cb = max(0.0, float(cashback_accrual or 0))
    rf = max(0.0, float(referral_accrual or 0))
    pa = max(0.0, float(partner_accrual or 0))
    return MoneyPeriod(
        deals=deals,
        turnover_rub=turnover,
        profit_rub=profit,
        review_bonus_rub=rb,
        wallet_payout_rub=wp,
        buy_network_fee_rub=nf,
        cashback_accrual_rub=cb,
        referral_accrual_rub=rf,
        partner_accrual_rub=pa,
        profit_after_costs_rub=profit - rb - wp - cb - rf - pa,
        net_profit_rub=profit - rb - wp - nf - cb - rf - pa,
        from_pnl=False,
    )


def money_period_with_review_bonus(
    deals: int,
    turnover: float,
    profit: float,
    review_bonus: float,
) -> MoneyPeriod:
    return money_period_with_expenses(deals, turnover, profit, review_bonus, 0.0)


def money_from_pnl(pnl: dict) -> MoneyPeriod:
    """Маппинг compute_pnl → MoneyPeriod (те же цифры, что Финансы/дашборд)."""
    total = pnl.get("total") or {}
    costs = pnl.get("costs") or {}
    payroll = pnl.get("payroll") or {}
    external = pnl.get("external") or {}
    manuals = pnl.get("manual_expenses") or {}

    deals = 0
    for row in pnl.get("by_type") or []:
        if (row.get("type") or "") in ("external", "casino", "vpn"):
            continue
        deals += int(row.get("orders") or 0)

    return MoneyPeriod(
        deals=deals,
        turnover_rub=float(total.get("fiat_volume") or 0),
        profit_rub=float(total.get("net_profit") or 0),
        review_bonus_rub=float(costs.get("review_bonus") or 0),
        wallet_payout_rub=float(costs.get("wallet_payout") or 0),
        buy_network_fee_rub=0.0,
        cashback_accrual_rub=float(costs.get("cashback") or 0),
        referral_accrual_rub=float(costs.get("referral") or 0),
        partner_accrual_rub=float(costs.get("partner") or 0),
        focus_lucky_rub=float(costs.get("focus_lucky") or 0),
        swap_commission_rub=float(costs.get("swap_commission") or 0),
        operators_payroll_rub=float(payroll.get("operators_total") or 0),
        admin_salary_rub=float(payroll.get("admin_salary") or 0),
        usdt_issued_rub=float(costs.get("usdt_issued_rub") or 0),
        manual_expenses_rub=float(manuals.get("total") or 0),
        external_profit_rub=float(external.get("house_profit_rub") or 0),
        casino_profit_rub=float((pnl.get("casino") or {}).get("owner_profit_rub") or 0),
        vpn_profit_rub=float((pnl.get("vpn") or {}).get("owner_profit_rub") or 0),
        profit_after_costs_rub=float(total.get("profit_after_costs") or 0),
        net_profit_rub=float(payroll.get("owner_residual") or 0),
        from_pnl=True,
    )


async def _compute_pnl(d_from: date, d_to: date) -> dict:
    """Тот же compute_pnl, что /x8/finance — через internal API (без sys.path хаков)."""
    import aiohttp

    base = (os.environ.get("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = (
        os.environ.get("INTERNAL_API_SECRET")
        or os.environ.get("WEBHOOK_SECRET")
        or ""
    ).strip()
    if not token:
        raise RuntimeError("INTERNAL_API_SECRET not set")

    url = f"{base}/api/internal/pnl"
    params = {"date_from": d_from.isoformat(), "date_to": d_to.isoformat()}
    headers = {"X-Internal-Token": token}
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params, headers=headers) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"internal pnl HTTP {resp.status}: {body[:300]}")
            import json

            return json.loads(body)


async def fetch_hot_wallet_runway() -> dict | None:
    """Запас горячего кошелька. None — /dash не должен падать."""
    import json

    import aiohttp

    base = (os.environ.get("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = (
        os.environ.get("INTERNAL_API_SECRET")
        or os.environ.get("WEBHOOK_SECRET")
        or ""
    ).strip()
    if not token:
        logger.warning("hot wallet runway skipped: INTERNAL_API_SECRET not set")
        return None
    url = f"{base}/api/internal/hot-wallet-runway"
    headers = {"X-Internal-Token": token}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.warning("hot wallet runway HTTP %s: %s", resp.status, body[:200])
                    return None
                data = json.loads(body)
                return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("hot wallet runway fetch failed", exc_info=True)
        return None


async def fetch_autopilot_savings() -> dict | None:
    """Плюс автопилота за 7 дней. None — /dash не должен падать."""
    import json

    import aiohttp

    base = (os.environ.get("EXCHANGE_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    token = (
        os.environ.get("INTERNAL_API_SECRET")
        or os.environ.get("WEBHOOK_SECRET")
        or ""
    ).strip()
    if not token:
        logger.warning("autopilot savings skipped: INTERNAL_API_SECRET not set")
        return None
    url = f"{base}/api/internal/autopilot-savings"
    headers = {"X-Internal-Token": token}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.warning("autopilot savings HTTP %s: %s", resp.status, body[:200])
                    return None
                data = json.loads(body)
                return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("autopilot savings fetch failed", exc_info=True)
        return None


async def _money_for_range(d_from: date, d_to: date) -> MoneyPeriod:
    """Деньги периода через compute_pnl (как /x8/finance). Fallback — старая схема."""
    try:
        pnl = await _compute_pnl(d_from, d_to)
        return money_from_pnl(pnl)
    except Exception:
        logger.exception("compute_pnl failed for %s..%s — fallback owner SQL", d_from, d_to)
        days = (d_to - d_from).days + 1
        if days <= 1:
            return await _money_legacy_for_date(d_from)
        return await _money_legacy_for_days(days)


async def _expenses_for_days(days: int) -> tuple[float, float, float, float, float, float]:
    rb = await sum_review_bonus_rub(days)
    wp = await sum_operator_wallet_payout_rub(days)
    nf = await sum_buy_network_fee_rub(days)
    cb = await sum_cashback_accrual_rub(days)
    rf = await sum_referral_accrual_rub(days)
    pa = await sum_partner_accrual_rub(days)
    return rb, wp, nf, cb, rf, pa


async def _expenses_for_date(d_obj: date) -> tuple[float, float, float, float, float, float]:
    rb = await sum_review_bonus_rub_for_date(d_obj)
    wp = await sum_operator_wallet_payout_rub_for_date(d_obj)
    nf = await sum_buy_network_fee_rub_for_date(d_obj)
    cb = await sum_cashback_accrual_rub_for_date(d_obj)
    rf = await sum_referral_accrual_rub_for_date(d_obj)
    pa = await sum_partner_accrual_rub_for_date(d_obj)
    return rb, wp, nf, cb, rf, pa


async def _money_legacy_for_days(days: int) -> MoneyPeriod:
    orders = await get_paid_orders_for_owner_days(days=days)
    deals, turnover, profit = aggregate_owner_profit(orders)
    rb, wp, nf, cb, rf, pa = await _expenses_for_days(days)
    return money_period_with_expenses(
        deals, turnover, profit, rb, wp, nf, cb, rf, pa
    )


async def _money_legacy_for_date(d_obj: date) -> MoneyPeriod:
    orders = await get_paid_orders_for_owner_date(d_obj)
    deals, turnover, profit = aggregate_owner_profit(orders)
    rb, wp, nf, cb, rf, pa = await _expenses_for_date(d_obj)
    return money_period_with_expenses(
        deals, turnover, profit, rb, wp, nf, cb, rf, pa
    )


async def _money_for_days(days: int) -> MoneyPeriod:
    today = _today_msk()
    d_from = today - timedelta(days=max(1, days) - 1)
    return await _money_for_range(d_from, today)


@dataclass
class AudiencePeriod:
    bot_new: int = 0
    bot_active: int = 0
    web_unique_ips: int = 0
    web_guest_sessions: int = 0


@dataclass
class FunnelPeriod:
    starts: int = 0
    created_order: int = 0
    paid_users: int = 0


@dataclass
class PayfastConversionPeriod:
    taken: int = 0
    paid: int = 0
    failed: int = 0
    conversion_pct: float | None = None
    days: int = 1


@dataclass
class OwnerSnapshot:
    fetched_at: datetime
    period_label: str = "сегодня"
    period_days: int = 1
    money: MoneyPeriod = field(default_factory=MoneyPeriod)
    money_week: MoneyPeriod = field(default_factory=MoneyPeriod)
    audience: AudiencePeriod = field(default_factory=AudiencePeriod)
    audience_week: AudiencePeriod = field(default_factory=AudiencePeriod)
    funnel: FunnelPeriod = field(default_factory=FunnelPeriod)
    payfast_today: PayfastConversionPeriod = field(default_factory=PayfastConversionPeriod)
    payfast_30d: PayfastConversionPeriod = field(
        default_factory=lambda: PayfastConversionPeriod(days=30)
    )
    stale_sell_pending: int = 0
    stale_completed: list[Any] = field(default_factory=list)
    old_pending_count: int = 0
    terminal_today: dict[str, int] = field(default_factory=dict)
    open_by_status: dict[str, int] = field(default_factory=dict)
    shifts: list[Any] = field(default_factory=list)
    last_paid: Any | None = None
    max_open_fiat: float | None = None
    missed_requisites_count: int = 0
    missed_requisites: list[dict[str, Any]] = field(default_factory=list)


async def _audience_for_days(days: int) -> AudiencePeriod:
    return AudiencePeriod(
        bot_new=await count_bot_new_users(days),
        bot_active=await count_bot_active_users(days),
        web_unique_ips=await count_web_unique_ips(days),
        web_guest_sessions=await count_web_guest_sessions(days),
    )


async def fetch_owner_snapshot(
    *,
    period_arg: str | None = None,
    include_week: bool = True,
) -> OwnerSnapshot:
    """period_arg: None = сегодня; '7'; 'DD.MM.YYYY'."""
    arg = period_arg if period_arg is not None else datetime.now().strftime("%d.%m.%Y")
    _get_orders_fn, header_kw = parse_stats_period_arg(
        arg,
        get_paid_for_date=get_paid_orders_for_owner_date,
        get_paid_for_days=get_paid_orders_for_owner_days,
    )

    period_start: datetime
    period_end: datetime
    if header_kw.get("by_date"):
        period_label = header_kw.get("date_label", "дата")
        period_days = 1
        d_obj = datetime.strptime(period_label, "%d.%m.%Y").date()
        money = await _money_for_range(d_obj, d_obj)
        aud_days = 1
        period_start = datetime.combine(d_obj, datetime.min.time(), tzinfo=_MSK)
        period_end = period_start + timedelta(days=1)
    else:
        period_days = int(header_kw.get("days", 1))
        period_label = (
            "сегодня"
            if period_days == 1
            else f"последние {period_days} дн."
        )
        money = await _money_for_days(period_days)
        aud_days = period_days
        period_end = datetime.now(_MSK)
        period_start = datetime.combine(
            _today_msk() - timedelta(days=period_days - 1),
            datetime.min.time(),
            tzinfo=_MSK,
        )

    audience = await _audience_for_days(aud_days)
    funnel = FunnelPeriod(
        starts=await count_funnel_starts(aud_days),
        created_order=await count_funnel_created_order(aud_days),
        paid_users=await count_funnel_paid_users(aud_days),
    )
    money_week = MoneyPeriod()
    audience_week = AudiencePeriod()
    if include_week and period_days <= 1:
        money_week = await _money_for_days(7)
        audience_week = await _audience_for_days(7)

    stale_min = max(1, int(config_rates.OWNER_STALE_PAYOUT_MINUTES))
    stale = await get_stale_completed_buy_orders(stale_min, limit=5)
    open_rows = await get_open_orders_summary()
    open_map = {str(r["status"]): int(r["cnt"]) for r in open_rows}
    missed_requisites_count = await count_no_shift_requisites_blocks(
        period_start, period_end
    )
    missed_requisites = await get_no_shift_requisites_blocks(
        period_start, period_end, limit=1000
    )

    pf_today_raw = await get_payfast_conversion_period(1)
    pf_30_raw = await get_payfast_conversion_period(30)
    payfast_today = PayfastConversionPeriod(
        taken=int(pf_today_raw.get("taken") or 0),
        paid=int(pf_today_raw.get("paid") or 0),
        failed=int(pf_today_raw.get("failed") or 0),
        conversion_pct=pf_today_raw.get("conversion_pct"),
        days=1,
    )
    payfast_30d = PayfastConversionPeriod(
        taken=int(pf_30_raw.get("taken") or 0),
        paid=int(pf_30_raw.get("paid") or 0),
        failed=int(pf_30_raw.get("failed") or 0),
        conversion_pct=pf_30_raw.get("conversion_pct"),
        days=30,
    )

    return OwnerSnapshot(
        fetched_at=datetime.now(),
        period_label=period_label,
        period_days=period_days,
        money=money,
        money_week=money_week,
        audience=audience,
        audience_week=audience_week,
        funnel=funnel,
        payfast_today=payfast_today,
        payfast_30d=payfast_30d,
        stale_sell_pending=await count_stale_sell_operator_pending(30),
        stale_completed=[dict(r) for r in stale],
        old_pending_count=await count_old_pending_orders(15),
        terminal_today=await count_terminal_orders_today(),
        open_by_status=open_map,
        shifts=await get_active_operator_shifts(),
        last_paid=await get_last_paid_order(),
        max_open_fiat=await get_max_open_order_fiat(),
        missed_requisites_count=missed_requisites_count,
        missed_requisites=[dict(row) for row in missed_requisites],
    )


async def fetch_missed_requisites(hours: int = 24) -> tuple[int, list[dict[str, Any]]]:
    """Все зафиксированные пропуски за последние часы для команды /misses."""
    hours = max(1, min(int(hours), 24 * 365))
    until = datetime.now(_MSK)
    since = until - timedelta(hours=hours)
    count = await count_no_shift_requisites_blocks(since, until)
    rows = await get_no_shift_requisites_blocks(since, until, limit=2000)
    return count, [dict(row) for row in rows]


async def fetch_users_detail(days: int = 1) -> tuple[AudiencePeriod, list[Any], list[Any], int]:
    aud = await _audience_for_days(days)
    new_users = await get_recent_bot_new_users(days, limit=15)
    top_ips = await get_top_web_ips(days, limit=10)
    web_regs = await count_web_new_registrations(days)
    return aud, list(new_users), list(top_ips), web_regs

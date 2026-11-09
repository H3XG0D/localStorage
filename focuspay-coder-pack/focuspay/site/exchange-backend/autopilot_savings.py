"""Сколько проект оставит себе, если включить автопилот.

Считаем по уже закрытым сделкам. Ставки в базе не меняем:
операторский фонд 30% становится 5% на авто-заявке и 10% на ручной,
кешбэк не растёт, реферала с процентом до 20% в модели поднимаем до 20%.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

WINDOW_DAYS = 7
REFERRAL_CAP = Decimal("20")
CENT = Decimal("0.01")


def _d(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _rub(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _f(value: Decimal) -> float:
    return float(_rub(value))


def fmt_rub(amount: float) -> str:
    return f"{round(float(amount)):,.0f}".replace(",", " ")


def quote_deal(
    *,
    profit: float,
    lane: str,
    pool_percent: float,
    presence_percent: float,
    manual_percent: float,
    user_referral_percent: float | None = None,
    partner_percent: float | None = None,
    cap_percent: float = 20,
) -> dict[str, Any]:
    """Одна сделка. Нулевая прибыль ничего не добавляет."""
    profit_d = _d(profit)
    zero = {
        "counted": False,
        "lane": "manual",
        "operator_save": Decimal("0"),
        "user_extra": Decimal("0"),
        "partner_extra": Decimal("0"),
        "partner_above": Decimal("0"),
        "user_above": Decimal("0"),
    }
    if profit_d <= 0:
        return zero
    auto = lane == "auto"
    new_pct = _d(presence_percent if auto else manual_percent)
    pool = _d(pool_percent)
    cap = _d(cap_percent)
    operator_save = _rub(profit_d * (pool - new_pct) / Decimal("100"))

    def lift(current: float | None) -> tuple[Decimal, Decimal]:
        if current is None:
            return Decimal("0"), Decimal("0")
        pct = _d(current)
        if pct > cap:
            return Decimal("0"), _rub(profit_d * pct / Decimal("100"))
        return _rub(profit_d * (cap - pct) / Decimal("100")), Decimal("0")

    user_extra, user_above = lift(user_referral_percent)
    partner_extra, partner_above = lift(partner_percent)
    return {
        "counted": True,
        "lane": "auto" if auto else "manual",
        "operator_save": operator_save,
        "user_extra": user_extra,
        "partner_extra": partner_extra,
        "partner_above": partner_above,
        "user_above": user_above,
    }


def assemble_savings(
    deals: list[dict[str, Any]],
    *,
    pool_percent: float,
    presence_percent: float,
    manual_percent: float,
    user_referral_percent: float,
    cap_percent: float = 20,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    operator_auto = Decimal("0")
    operator_manual = Decimal("0")
    user_extra = Decimal("0")
    partner_extra = Decimal("0")
    partner_above = Decimal("0")
    user_above = Decimal("0")
    profit = Decimal("0")
    auto_deals = 0
    manual_deals = 0
    partner_above_deals = 0
    user_above_deals = 0
    for deal in deals:
        row = quote_deal(
            profit=float(deal.get("profit") or 0),
            lane=str(deal.get("lane") or "manual"),
            pool_percent=pool_percent,
            presence_percent=presence_percent,
            manual_percent=manual_percent,
            user_referral_percent=deal.get("user_referral_percent"),
            partner_percent=deal.get("partner_percent"),
            cap_percent=cap_percent,
        )
        if not row["counted"]:
            continue
        profit += _d(deal.get("profit"))
        if row["lane"] == "auto":
            auto_deals += 1
            operator_auto += row["operator_save"]
        else:
            manual_deals += 1
            operator_manual += row["operator_save"]
        user_extra += row["user_extra"]
        partner_extra += row["partner_extra"]
        partner_above += row["partner_above"]
        user_above += row["user_above"]
        if row["partner_above"] > 0:
            partner_above_deals += 1
        if row["user_above"] > 0:
            user_above_deals += 1

    operator_save = operator_auto + operator_manual
    net = operator_save - user_extra - partner_extra
    referral_extra = user_extra + partner_extra
    return _report(
        window_days=window_days,
        pool_percent=pool_percent,
        presence_percent=presence_percent,
        manual_percent=manual_percent,
        user_referral_percent=user_referral_percent,
        cap_percent=cap_percent,
        profit=profit,
        auto_deals=auto_deals,
        manual_deals=manual_deals,
        operator_auto=operator_auto,
        operator_manual=operator_manual,
        operator_save=operator_save,
        user_extra=user_extra,
        partner_extra=partner_extra,
        partner_above=partner_above,
        partner_above_deals=partner_above_deals,
        user_above=user_above,
        user_above_deals=user_above_deals,
        referral_extra=referral_extra,
        net=net,
    )


def _report(**parts: Any) -> dict[str, Any]:
    net = parts["net"]
    referral_extra = parts["referral_extra"]
    line = (
        f"Плюс за {parts['window_days']} дней: {fmt_rub(_f(net))} ₽"
        f" · операторы −рефералы до {fmt_rub(float(parts['cap_percent']))}%"
        " · кешбэк не поднимаем"
    )
    lines = [
        {
            "key": "auto",
            "label": f"Автопилот { _pct(parts['presence_percent']) } вместо { _pct(parts['pool_percent']) }",
            "amount_rub": _f(parts["operator_auto"]),
            "hint": f"{parts['auto_deals']} сделок",
        },
        {
            "key": "manual",
            "label": f"Ручные { _pct(parts['manual_percent']) } вместо { _pct(parts['pool_percent']) }",
            "amount_rub": _f(parts["operator_manual"]),
            "hint": f"{parts['manual_deals']} сделок",
        },
        {
            "key": "user_ref",
            "label": "Рефералка клиентов до 20%",
            "amount_rub": _f(-parts["user_extra"]),
            "hint": (
                "уже выше 20%, не поднимаем"
                if parts["user_above_deals"] and parts["user_extra"] == 0
                else f"сейчас {_pct(parts['user_referral_percent'])}"
            ),
        },
        {
            "key": "partner",
            "label": "Партнёры до 20%",
            "amount_rub": _f(-parts["partner_extra"]),
            "hint": "подъём до 20% прибыли",
        },
        {
            "key": "partner_vip",
            "label": "Партнёры выше 20%",
            "amount_rub": 0.0,
            "hint": (
                f"не поднимаем, сейчас {fmt_rub(_f(parts['partner_above']))} ₽"
                if parts["partner_above"] > 0
                else "таких сделок нет"
            ),
        },
        {
            "key": "cashback",
            "label": "Кешбэк",
            "amount_rub": 0.0,
            "hint": "не увеличиваем",
        },
        {
            "key": "net",
            "label": "Плюс проекту",
            "amount_rub": _f(net),
            "hint": f"экономия {fmt_rub(_f(parts['operator_save']))} ₽ минус рефералы {fmt_rub(_f(referral_extra))} ₽",
        },
    ]
    return {
        "window_days": parts["window_days"],
        "deals": parts["auto_deals"] + parts["manual_deals"],
        "profit_rub": _f(parts["profit"]),
        "operator_pool_percent": float(parts["pool_percent"]),
        "presence_percent": float(parts["presence_percent"]),
        "manual_percent": float(parts["manual_percent"]),
        "referral_cap_percent": float(parts["cap_percent"]),
        "user_referral_percent": float(parts["user_referral_percent"]),
        "operator_save_rub": _f(parts["operator_save"]),
        "operator_save_auto_rub": _f(parts["operator_auto"]),
        "operator_save_manual_rub": _f(parts["operator_manual"]),
        "auto_deals": parts["auto_deals"],
        "manual_deals": parts["manual_deals"],
        "user_referral_extra_rub": _f(parts["user_extra"]),
        "partner_extra_rub": _f(parts["partner_extra"]),
        "partner_above_cap_rub": _f(parts["partner_above"]),
        "partner_above_cap_deals": parts["partner_above_deals"],
        "cashback_extra_rub": 0.0,
        "net_rub": _f(net),
        "line": line,
        "lines": lines,
    }


def _pct(value: Any) -> str:
    number = float(value)
    text = f"{number:g}"
    return f"{text}%"


def empty_savings(reason: str = "нет данных") -> dict[str, Any]:
    return {
        "window_days": WINDOW_DAYS,
        "deals": 0,
        "net_rub": None,
        "cashback_extra_rub": 0.0,
        "operator_save_rub": None,
        "user_referral_extra_rub": None,
        "partner_extra_rub": None,
        "line": reason,
        "lines": [],
    }


def _lane(order: dict, ctx) -> str:
    from auto_preview import preview_order_autopay

    try:
        verdict = preview_order_autopay(order, ctx).get("verdict")
    except Exception:
        return "manual"
    return "auto" if verdict == "auto" else "manual"


def _partner_percent(campaign: dict | None, refs: int) -> float | None:
    if not campaign or campaign.get("author_telegram_id") is not None:
        return None
    from partner_tier import global_tier_from_runtime, resolve_tier_settings, tier_info
    from runtime_settings import partner_tier_global

    settings = resolve_tier_settings(global_tier_from_runtime(partner_tier_global()), campaign)
    return float(tier_info(refs, settings)["effective_percent"])


async def build_autopilot_savings(conn) -> dict[str, Any]:
    """Живые закрытые сделки за окно. Ошибка чтения не роняет страницу."""
    import logging

    from economics_snapshot import order_economics
    from operator_payroll_split import fetch_current_payroll_settings
    from runtime_settings import user_referral_pct

    logger = logging.getLogger("autopilot_savings")
    try:
        payroll = await fetch_current_payroll_settings(conn)
        rows = await conn.fetch(
            """
            SELECT o.order_id, o.user_id, o.direction, o.crypto, o.fiat_amount,
                   o.crypto_amount, o.rate, o.cashback_applied_rub, o.card_fee_pct,
                   o.economics_snapshot, o.status, o.created_at,
                   ura.referrer_user_id, pa.promo_code
            FROM orders o
            LEFT JOIN LATERAL (
                SELECT referrer_user_id
                FROM user_referral_attributions
                WHERE user_id = o.user_id
                LIMIT 1
            ) ura ON TRUE
            LEFT JOIN LATERAL (
                SELECT promo_code
                FROM promo_attributions
                WHERE user_id = o.user_id
                LIMIT 1
            ) pa ON TRUE
            WHERE o.status = 'PAID'
              AND COALESCE(o.payout_confirmed_at, o.updated_at) >= now() - ($1 || ' days')::interval
            """,
            str(WINDOW_DAYS),
        )
    except Exception:
        logger.warning("autopilot savings query failed", exc_info=True)
        return empty_savings()

    codes = sorted({str(r["promo_code"]) for r in rows if r["promo_code"]})
    campaigns: dict[str, dict] = {}
    ref_counts: dict[str, int] = {}
    if codes:
        try:
            camp_rows = await conn.fetch(
                """
                SELECT code, partner_commission_percent,
                       partner_tier_base_percent, partner_tier_step_percent,
                       partner_tier_every_n, partner_tier_max_percent,
                       author_telegram_id
                FROM promo_campaigns
                WHERE code = ANY($1::text[]) AND is_active = TRUE
                """,
                codes,
            )
            count_rows = await conn.fetch(
                """
                SELECT promo_code, COUNT(*)::int AS refs
                FROM promo_attributions
                WHERE promo_code = ANY($1::text[])
                GROUP BY promo_code
                """,
                codes,
            )
        except Exception:
            logger.warning("autopilot savings partners failed", exc_info=True)
            camp_rows, count_rows = [], []
        campaigns = {str(r["code"]): dict(r) for r in camp_rows}
        ref_counts = {str(r["promo_code"]): int(r["refs"] or 0) for r in count_rows}

    try:
        from auto_preview import build_preview_context

        ctx = await build_preview_context(conn, (r["user_id"] for r in rows))
    except Exception:
        logger.warning("autopilot savings preview failed", exc_info=True)
        ctx = None

    referral_pct = float(user_referral_pct())
    deals: list[dict[str, Any]] = []
    for row in rows:
        order = dict(row)
        try:
            profit = float(order_economics(order)["service_profit_rub"])
        except Exception:
            logger.debug("order economics failed %s", order.get("order_id"), exc_info=True)
            continue
        lane = _lane(order, ctx) if ctx is not None else "manual"
        user_pct = referral_pct if order.get("referrer_user_id") is not None else None
        code = str(order["promo_code"]) if order.get("promo_code") else ""
        partner_pct = _partner_percent(campaigns.get(code), ref_counts.get(code, 0)) if code else None
        deals.append(
            {
                "profit": profit,
                "lane": lane,
                "user_referral_percent": user_pct,
                "partner_percent": partner_pct,
            }
        )
    return assemble_savings(
        deals,
        pool_percent=float(payroll["operator_pool_percent"]),
        presence_percent=float(payroll["autopilot_presence_percent"]),
        manual_percent=float(payroll["autopilot_manual_percent"]),
        user_referral_percent=referral_pct,
    )

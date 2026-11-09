"""Aggregation helpers for operator shift/time/earnings stats."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from operator_earnings import utc_aware
from payroll_base import (
    order_completed_in_shift,
    order_in_shift,
    stats_from_operator_orders,
)

MOSCOW = ZoneInfo("Europe/Moscow")
WALLET_CRYPTOS = ("usdt", "btc", "trx", "ltc")

# Postgres: calendar day in Europe/Moscow for a timestamptz column.
# Use as f"{MOSCOW_DATE_SQL.format(col='started_at')} BETWEEN $2 AND $3"
MOSCOW_DATE_SQL = "(({col} AT TIME ZONE 'Europe/Moscow')::date)"
MOSCOW_TODAY_SQL = "((now() AT TIME ZONE 'Europe/Moscow')::date)"


def moscow_date_expr(column: str) -> str:
    """SQL expression: Moscow calendar date of a timestamptz column."""
    return MOSCOW_DATE_SQL.format(col=column)


def default_period_range(days: int = 30) -> tuple[date, date]:
    today = datetime.now(MOSCOW).date()
    d_from = today - timedelta(days=days - 1)
    return d_from, today


def shift_duration_hours(started_at, ended_at, now: datetime | None = None) -> float:
    started = utc_aware(started_at)
    if not started:
        return 0.0
    end = utc_aware(ended_at) if ended_at else utc_aware(now or datetime.now(timezone.utc))
    if not end:
        return 0.0
    return max(0.0, (end - started).total_seconds() / 3600.0)


def format_time_moscow(dt) -> str:
    t = utc_aware(dt)
    if not t:
        return "—"
    return t.astimezone(MOSCOW).strftime("%H:%M")


def shift_work_date(started_at) -> date | None:
    t = utc_aware(started_at)
    if not t:
        return None
    return t.astimezone(MOSCOW).date()


def match_orders_to_shift(orders: list, shift) -> list:
    """Заявки смены по времени завершения выплаты (как payroll / оборот / ЗП)."""
    return [
        o
        for o in orders
        if order_completed_in_shift(o, shift["started_at"], shift["ended_at"])
    ]


def match_orders_to_shift_by_created(orders: list, shift) -> list:
    """Заявки по created_at — поток крипты / network_fees по кошельку."""
    return [
        o
        for o in orders
        if order_in_shift(o["created_at"], shift["started_at"], shift["ended_at"])
    ]


def compute_period_stats(
    shifts: list,
    orders: list,
    percent: float,
    accruals: dict,
    *,
    include_earnings: bool = True,
    role_split_earnings_by_order: dict | None = None,
) -> dict:
    shifts_period = len(shifts)
    now = datetime.now(timezone.utc)
    hours_period = sum(
        shift_duration_hours(s["started_at"], s["ended_at"], now) for s in shifts
    )
    work_dates = {d for s in shifts if (d := shift_work_date(s["started_at"]))}

    total_orders = 0
    total_fiat = 0.0
    total_earnings = 0.0

    for s in shifts:
        matched = match_orders_to_shift(orders, s)
        st = stats_from_operator_orders(
            matched, percent, accruals, role_split_earnings_by_order
        )
        total_orders += st["orders_count"]
        total_fiat += st["fiat_total"]
        total_earnings += st["earnings_rub"]

    out = {
        "shifts_period": shifts_period,
        "hours_period": round(hours_period, 1),
        "days_worked_period": len(work_dates),
        "orders_period": total_orders,
        "fiat_period": round(total_fiat, 2),
    }
    if include_earnings:
        out["earnings_period_rub"] = round(total_earnings, 2)
    return out


def build_daily_stats(
    shifts: list,
    orders: list,
    percent: float,
    accruals: dict,
    date_from: date,
    date_to: date,
    *,
    include_earnings: bool = True,
    role_split_earnings_by_order: dict | None = None,
) -> tuple[list[dict], dict]:
    """Returns (daily rows sorted desc, summary dict)."""
    now = datetime.now(timezone.utc)

    shifts_by_date: dict[date, list] = defaultdict(list)
    for s in shifts:
        wd = shift_work_date(s["started_at"])
        if wd and date_from <= wd <= date_to:
            shifts_by_date[wd].append(s)

    days_in_period = (date_to - date_from).days + 1
    daily: list[dict] = []
    total_hours = 0.0
    total_orders = 0
    total_fiat = 0.0
    total_earnings = 0.0
    total_shifts = 0

    for wd in sorted(shifts_by_date.keys(), reverse=True):
        day_shifts = shifts_by_date[wd]
        day_hours = sum(
            shift_duration_hours(s["started_at"], s["ended_at"], now) for s in day_shifts
        )
        shift_times: list[dict] = []
        day_orders = 0
        day_fiat = 0.0
        day_earnings = 0.0

        for s in day_shifts:
            matched = match_orders_to_shift(orders, s)
            st = stats_from_operator_orders(
                matched, percent, accruals, role_split_earnings_by_order
            )
            day_orders += st["orders_count"]
            day_fiat += st["fiat_total"]
            day_earnings += st["earnings_rub"]

            end_dt = s["ended_at"] or now
            shift_times.append(
                {
                    "start": format_time_moscow(s["started_at"]),
                    "end": format_time_moscow(end_dt) if s["ended_at"] else "…",
                }
            )

        total_hours += day_hours
        total_orders += day_orders
        total_fiat += day_fiat
        total_earnings += day_earnings
        total_shifts += len(day_shifts)

        row: dict = {
            "date": wd.isoformat(),
            "shifts_count": len(day_shifts),
            "hours": round(day_hours, 2),
            "shift_times": shift_times,
            "orders": day_orders,
            "fiat": round(day_fiat, 2),
        }
        if include_earnings:
            row["earnings_rub"] = round(day_earnings, 2)
        daily.append(row)

    days_worked = len(shifts_by_date)
    work_frequency_pct = (
        round(days_worked / days_in_period * 100, 1) if days_in_period > 0 else 0.0
    )
    avg_hours = round(total_hours / days_worked, 1) if days_worked > 0 else 0.0

    summary: dict = {
        "days_in_period": days_in_period,
        "days_worked": days_worked,
        "work_frequency_pct": work_frequency_pct,
        "total_hours": round(total_hours, 1),
        "avg_hours_per_work_day": avg_hours,
        "shifts_count": total_shifts,
        "orders": total_orders,
        "fiat": round(total_fiat, 2),
    }
    if include_earnings:
        summary["earnings_rub"] = round(total_earnings, 2)

    return daily, summary


def compute_balance_summary(raw_bals: list, matched_orders: list) -> list[dict]:
    """Балансы смены + потоки по ордерам (для network_fees)."""
    flow: dict[str, dict[str, float]] = {}
    for o in matched_orders:
        base = (o.get("crypto") or "").split("_")[0].lower()
        if not base:
            continue
        flow.setdefault(base, {"sent": 0.0, "recv": 0.0})
        amt = float(o.get("crypto_amount") or 0)
        if (o.get("direction") or "").lower() == "buy":
            flow[base]["sent"] += amt
        else:
            flow[base]["recv"] += amt

    balance_summary = []
    for b in raw_bals:
        c = b["crypto"]
        bs = float(b["balance_start"]) if b["balance_start"] is not None else None
        be = float(b["balance_end"]) if b["balance_end"] is not None else None
        sent = flow.get(c, {}).get("sent", 0.0)
        recv = flow.get(c, {}).get("recv", 0.0)
        expected = round(bs - sent + recv, 8) if bs is not None else None
        fees = (
            round(expected - be, 8)
            if expected is not None and be is not None
            else None
        )
        balance_summary.append(
            {
                "crypto": c,
                "balance_start": bs,
                "balance_end": be,
                "sent_in_buy": round(sent, 8),
                "recv_in_sell": round(recv, 8),
                "expected_end": expected,
                "network_fees": fees,
            }
        )
    return balance_summary


def build_daily_balance_stats(
    shifts: list,
    date_from: date,
    date_to: date,
) -> list[dict]:
    """Сводка введённых балансов по дням (дата = начало смены, Москва)."""
    now = datetime.now(timezone.utc)
    min_dt = datetime.min.replace(tzinfo=timezone.utc)

    ordered = sorted(
        shifts,
        key=lambda s: utc_aware(s["started_at"]) or min_dt,
    )
    prev_end: dict[str, float] = {}
    enriched_shifts: list[dict] = []

    for s in ordered:
        summary = s.get("balance_summary") or []
        if not summary:
            enriched_shifts.append({**s, "balance_summary": []})
            continue

        new_summary = []
        for row in summary:
            c = row["crypto"]
            bs = row.get("balance_start")
            be = row.get("balance_end")
            new_row = dict(row)
            if bs is not None and c in prev_end:
                new_row["gap_from_prev"] = round(bs - prev_end[c], 8)
            new_summary.append(new_row)
            if be is not None:
                prev_end[c] = be
            elif bs is not None:
                prev_end[c] = bs

        enriched_shifts.append({**s, "balance_summary": new_summary})

    by_date: dict[date, list] = defaultdict(list)
    for s in enriched_shifts:
        wd = shift_work_date(s["started_at"])
        if wd and date_from <= wd <= date_to:
            by_date[wd].append(s)

    last_end_by_crypto: dict[str, float] = {}
    daily_by_date: dict[date, dict] = {}

    for wd in sorted(by_date.keys()):
        day_shifts = sorted(
            by_date[wd],
            key=lambda s: utc_aware(s["started_at"]) or min_dt,
        )

        summary_by_crypto: dict[str, dict] = {}
        for crypto in WALLET_CRYPTOS:
            starts: list[tuple] = []
            ends: list[tuple] = []
            fees_sum = 0.0
            has_fees = False
            sent_sum = 0.0
            recv_sum = 0.0
            gap_in = 0.0
            gap_out = 0.0

            for sh in day_shifts:
                for b in sh.get("balance_summary") or []:
                    if b.get("crypto") != crypto:
                        continue
                    if b.get("balance_start") is not None:
                        starts.append((utc_aware(sh["started_at"]), b["balance_start"]))
                    if b.get("balance_end") is not None:
                        ends.append(
                            (utc_aware(sh["ended_at"]) or now, b["balance_end"])
                        )
                    nf = b.get("network_fees")
                    if nf is not None:
                        fees_sum += nf
                        has_fees = True
                    sent_sum += float(b.get("sent_in_buy") or 0)
                    recv_sum += float(b.get("recv_in_sell") or 0)
                    gap = b.get("gap_from_prev")
                    if gap is not None:
                        if gap > 0:
                            gap_in += gap
                        elif gap < 0:
                            gap_out += abs(gap)

            day_start = sorted(starts, key=lambda x: x[0])[0][1] if starts else None
            day_end = sorted(ends, key=lambda x: x[0])[-1][1] if ends else None
            day_delta = (
                round(day_end - day_start, 8)
                if day_start is not None and day_end is not None
                else None
            )
            vs_prev = (
                round(day_end - last_end_by_crypto[crypto], 8)
                if day_end is not None and crypto in last_end_by_crypto
                else None
            )

            if day_start is not None or day_end is not None:
                summary_by_crypto[crypto] = {
                    "crypto": crypto,
                    "balance_start": day_start,
                    "balance_end": day_end,
                    "day_delta": day_delta,
                    "vs_prev_day_end": vs_prev,
                    "sent_in_buy": round(sent_sum, 8) if sent_sum else 0.0,
                    "recv_in_sell": round(recv_sum, 8) if recv_sum else 0.0,
                    "gap_in": round(gap_in, 8) if gap_in else 0.0,
                    "gap_out": round(gap_out, 8) if gap_out else 0.0,
                    "total_network_fees": round(fees_sum, 8) if has_fees else None,
                }

            if day_end is not None:
                last_end_by_crypto[crypto] = day_end

        shift_items = []
        for sh in day_shifts:
            end_dt = sh.get("ended_at") or now
            shift_items.append(
                {
                    "shift_id": sh["id"],
                    "start_time": format_time_moscow(sh["started_at"]),
                    "end_time": format_time_moscow(end_dt)
                    if sh.get("ended_at")
                    else "…",
                    "balances": sh.get("balance_summary") or [],
                }
            )

        daily_by_date[wd] = {
            "date": wd.isoformat(),
            "shifts_count": len(day_shifts),
            "shifts": shift_items,
            "summary": list(summary_by_crypto.values()),
        }

    return [daily_by_date[wd] for wd in sorted(daily_by_date.keys(), reverse=True)]


# ---------------------------------------------------------------------------
# SLA metrics
# ---------------------------------------------------------------------------

# SLA thresholds
SLA_CLAIM_MINUTES = 20  # Максимум 20 минут на взятие заявки
SLA_COMPLETE_MINUTES = 60  # Максимум 60 минут на завершение после взятия


def _minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    """Разница в минутах между двумя timestamp."""
    if not start or not end:
        return None
    delta = end - start
    return round(delta.total_seconds() / 60.0, 2)


def _percentile(values: list[float], p: int) -> float:
    """Вычислить p-й процентиль из списка значений."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    index = int(len(sorted_vals) * p / 100.0)
    if index >= len(sorted_vals):
        index = len(sorted_vals) - 1
    return round(sorted_vals[index], 2)


async def compute_operator_sla(conn, operator_id: int, days: int = 30) -> dict:
    """Рассчитать SLA метрики для оператора за последние N дней.

    Метрики:
    - time_to_claim: время от created_at до claimed_at
    - time_to_complete: время от claimed_at до operator_completed_at
    - SLA breach count: сколько заявок превысили пороги
    - Средние значения и P95
    """

    # Получить заявки оператора за период
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = await conn.fetch(
        """
        SELECT
            order_id,
            created_at,
            claimed_at,
            operator_completed_at,
            status,
            direction
        FROM orders
        WHERE operator_id = $1
          AND created_at > $2
          AND status IN ('COMPLETED', 'PAID', 'CANCELED', 'FAILED')
        ORDER BY created_at DESC
        """,
        operator_id,
        cutoff,
    )

    if not rows:
        return {
            "operator_id": operator_id,
            "period_days": days,
            "total_orders": 0,
            "time_to_claim": None,
            "time_to_complete": None,
            "sla_breaches": {"claim": 0, "complete": 0, "total": 0},
        }

    # Вычислить метрики по каждой заявке
    claim_times = []
    complete_times = []
    claim_breaches = 0
    complete_breaches = 0

    for row in rows:
        # Time to claim
        if row["claimed_at"]:
            ttc = _minutes_between(row["created_at"], row["claimed_at"])
            if ttc is not None and ttc >= 0:
                claim_times.append(ttc)
                if ttc > SLA_CLAIM_MINUTES:
                    claim_breaches += 1

        # Time to complete (только для завершённых)
        if row["operator_completed_at"] and row["claimed_at"]:
            if row["status"] in ("COMPLETED", "PAID"):
                ttcomplete = _minutes_between(row["claimed_at"], row["operator_completed_at"])
                if ttcomplete is not None and ttcomplete >= 0:
                    complete_times.append(ttcomplete)
                    if ttcomplete > SLA_COMPLETE_MINUTES:
                        complete_breaches += 1

    # Агрегированные метрики
    return {
        "operator_id": operator_id,
        "period_days": days,
        "total_orders": len(rows),
        "orders_with_claim_time": len(claim_times),
        "orders_with_complete_time": len(complete_times),
        "time_to_claim": {
            "avg_minutes": round(sum(claim_times) / len(claim_times), 2) if claim_times else 0.0,
            "p50_minutes": _percentile(claim_times, 50) if claim_times else 0.0,
            "p95_minutes": _percentile(claim_times, 95) if claim_times else 0.0,
            "max_minutes": round(max(claim_times), 2) if claim_times else 0.0,
            "sla_threshold_minutes": SLA_CLAIM_MINUTES,
        },
        "time_to_complete": {
            "avg_minutes": round(sum(complete_times) / len(complete_times), 2) if complete_times else 0.0,
            "p50_minutes": _percentile(complete_times, 50) if complete_times else 0.0,
            "p95_minutes": _percentile(complete_times, 95) if complete_times else 0.0,
            "max_minutes": round(max(complete_times), 2) if complete_times else 0.0,
            "sla_threshold_minutes": SLA_COMPLETE_MINUTES,
        },
        "sla_breaches": {
            "claim": claim_breaches,
            "complete": complete_breaches,
            "total": claim_breaches + complete_breaches,
            "claim_breach_rate_pct": round(claim_breaches / len(claim_times) * 100, 2) if claim_times else 0.0,
            "complete_breach_rate_pct": round(complete_breaches / len(complete_times) * 100, 2) if complete_times else 0.0,
        },
    }


async def compute_all_operators_sla(conn, days: int = 30) -> list[dict]:
    """Рассчитать SLA метрики для всех активных операторов.

    Возвращает список операторов с их SLA метриками, отсортированный по breach rate.
    """

    # Получить всех активных операторов
    operator_rows = await conn.fetch(
        """
        SELECT id, username, display_name
        FROM operator_accounts
        WHERE is_active = TRUE
        ORDER BY username
        """
    )

    results = []

    for op_row in operator_rows:
        sla = await compute_operator_sla(conn, op_row["id"], days)
        sla["username"] = op_row["username"]
        sla["display_name"] = op_row.get("display_name")
        results.append(sla)

    # Сортировка по breach rate (worst first)
    results.sort(
        key=lambda x: x["sla_breaches"]["total"],
        reverse=True,
    )

    return results

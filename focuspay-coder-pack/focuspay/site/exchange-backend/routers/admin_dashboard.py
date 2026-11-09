"""Live-снимок для Dashboard: кошелёк, долг, операторы в работе."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_admin, get_current_finance_viewer
from db import get_pool
from finance_access import can_view_finance_admin, shift_kpi_public_fields
from operator_balance_fiat import enrich_balance_summary, market_prices_rub
from operator_payroll_pool import pool_balance
from operator_shift_wallets import operator_wallet_snapshot
from operator_stats import default_period_range, shift_work_date
from payroll_base import fetch_in_work_by_operator, stats_for_operator_shift_conn
from routers.admin_operators import _operator_earnings_map
from routers.operator import _compute_network_fees

router = APIRouter()
logger = logging.getLogger("admin_dashboard")

_NETWORK_FEE_RUB_THRESHOLD = 50.0
_WALLET_MATCH_EPS = 1.0
_STALE_SHIFT_HOURS = 12
_MISSING_END_HOURS = 8
_SUSPICIOUS_FLOW_USDT = 50.0
_SUSPICIOUS_FEE_EPS = 0.05


def _fiat_from_crypto_fee(crypto: str, amount: float, market: dict[str, float]) -> float:
    c = (crypto or "").split("_")[0].lower()
    rub_price = float(market.get(c) or 0)
    return abs(amount) * rub_price if rub_price > 0 else 0.0


def _signed_crypto_to_usdt(crypto: str, amount: float, market: dict[str, float]) -> float:
    """Конвертация с сохранением знака → USDT."""
    c = (crypto or "").split("_")[0].lower()
    amt = float(amount or 0)
    if c == "usdt":
        return amt
    usdt_rub = float(market.get("usdt") or 0)
    rub_price = float(market.get(c) or 0)
    if usdt_rub <= 0 or rub_price <= 0:
        return 0.0
    return amt * rub_price / usdt_rub


def _crypto_to_usdt(crypto: str, amount: float, market: dict[str, float]) -> float:
    return abs(_signed_crypto_to_usdt(crypto, amount, market))


def _iter_dates(d_from: date, d_to: date):
    cur = d_from
    while cur <= d_to:
        yield cur
        cur += timedelta(days=1)


def _adjust_row_for_issuance(row: dict, usdt_issued: float) -> dict:
    """
    Ожидаемый конец с учётом выдачи USDT:
      expected = start − buy + sell + usdt_issued
      fees = expected − end
    """
    r = dict(row)
    crypto = (r.get("crypto") or "").split("_")[0].lower()
    fees = r.get("network_fees")
    expected = r.get("expected_end")
    if crypto == "usdt" and usdt_issued:
        if expected is not None:
            r["expected_end"] = round(float(expected) + usdt_issued, 8)
        if fees is not None:
            r["network_fees"] = round(float(fees) + usdt_issued, 8)
        r["usdt_issued"] = round(usdt_issued, 8)
    else:
        r["usdt_issued"] = 0.0
    return r


def _asset_row(crypto: str, start: float, end: float, market: dict[str, float]) -> dict:
    """Одна монета: было / стало / дельта в нативе + $ + ₽."""
    from operator_balance_fiat import crypto_to_fiat

    start_rub, start_usd = crypto_to_fiat(crypto, start, market)
    end_rub, end_usd = crypto_to_fiat(crypto, end, market)
    delta = round(end - start, 8)
    delta_usd = round(end_usd - start_usd, 2)
    delta_rub = round(end_rub - start_rub, 2)
    return {
        "crypto": crypto.upper(),
        "start": round(start, 8),
        "end": round(end, 8),
        "delta": delta,
        "start_usd": start_usd,
        "end_usd": end_usd,
        "delta_usd": delta_usd,
        "start_rub": start_rub,
        "end_rub": end_rub,
        "delta_rub": delta_rub,
    }


def _merge_day_assets(first_assets: list[dict], last_assets: list[dict], market: dict[str, float]) -> list[dict]:
    """За день: старт первой смены × конец последней — по каждой монете."""
    by_c: dict[str, dict] = {}
    for a in first_assets:
        c = (a.get("crypto") or "").upper()
        by_c[c] = {"crypto": c, "start": float(a["start"]), "end": float(a["end"])}
    for a in last_assets:
        c = (a.get("crypto") or "").upper()
        if c in by_c:
            by_c[c]["end"] = float(a["end"])
        else:
            by_c[c] = {"crypto": c, "start": 0.0, "end": float(a["end"])}
    rows = [_asset_row(v["crypto"].lower(), v["start"], v["end"], market) for v in by_c.values()]
    rows.sort(key=lambda r: abs(r["delta_usd"]), reverse=True)
    return rows


async def _build_wallet_daily(conn, d_from: date, d_to: date) -> dict:
    """
    Движение всего кошелька за смену (BTC, LTC, USDT, …):

      было (начало) → стало (конец) по каждой монете
      дельта $ = сумма (конец − начало) в USDT-эквиваленте
      плюс = к концу портфель в $ стал БОЛЬШЕ

    Смысл потока: выплачиваем BTC/LTC, ручные заводят USDT (~каждые $500).
    """
    market = await market_prices_rub()
    usdt_rub = float(market.get("usdt") or 0)

    pad_from = datetime.combine(d_from - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    pad_to = datetime.combine(d_to + timedelta(days=1), datetime.max.time(), tzinfo=timezone.utc)

    bal_rows = await conn.fetch(
        """
        SELECT s.id AS shift_id, s.operator_id, s.started_at, s.ended_at,
               oa.username, oa.display_name,
               LOWER(SPLIT_PART(b.crypto, '_', 1)) AS crypto,
               b.balance_start, b.balance_end
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id
        JOIN operator_shift_balances b ON b.shift_id = s.id
        WHERE s.ended_at IS NOT NULL
          AND s.started_at >= $1
          AND s.started_at <= $2
          AND b.balance_start IS NOT NULL
          AND b.balance_end IS NOT NULL
        ORDER BY s.started_at, b.crypto
        """,
        pad_from,
        pad_to,
    )

    # group balances by shift
    shifts_map: dict[int, dict] = {}
    for r in bal_rows:
        sid = int(r["shift_id"])
        if sid not in shifts_map:
            started = r["started_at"]
            ended = r["ended_at"]
            shifts_map[sid] = {
                "shift_id": sid,
                "operator_id": int(r["operator_id"]),
                "username": r["username"],
                "display_name": r["display_name"],
                "started_at": started,
                "ended_at": ended,
                "raw": [],
            }
        shifts_map[sid]["raw"].append(
            (str(r["crypto"] or "").lower(), float(r["balance_start"]), float(r["balance_end"]))
        )

    by_day: dict[str, dict] = {}
    for d in _iter_dates(d_from, d_to):
        by_day[d.isoformat()] = {"date": d.isoformat(), "shifts": []}

    # preserve start order
    for sid in sorted(shifts_map.keys(), key=lambda k: shifts_map[k]["started_at"]):
        s = shifts_map[sid]
        wd = shift_work_date(s["started_at"])
        if not wd or wd < d_from or wd > d_to:
            continue

        assets = [_asset_row(c, st, en, market) for c, st, en in s["raw"]]
        if not assets:
            continue
        assets.sort(key=lambda a: abs(a["delta_usd"]), reverse=True)

        start_usd = round(sum(a["start_usd"] for a in assets), 2)
        end_usd = round(sum(a["end_usd"] for a in assets), 2)
        delta_usd = round(end_usd - start_usd, 2)
        start_rub = round(sum(a["start_rub"] for a in assets), 2)
        end_rub = round(sum(a["end_rub"] for a in assets), 2)
        delta_rub = round(end_rub - start_rub, 2)

        started = s["started_at"]
        ended = s["ended_at"]
        by_day[wd.isoformat()]["shifts"].append({
            "id": s["operator_id"],
            "name": s["display_name"] or s["username"],
            "shift_id": sid,
            "started_at": started.isoformat() if hasattr(started, "isoformat") else str(started),
            "ended_at": ended.isoformat() if ended and hasattr(ended, "isoformat") else str(ended),
            "assets": assets,
            "total_start_usd": start_usd,
            "total_end_usd": end_usd,
            "delta_usd": delta_usd,
            "total_start_rub": start_rub,
            "total_end_rub": end_rub,
            "delta_rub": delta_rub,
            # aliases (портфель в $)
            "usdt_start": start_usd,
            "usdt_end": end_usd,
            "usdt_start_rub": start_rub,
            "usdt_end_rub": end_rub,
            "delta_usdt": delta_usd,
            "discrepancy_usd": delta_usd,
            "discrepancy_rub": delta_rub,
        })

    chart = []
    total_delta = 0.0
    total_delta_rub = 0.0
    total_shifts = 0

    for key in sorted(by_day.keys()):
        shifts = by_day[key]["shifts"]
        if not shifts:
            chart.append({
                "date": key,
                "assets": [],
                "total_start_usd": None,
                "total_end_usd": None,
                "total_start_rub": None,
                "total_end_rub": None,
                "delta_usd": 0.0,
                "delta_rub": 0.0,
                "usdt_start": None,
                "usdt_end": None,
                "usdt_start_rub": None,
                "usdt_end_rub": None,
                "delta_usdt": 0.0,
                "discrepancy_usd": 0.0,
                "discrepancy_rub": 0.0,
                "shifts_count": 0,
                "operators": [],
            })
            continue

        first = shifts[0]
        last = shifts[-1]
        day_assets = _merge_day_assets(first["assets"], last["assets"], market)
        day_start = round(sum(a["start_usd"] for a in day_assets), 2)
        day_end = round(sum(a["end_usd"] for a in day_assets), 2)
        day_delta = round(day_end - day_start, 2)
        day_start_rub = round(sum(a["start_rub"] for a in day_assets), 2)
        day_end_rub = round(sum(a["end_rub"] for a in day_assets), 2)
        day_delta_rub = round(day_end_rub - day_start_rub, 2)

        chart.append({
            "date": key,
            "assets": day_assets,
            "total_start_usd": day_start,
            "total_end_usd": day_end,
            "total_start_rub": day_start_rub,
            "total_end_rub": day_end_rub,
            "delta_usd": day_delta,
            "delta_rub": day_delta_rub,
            "usdt_start": day_start,
            "usdt_end": day_end,
            "usdt_start_rub": day_start_rub,
            "usdt_end_rub": day_end_rub,
            "delta_usdt": day_delta,
            "discrepancy_usd": day_delta,
            "discrepancy_rub": day_delta_rub,
            "shifts_count": len(shifts),
            "operators": shifts,
        })
        total_delta += day_delta
        total_delta_rub += day_delta_rub
        total_shifts += len(shifts)

    return {
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "usdt_rub_rate": round(usdt_rub, 2),
        "chart": chart,
        "summary": {
            "delta_usd": round(total_delta, 2),
            "delta_usdt": round(total_delta, 2),
            "delta_rub": round(total_delta_rub, 2),
            "discrepancy_usd": round(total_delta, 2),
            "discrepancy_rub": round(total_delta_rub, 2),
            "shifts_count": total_shifts,
        },
    }


def _shift_hours_open(started_at) -> float:
    if not isinstance(started_at, datetime):
        return 0.0
    started = started_at.replace(tzinfo=timezone.utc) if started_at.tzinfo is None else started_at
    return (datetime.now(timezone.utc) - started).total_seconds() / 3600


async def _build_live(conn, can_finance: bool) -> dict:
    market = await market_prices_rub()
    usdt_rub = float(market.get("usdt") or 0)

    shift_rows = await conn.fetch(
        """
        SELECT s.id AS shift_id, s.operator_id, s.started_at,
               oa.username, oa.display_name, oa.percent
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id
        WHERE s.ended_at IS NULL
        ORDER BY s.started_at
        """
    )

    in_work_by_op = await fetch_in_work_by_operator(conn)

    all_ops = await conn.fetch(
        """
        SELECT id, username, display_name,
               EXISTS (
                   SELECT 1 FROM operator_shifts os
                   WHERE os.operator_id = operator_accounts.id AND os.ended_at IS NULL
               ) AS on_shift
        FROM operator_accounts
        WHERE is_active
        ORDER BY username
        """
    )

    snapshots: list[dict] = []
    discrepancies: list[dict] = []
    operators_live: list[dict] = []
    active_shifts: list[dict] = []
    shift_meta_by_op: dict[int, dict] = {}

    for s in shift_rows:
        op_id = int(s["operator_id"])
        shift_id = int(s["shift_id"])
        name = s["display_name"] or s["username"]
        started = s["started_at"]
        started_iso = started.isoformat() if isinstance(started, datetime) else str(started)

        snap = await operator_wallet_snapshot(conn, op_id)
        bal_summary = await _compute_network_fees(
            conn, shift_id, op_id, started, None
        )
        bal_summary = enrich_balance_summary(bal_summary, market)

        if not snap:
            discrepancies.append({
                "type": "missing_snapshot",
                "message": f"{name}: на смене, но балансы кошелька не заполнены",
                "operator_id": op_id,
            })
        else:
            snapshots.append({
                "operator_id": op_id,
                "name": name,
                "total_rub": float(snap.get("total_rub") or 0),
                "total_usd": float(snap.get("total_usd") or 0),
                "shift_id": shift_id,
            })

        hours_open = _shift_hours_open(started)
        if hours_open > _STALE_SHIFT_HOURS:
            discrepancies.append({
                "type": "stale_snapshot",
                "message": f"{name}: смена открыта {int(hours_open)} ч без закрытия",
                "operator_id": op_id,
            })

        has_any_end = any(
            row.get("balance_end") is not None for row in bal_summary
        )
        if hours_open > _MISSING_END_HOURS and not has_any_end and bal_summary:
            discrepancies.append({
                "type": "missing_end",
                "message": (
                    f"{name}: смена {int(hours_open)} ч — конец смены ещё не введён"
                ),
                "operator_id": op_id,
            })

        for row in bal_summary:
            fees = row.get("network_fees")
            if fees is not None and abs(float(fees)) > 0.00000001:
                fee_rub = _fiat_from_crypto_fee(row.get("crypto", ""), float(fees), market)
                if fee_rub >= _NETWORK_FEE_RUB_THRESHOLD:
                    discrepancies.append({
                        "type": "network_fees",
                        "message": (
                            f"{name}: неизвестное расхождение по {str(row.get('crypto', '')).upper()} "
                            f"({float(fees):.6f}, ~{fee_rub:.0f} ₽)"
                        ),
                        "operator_id": op_id,
                        "crypto": row.get("crypto"),
                        "delta_rub": round(fee_rub, 2),
                    })

        shift_stats = await stats_for_operator_shift_conn(
            conn, op_id, started, None, float(s.get("percent") or 0)
        )
        shift_meta_by_op[op_id] = {
            "shift_id": shift_id,
            "started_at": started_iso,
            "balance_summary": bal_summary,
            "wallet_snapshot": snap,
            "shift_stats": shift_stats,
        }

        active_shifts.append({
            "operator_id": op_id,
            "operator_name": name,
            "shift_id": shift_id,
            "started_at": started_iso,
            "balance_summary": bal_summary,
            "wallet_snapshot": snap,
        })

    wallet_total_rub = 0.0
    wallet_total_usd = 0.0
    if snapshots:
        rub_vals = [x["total_rub"] for x in snapshots]
        usd_vals = [x["total_usd"] for x in snapshots]
        if len(snapshots) > 1:
            ref_rub = rub_vals[0]
            ref_usd = usd_vals[0]
            for snap in snapshots[1:]:
                if abs(snap["total_rub"] - ref_rub) > _WALLET_MATCH_EPS:
                    discrepancies.append({
                        "type": "operator_mismatch",
                        "message": (
                            f"Кошелёк: {snapshots[0]['name']} ({ref_rub:.0f} ₽) ≠ "
                            f"{snap['name']} ({snap['total_rub']:.0f} ₽)"
                        ),
                        "operator_id": snap["operator_id"],
                        "delta_rub": round(abs(snap["total_rub"] - ref_rub), 2),
                    })
                if abs(snap["total_usd"] - ref_usd) > 0.5:
                    discrepancies.append({
                        "type": "operator_mismatch",
                        "message": (
                            f"Кошелёк USD: {snapshots[0]['name']} (${ref_usd:.2f}) ≠ "
                            f"{snap['name']} (${snap['total_usd']:.2f})"
                        ),
                        "operator_id": snap["operator_id"],
                    })
        wallet_total_rub = round(rub_vals[0], 2)
        wallet_total_usd = round(usd_vals[0], 2)

    snap_by_op = {x["operator_id"]: x for x in snapshots}

    for op in all_ops:
        op_id = int(op["id"])
        iw = in_work_by_op.get(op_id, {"orders_in_work": 0, "in_work_rub": 0.0})
        in_work_rub = iw["in_work_rub"]
        in_work_usd = round(in_work_rub / usdt_rub, 2) if usdt_rub > 0 else 0.0
        snap = snap_by_op.get(op_id)
        on_shift = bool(op["on_shift"])
        meta = shift_meta_by_op.get(op_id)
        if not on_shift and iw["orders_in_work"] == 0 and not snap:
            continue
        card = {
            "id": op_id,
            "name": op["display_name"] or op["username"],
            "on_shift": on_shift,
            "orders_in_work": iw["orders_in_work"],
            "in_work_rub": in_work_rub,
            "in_work_usd": in_work_usd,
            "wallet_rub": snap["total_rub"] if snap else None,
            "wallet_usd": snap["total_usd"] if snap else None,
            "shift_id": meta["shift_id"] if meta else None,
            "shift_started_at": meta["started_at"] if meta else None,
            "balance_summary": meta["balance_summary"] if meta else [],
            "wallet_snapshot": meta["wallet_snapshot"] if meta else None,
        }
        card.update(
            shift_kpi_public_fields(
                meta.get("shift_stats") if meta else None,
                can_finance,
            )
        )
        operators_live.append(card)

    operators_live.sort(
        key=lambda x: (not x["on_shift"], -x["orders_in_work"], x["name"] or ""),
    )

    try:
        from hot_wallet_runway import build_hot_wallet_runway

        hot_wallet = await build_hot_wallet_runway(conn)
    except Exception:
        logger.warning("hot wallet runway unavailable", exc_info=True)
        from hot_wallet_runway import empty_runway

        hot_wallet = empty_runway()

    try:
        from autopilot_savings import build_autopilot_savings

        autopilot_savings = await build_autopilot_savings(conn)
    except Exception:
        logger.warning("autopilot savings unavailable", exc_info=True)
        from autopilot_savings import empty_savings

        autopilot_savings = empty_savings()

    out: dict = {
        "can_view_finance": can_finance,
        "wallet": {
            "total_rub": wallet_total_rub,
            "total_usd": wallet_total_usd,
            "reported_by": len(snapshots),
            "discrepancies": discrepancies,
            "active_shifts": active_shifts,
        },
        "hot_wallet": hot_wallet,
        "autopilot_savings": autopilot_savings,
        "operators": operators_live,
    }

    if can_finance:
        pool = await pool_balance(conn)
        earnings = await _operator_earnings_map(conn)
        op_debt = []
        for op_id, e in earnings.items():
            accrued = float(e.get("earnings_accrued_rub") or 0)
            paid = float(e.get("earnings_paid_rub") or 0)
            debt = round(accrued - paid, 2)
            if debt <= 0.009 and accrued <= 0.009:
                continue
            op_row = await conn.fetchrow(
                "SELECT username, display_name FROM operator_accounts WHERE id = $1",
                op_id,
            )
            if not op_row:
                continue
            op_debt.append({
                "id": op_id,
                "name": op_row["display_name"] or op_row["username"],
                "accrued_rub": round(accrued, 2),
                "paid_rub": round(paid, 2),
                "debt_rub": debt,
            })
        op_debt.sort(key=lambda x: -x["debt_rub"])
        out["payroll"] = {
            "pool_total_rub": pool["total_rub"],
            "pool_available_rub": pool["available_rub"],
            "pending_requests_count": pool["pending_requests_count"],
            "operators": op_debt,
        }

    return out


@router.get("/dashboard/live")
async def get_dashboard_live(admin=Depends(get_current_admin)):
    can_finance = can_view_finance_admin(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _build_live(conn, can_finance)


@router.get("/dashboard/owner")
async def get_dashboard_owner(
    period: str = Query(
        "today",
        description="today|yesterday|week|month|year (Europe/Moscow; week = Monday→today; month = last 30 days)",
    ),
    _admin=Depends(get_current_finance_viewer),
):
    """Owner business KPIs with previous-period deltas. Not turnover-as-income."""
    from owner_dashboard_metrics import PERIOD_KEYS, build_owner_dashboard

    key = (period or "today").strip().lower()
    if key not in PERIOD_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period. Allowed: {', '.join(PERIOD_KEYS)}",
        )
    return await build_owner_dashboard(key)


@router.get("/dashboard/wallet-daily")
async def get_dashboard_wallet_daily(
    admin=Depends(get_current_admin),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    """Расхождения кошелька (network_fees) по дням закрытых смен."""
    _ = admin
    if date_from and date_to:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    else:
        d_from, d_to = default_period_range(30)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _build_wallet_daily(conn, d_from, d_to)


# ---------------------------------------------------------------------------
# Volume cohorts: клиенты с объёмом ≥ 50 / 100 / 200 тыс ₽
# ---------------------------------------------------------------------------

_VOLUME_THRESHOLDS = (50_000, 100_000, 200_000)
_VOLUME_MODES = frozenset({"lifetime", "new_day", "new_week", "week_volume"})


def _msk_today() -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _bucket_payload(ge_50: int, ge_100: int, ge_200: int) -> list[dict]:
    return [
        {"threshold": 50_000, "label": "≥50к", "count": int(ge_50)},
        {"threshold": 100_000, "label": "≥100к", "count": int(ge_100)},
        {"threshold": 200_000, "label": "≥200к", "count": int(ge_200)},
    ]


async def _count_lifetime_buckets(conn) -> tuple[int, int, int]:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE vol >= 50000)::int AS ge_50k,
            COUNT(*) FILTER (WHERE vol >= 100000)::int AS ge_100k,
            COUNT(*) FILTER (WHERE vol >= 200000)::int AS ge_200k
        FROM (
            SELECT user_id, COALESCE(SUM(fiat_amount), 0) AS vol
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
            GROUP BY user_id
        ) t
        """
    )
    return int(row["ge_50k"]), int(row["ge_100k"]), int(row["ge_200k"])


async def _count_new_crossers(conn, start_d: date, end_d: date) -> tuple[int, int, int]:
    """Сколько клиентов впервые пересекли порог в [start_d, end_d] (даты МСК)."""
    row = await conn.fetchrow(
        """
        WITH paid AS (
            SELECT user_id, id, fiat_amount,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date AS d,
                   SUM(fiat_amount) OVER (
                       PARTITION BY user_id ORDER BY created_at, id
                   ) AS cum
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
        ),
        crossed AS (
            SELECT user_id,
                   MIN(d) FILTER (WHERE cum >= 50000) AS at_50,
                   MIN(d) FILTER (WHERE cum >= 100000) AS at_100,
                   MIN(d) FILTER (WHERE cum >= 200000) AS at_200
            FROM paid
            GROUP BY user_id
        )
        SELECT
            COUNT(*) FILTER (WHERE at_50 BETWEEN $1 AND $2)::int AS ge_50k,
            COUNT(*) FILTER (WHERE at_100 BETWEEN $1 AND $2)::int AS ge_100k,
            COUNT(*) FILTER (WHERE at_200 BETWEEN $1 AND $2)::int AS ge_200k
        FROM crossed
        """,
        start_d,
        end_d,
    )
    return int(row["ge_50k"]), int(row["ge_100k"]), int(row["ge_200k"])


async def _chart_new_crossers(conn, d_from: date, d_to: date) -> list[dict]:
    """По дням: сколько клиентов впервые пересекли 50/100/200к (накопительный объём)."""
    rows = await conn.fetch(
        """
        WITH paid AS (
            SELECT user_id, id, fiat_amount,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date AS d,
                   SUM(fiat_amount) OVER (
                       PARTITION BY user_id ORDER BY created_at, id
                   ) AS cum
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
        ),
        crossed AS (
            SELECT user_id,
                   MIN(d) FILTER (WHERE cum >= 50000) AS at_50,
                   MIN(d) FILTER (WHERE cum >= 100000) AS at_100,
                   MIN(d) FILTER (WHERE cum >= 200000) AS at_200
            FROM paid
            GROUP BY user_id
        ),
        c50 AS (
            SELECT at_50 AS d, COUNT(*)::int AS n
            FROM crossed WHERE at_50 BETWEEN $1 AND $2 GROUP BY at_50
        ),
        c100 AS (
            SELECT at_100 AS d, COUNT(*)::int AS n
            FROM crossed WHERE at_100 BETWEEN $1 AND $2 GROUP BY at_100
        ),
        c200 AS (
            SELECT at_200 AS d, COUNT(*)::int AS n
            FROM crossed WHERE at_200 BETWEEN $1 AND $2 GROUP BY at_200
        ),
        days AS (
            SELECT generate_series($1::date, $2::date, '1 day'::interval)::date AS d
        )
        SELECT days.d AS date,
               COALESCE(c50.n, 0)::int AS new_50k,
               COALESCE(c100.n, 0)::int AS new_100k,
               COALESCE(c200.n, 0)::int AS new_200k
        FROM days
        LEFT JOIN c50 ON c50.d = days.d
        LEFT JOIN c100 ON c100.d = days.d
        LEFT JOIN c200 ON c200.d = days.d
        ORDER BY days.d
        """,
        d_from,
        d_to,
    )
    return [
        {
            "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
            "new_50k": int(r["new_50k"]),
            "new_100k": int(r["new_100k"]),
            "new_200k": int(r["new_200k"]),
        }
        for r in rows
    ]


async def _chart_day_volume(conn, d_from: date, d_to: date) -> list[dict]:
    """На каждый день: сколько юзеров имели объём за этот день ≥ порогов."""
    rows = await conn.fetch(
        """
        WITH daily AS (
            SELECT user_id,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date AS d,
                   SUM(fiat_amount) AS vol
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
              AND ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date
                  BETWEEN $1 AND $2
            GROUP BY user_id, d
        )
        SELECT d AS date,
               COUNT(*) FILTER (WHERE vol >= 50000)::int AS new_50k,
               COUNT(*) FILTER (WHERE vol >= 100000)::int AS new_100k,
               COUNT(*) FILTER (WHERE vol >= 200000)::int AS new_200k
        FROM daily
        GROUP BY d
        ORDER BY d
        """,
        d_from,
        d_to,
    )
    by_d = {
        (r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"])): r
        for r in rows
    }
    out = []
    for d in _iter_dates(d_from, d_to):
        key = d.isoformat()
        r = by_d.get(key)
        out.append({
            "date": key,
            "new_50k": int(r["new_50k"]) if r else 0,
            "new_100k": int(r["new_100k"]) if r else 0,
            "new_200k": int(r["new_200k"]) if r else 0,
        })
    return out


async def _count_week_volume_msk(conn, start_d: date, end_d: date) -> tuple[int, int, int]:
    row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE vol >= 50000)::int AS ge_50k,
            COUNT(*) FILTER (WHERE vol >= 100000)::int AS ge_100k,
            COUNT(*) FILTER (WHERE vol >= 200000)::int AS ge_200k
        FROM (
            SELECT user_id, COALESCE(SUM(fiat_amount), 0) AS vol
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
              AND ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date
                  BETWEEN $1 AND $2
            GROUP BY user_id
        ) t
        """,
        start_d,
        end_d,
    )
    return int(row["ge_50k"]), int(row["ge_100k"]), int(row["ge_200k"])


async def _build_retention(conn, d_from: date, d_to: date) -> dict:
    """
    Новые / повторные / частые клиенты.

    - новый: дата 1-й PAID/COMPLETED заявки
    - повторный: дата 2-й заявки (впервые стал повторным)
    - частый: ≥2 заявки и средний интервал между соседними ≤ 3 суток
    """
    today = _msk_today()
    week_from = today - timedelta(days=6)

    row = await conn.fetchrow(
        """
        WITH paid AS (
            SELECT user_id,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date AS d,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow') AS ts,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id ORDER BY created_at, id
                   ) AS rn,
                   LAG(((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow'))
                       OVER (PARTITION BY user_id ORDER BY created_at, id) AS prev_ts
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
        ),
        user_stats AS (
            SELECT user_id,
                   MIN(d) FILTER (WHERE rn = 1) AS first_d,
                   MIN(d) FILTER (WHERE rn = 2) AS second_d,
                   COUNT(*)::int AS n_orders,
                   MAX(d) AS last_d,
                   AVG(EXTRACT(EPOCH FROM (ts - prev_ts)) / 86400.0)
                       FILTER (WHERE prev_ts IS NOT NULL) AS avg_gap_days
            FROM paid
            GROUP BY user_id
        )
        SELECT
            COUNT(*) FILTER (WHERE first_d BETWEEN $1 AND $2)::int AS new_period,
            COUNT(*) FILTER (WHERE first_d = $3)::int AS new_today,
            COUNT(*) FILTER (WHERE first_d BETWEEN $4 AND $3)::int AS new_week,
            COUNT(*) FILTER (WHERE second_d BETWEEN $1 AND $2)::int AS repeat_period,
            COUNT(*) FILTER (WHERE second_d = $3)::int AS repeat_today,
            COUNT(*) FILTER (WHERE second_d BETWEEN $4 AND $3)::int AS repeat_week,
            COUNT(*) FILTER (
                WHERE n_orders >= 2 AND avg_gap_days IS NOT NULL AND avg_gap_days <= 3
            )::int AS frequent_total,
            COUNT(*) FILTER (
                WHERE n_orders >= 2 AND avg_gap_days IS NOT NULL AND avg_gap_days <= 3
                  AND last_d BETWEEN $4 AND $3
            )::int AS frequent_week,
            COUNT(*) FILTER (
                WHERE n_orders >= 2 AND avg_gap_days IS NOT NULL AND avg_gap_days <= 3
                  AND last_d BETWEEN $1 AND $2
            )::int AS frequent_period
        FROM user_stats
        """,
        d_from,
        d_to,
        today,
        week_from,
    )

    chart_rows = await conn.fetch(
        """
        WITH paid AS (
            SELECT user_id,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow')::date AS d,
                   ((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow') AS ts,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id ORDER BY created_at, id
                   ) AS rn,
                   LAG(((created_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Moscow'))
                       OVER (PARTITION BY user_id ORDER BY created_at, id) AS prev_ts
            FROM orders
            WHERE status IN ('PAID', 'COMPLETED')
        ),
        user_stats AS (
            SELECT user_id,
                   MIN(d) FILTER (WHERE rn = 1) AS first_d,
                   MIN(d) FILTER (WHERE rn = 2) AS second_d,
                   COUNT(*)::int AS n_orders,
                   AVG(EXTRACT(EPOCH FROM (ts - prev_ts)) / 86400.0)
                       FILTER (WHERE prev_ts IS NOT NULL) AS avg_gap_days
            FROM paid
            GROUP BY user_id
        ),
        frequent AS (
            SELECT user_id
            FROM user_stats
            WHERE n_orders >= 2 AND avg_gap_days IS NOT NULL AND avg_gap_days <= 3
        ),
        active_freq AS (
            SELECT DISTINCT p.d, p.user_id
            FROM paid p
            JOIN frequent f ON f.user_id = p.user_id
            WHERE p.d BETWEEN $1 AND $2
        ),
        new_d AS (
            SELECT first_d AS d, COUNT(*)::int AS n
            FROM user_stats
            WHERE first_d BETWEEN $1 AND $2
            GROUP BY first_d
        ),
        rep_d AS (
            SELECT second_d AS d, COUNT(*)::int AS n
            FROM user_stats
            WHERE second_d BETWEEN $1 AND $2
            GROUP BY second_d
        ),
        freq_d AS (
            SELECT d, COUNT(*)::int AS n
            FROM active_freq
            GROUP BY d
        ),
        days AS (
            SELECT generate_series($1::date, $2::date, '1 day'::interval)::date AS d
        )
        SELECT days.d AS date,
               COALESCE(new_d.n, 0)::int AS new_clients,
               COALESCE(rep_d.n, 0)::int AS repeaters,
               COALESCE(freq_d.n, 0)::int AS frequent
        FROM days
        LEFT JOIN new_d ON new_d.d = days.d
        LEFT JOIN rep_d ON rep_d.d = days.d
        LEFT JOIN freq_d ON freq_d.d = days.d
        ORDER BY days.d
        """,
        d_from,
        d_to,
    )

    chart = [
        {
            "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
            "new_clients": int(r["new_clients"]),
            "repeaters": int(r["repeaters"]),
            "frequent": int(r["frequent"]),
        }
        for r in chart_rows
    ]

    return {
        "new_clients": {
            "period": int(row["new_period"]),
            "today": int(row["new_today"]),
            "week": int(row["new_week"]),
        },
        "repeaters": {
            "period": int(row["repeat_period"]),
            "today": int(row["repeat_today"]),
            "week": int(row["repeat_week"]),
        },
        "frequent": {
            "total": int(row["frequent_total"]),
            "period": int(row["frequent_period"]),
            "week": int(row["frequent_week"]),
            "max_avg_gap_days": 3,
        },
        "chart": chart,
    }


async def _build_volume_cohorts(conn, d_from: date, d_to: date, mode: str) -> dict:
    mode = mode if mode in _VOLUME_MODES else "lifetime"
    today = _msk_today()
    week_from = today - timedelta(days=6)

    w50, w100, w200 = await _count_week_volume_msk(conn, week_from, today)

    if mode == "lifetime":
        b50, b100, b200 = await _count_lifetime_buckets(conn)
        chart = await _chart_new_crossers(conn, d_from, d_to)
        chart_kind = "new_crossers"
        mode_label = "Все (накопительно)"
    elif mode == "new_day":
        b50, b100, b200 = await _count_new_crossers(conn, today, today)
        chart = await _chart_new_crossers(conn, d_from, d_to)
        chart_kind = "new_crossers"
        mode_label = "Новые за день"
    elif mode == "new_week":
        b50, b100, b200 = await _count_new_crossers(conn, week_from, today)
        chart = await _chart_new_crossers(conn, d_from, d_to)
        chart_kind = "new_crossers"
        mode_label = "Новые за неделю"
    else:  # week_volume
        b50, b100, b200 = w50, w100, w200
        chart = await _chart_day_volume(conn, d_from, d_to)
        chart_kind = "day_volume"
        mode_label = "Объём за 7 дней"

    retention = await _build_retention(conn, d_from, d_to)

    return {
        "mode": mode,
        "mode_label": mode_label,
        "period": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "thresholds": list(_VOLUME_THRESHOLDS),
        "buckets": _bucket_payload(b50, b100, b200),
        "week_volume": _bucket_payload(w50, w100, w200),
        "week_ge_50k": w50,
        "chart_kind": chart_kind,
        "chart": chart,
        "retention": retention,
    }


@router.get("/dashboard/volume-cohorts")
async def get_dashboard_volume_cohorts(
    admin=Depends(get_current_admin),
    mode: str = Query("lifetime", description="lifetime|new_day|new_week|week_volume"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    """Клиенты с объёмом ≥ 50 / 100 / 200 тыс ₽ и динамика новых."""
    _ = admin
    if date_from and date_to:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    else:
        d_from, d_to = default_period_range(30)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    m = (mode or "lifetime").strip().lower()
    if m not in _VOLUME_MODES:
        m = "lifetime"
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _build_volume_cohorts(conn, d_from, d_to, m)


# ---------------------------------------------------------------------------
# Project liabilities: что могут запросить/вывести прямо сейчас
# ---------------------------------------------------------------------------

async def _build_liabilities(conn) -> dict:
    """
    Общий долг проекта по разделам (available / могут запросить сейчас).

    Админы = балансы кампаний partner_accounts из admin_salary_recipients.
    Партнёры = остальные кампании partner_ledger (без пересечения с админами).
    """
    market = await market_prices_rub()
    usdt_rub = float(market.get("usdt") or 0)

    op_pool = await pool_balance(conn)
    operators_rub = float(op_pool.get("available_rub") or 0)

    buyers_rub = float(
        await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0)::float FROM user_cashback_ledger"
        )
        or 0
    )

    ref_row = await conn.fetchrow(
        """
        SELECT
            COALESCE((SELECT SUM(amount_rub)::float FROM user_referral_ledger), 0) AS bal,
            COALESCE((
                SELECT SUM(amount_rub)::float
                FROM user_referral_withdrawals
                WHERE status = 'pending'
            ), 0) AS pend
        """
    )
    referrers_rub = max(0.0, float(ref_row["bal"] or 0) - float(ref_row["pend"] or 0))

    partner_rows = await conn.fetch(
        """
        WITH admin_campaigns AS (
            SELECT DISTINCT pa.promo_campaign_id AS campaign_id
            FROM admin_salary_recipients r
            JOIN partner_accounts pa ON pa.id = r.partner_account_id
            WHERE pa.promo_campaign_id IS NOT NULL
        ),
        bal AS (
            SELECT campaign_id, COALESCE(SUM(amount_rub), 0)::float AS rub
            FROM partner_ledger
            GROUP BY campaign_id
        ),
        pend AS (
            SELECT campaign_id, COALESCE(SUM(amount_rub), 0)::float AS rub
            FROM partner_withdrawals
            WHERE status = 'pending'
            GROUP BY campaign_id
        ),
        camps AS (
            SELECT COALESCE(b.campaign_id, p.campaign_id) AS campaign_id,
                   COALESCE(b.rub, 0) AS bal,
                   COALESCE(p.rub, 0) AS pend
            FROM bal b
            FULL OUTER JOIN pend p ON p.campaign_id = b.campaign_id
        )
        SELECT
            COALESCE(SUM(
                CASE WHEN ac.campaign_id IS NOT NULL
                     THEN GREATEST(0, c.bal - c.pend) ELSE 0 END
            ), 0)::float AS admins_rub,
            COALESCE(SUM(
                CASE WHEN ac.campaign_id IS NULL
                     THEN GREATEST(0, c.bal - c.pend) ELSE 0 END
            ), 0)::float AS partners_rub
        FROM camps c
        LEFT JOIN admin_campaigns ac ON ac.campaign_id = c.campaign_id
        """
    )
    admins_rub = float(partner_rows[0]["admins_rub"] or 0) if partner_rows else 0.0
    partners_rub = float(partner_rows[0]["partners_rub"] or 0) if partner_rows else 0.0

    ext_row = await conn.fetchrow(
        """
        SELECT
            COALESCE((SELECT SUM(amount_usd)::float FROM external_ledger), 0) AS bal,
            COALESCE((
                SELECT SUM(gross_usd)::float
                FROM external_payouts
                WHERE status = 'pending'
            ), 0) AS pend
        """
    )
    external_usd = max(0.0, float(ext_row["bal"] or 0) - float(ext_row["pend"] or 0))
    external_rub = round(external_usd * usdt_rub, 2) if usdt_rub > 0 else 0.0

    sections = [
        {
            "id": "operators",
            "label": "Операторы",
            "amount_rub": round(operators_rub, 2),
        },
        {
            "id": "buyers",
            "label": "Покупатели",
            "amount_rub": round(buyers_rub, 2),
        },
        {
            "id": "referrers",
            "label": "Реферы",
            "amount_rub": round(referrers_rub, 2),
        },
        {
            "id": "partners",
            "label": "Партнёры",
            "amount_rub": round(partners_rub, 2),
        },
        {
            "id": "admins",
            "label": "Админы",
            "amount_rub": round(admins_rub, 2),
        },
        {
            "id": "external",
            "label": "Внештат",
            "amount_rub": external_rub,
            "amount_usd": round(external_usd, 2),
        },
    ]
    total_rub = round(sum(float(s["amount_rub"]) for s in sections), 2)

    return {
        "total_rub": total_rub,
        "usdt_rub_rate": round(usdt_rub, 2),
        "sections": sections,
    }


@router.get("/dashboard/liabilities")
async def get_dashboard_liabilities(admin=Depends(get_current_admin)):
    """Общий долг: что могут запросить/вывести прямо сейчас по разделам."""
    _ = admin
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await _build_liabilities(conn)


@router.get("/dashboard/capital-history", include_in_schema=False)
@router.get("/finance/capital-history")
async def get_capital_history(
    limit: int = 30,
    admin=Depends(get_current_finance_viewer),
):
    """История capital snapshots для отслеживания динамики капитала компании."""
    _ = admin
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, occurred_at, amount, currency, reference, note, created_at
            FROM owner_finance_ledger
            WHERE entry_type = 'capital_snapshot'
              AND status = 'confirmed'
            ORDER BY occurred_at DESC
            LIMIT $1
            """,
            limit,
        )

        snapshots = []
        for row in rows:
            # Parse crypto_details from reference JSON
            crypto_details = {}
            if row["reference"]:
                try:
                    import json
                    crypto_details = json.loads(row["reference"])
                except Exception:
                    pass

            snapshots.append({
                "id": row["id"],
                "occurred_at": row["occurred_at"].isoformat(),
                "total_rub": float(row["amount"]),
                "currency": row["currency"],
                "crypto_details": crypto_details,
                "note": row["note"],
                "created_at": row["created_at"].isoformat(),
            })

        return {"snapshots": snapshots, "count": len(snapshots)}

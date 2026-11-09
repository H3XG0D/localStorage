"""Shared hourly fund, split like the autopilot presence percent.

220 ₽/hour is one pool, not a rate per operator. Each stretch of time where
the roster stays the same is split by grade weight among whoever is on shift.
A person who joins halfway does not take a share of the earlier minutes.
The balance line is still written once, when the shift closes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from operator_payroll_split import (
    _profile_for_operator,
    fetch_current_payroll_settings,
    money,
    primary_pay_role,
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def hourly_amount_rub(started_at, ended_at, rate_rub) -> Decimal:
    """Minutes on shift / 60 × rate, rounded to kopecks."""
    started = _aware(started_at)
    ended = _aware(ended_at)
    rate = Decimal(str(rate_rub or 0))
    if started is None or ended is None or rate <= 0:
        return Decimal("0.00")
    seconds = (ended - started).total_seconds()
    if seconds <= 0:
        return Decimal("0.00")
    hours = Decimal(str(seconds)) / Decimal("3600")
    return money(hours * rate)


def _seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return (
        Decimal(delta.days * 86400 + delta.seconds)
        + (Decimal(delta.microseconds) / Decimal("1000000"))
    )


def split_hourly_fund(intervals: list[dict], rate_rub) -> dict[int, Decimal]:
    """Split one hourly fund across shift intervals.

    Each interval is ``operator_id``, ``start``, ``end``, ``weight``.
    The roster is recalculated whenever someone starts or ends a shift,
    so the split follows the minutes actually worked together.
    """
    rate = Decimal(str(rate_rub or 0))
    if rate <= 0:
        return {}

    events: list[tuple[datetime, int, dict]] = []
    for interval in intervals:
        start = _aware(interval.get("start"))
        end = _aware(interval.get("end"))
        if start is None or end is None or end <= start:
            continue
        weight = Decimal(str(interval.get("weight") or 0))
        if weight <= 0:
            continue
        item = {
            "operator_id": int(interval["operator_id"]),
            "weight": weight,
        }
        events.append((start, 1, item))
        events.append((end, 0, item))
    events.sort(key=lambda event: (event[0], event[1]))

    active: dict[int, dict] = {}
    totals: dict[int, Decimal] = {}
    previous: datetime | None = None
    for moment, kind, item in events:
        if previous is not None and moment > previous and active:
            pool = money(rate * _seconds(previous, moment) / Decimal("3600"))
            if pool > 0:
                for operator_id, share in _allocate_share(pool, list(active.values())):
                    totals[operator_id] = totals.get(operator_id, Decimal("0.00")) + share
        operator_id = item["operator_id"]
        if kind == 0:
            active.pop(operator_id, None)
        else:
            active[operator_id] = item
        previous = moment
    return totals


def _allocate_share(amount: Decimal, people: list[dict]) -> list[tuple[int, Decimal]]:
    ordered = sorted(people, key=lambda person: int(person["operator_id"]))
    total_weight = sum((person["weight"] for person in ordered), Decimal("0"))
    if total_weight <= 0:
        return []
    allocated = Decimal("0.00")
    shares: list[tuple[int, Decimal]] = []
    for index, person in enumerate(ordered):
        if index == len(ordered) - 1:
            value = money(amount - allocated)
        else:
            value = money(amount * person["weight"] / total_weight)
            allocated += value
        shares.append((int(person["operator_id"]), value))
    return shares


def payroll_ledger_kind(row: dict) -> str:
    kind = str(row.get("type") or "")
    note = str(row.get("note") or "")
    if kind == "hourly" or note.startswith("Почасовая"):
        return "hourly"
    if note.startswith("За смену"):
        return "presence"
    if note.startswith("Ручная"):
        return "manual"
    if kind == "penalty":
        return "penalty"
    return "accrual"


async def hourly_snapshot_for_shift_start(conn) -> tuple[bool, Decimal]:
    """Rate is frozen at shift open. Autopilot and the hourly toggle must both be on."""
    from auto_settings import auto_mode_enabled

    settings = await fetch_current_payroll_settings(conn)
    enabled = bool(auto_mode_enabled() and settings.get("autopilot_hourly_enabled"))
    if not enabled:
        return False, Decimal("0")
    return True, Decimal(str(settings.get("autopilot_hourly_rate_rub") or 0))


async def _pool_rate(conn, shift: dict) -> Decimal:
    """One fund for everyone on shift. Live settings win over the open-shift snapshot."""
    from auto_settings import auto_mode_enabled

    settings = await fetch_current_payroll_settings(conn)
    if auto_mode_enabled() and settings.get("autopilot_hourly_enabled"):
        return Decimal(str(settings.get("autopilot_hourly_rate_rub") or 0))
    if shift.get("hourly_enabled"):
        return Decimal(str(shift.get("hourly_rate_rub") or 0))
    return Decimal("0")


async def fetch_hourly_intervals(conn, window_start, window_end) -> list[dict]:
    """Shifts that overlap the window, clipped to it, with presence-style weights."""
    start = _aware(window_start)
    end = _aware(window_end)
    if start is None or end is None or end <= start:
        return []
    rows = await conn.fetch(
        """
        SELECT s.operator_id, s.started_at, s.ended_at,
               oa.operator_role, oa.operator_roles
        FROM operator_shifts s
        JOIN operator_accounts oa ON oa.id = s.operator_id
        WHERE s.started_at < $2
          AND (s.ended_at IS NULL OR s.ended_at > $1)
        """,
        start,
        end,
    )
    intervals: list[dict] = []
    for row in rows:
        role = primary_pay_role(dict(row))
        profile = await _profile_for_operator(conn, int(row["operator_id"]), role, end)
        piece_start = max(_aware(row["started_at"]), start)
        piece_end = min(_aware(row["ended_at"]) or end, end)
        if piece_end <= piece_start:
            continue
        intervals.append(
            {
                "operator_id": int(row["operator_id"]),
                "start": piece_start,
                "end": piece_end,
                "weight": Decimal(str(profile.get("weight") or 1)),
            }
        )
    return intervals


async def accrue_shift_hourly(conn, shift: dict) -> dict:
    """One ledger row per shift: that operator's minute-by-minute share of the fund."""
    shift_id = int(shift["id"])
    rate = await _pool_rate(conn, shift)
    if rate <= 0:
        return {"accrued": False, "amount_rub": 0.0, "reason": "disabled"}
    ended = shift.get("ended_at")
    if ended is None:
        return {"accrued": False, "amount_rub": 0.0, "reason": "open"}
    existing = await conn.fetchval(
        """
        SELECT id FROM operator_payroll_ledger
        WHERE type = 'hourly' AND shift_id = $1
        """,
        shift_id,
    )
    if existing:
        return {"accrued": False, "amount_rub": 0.0, "reason": "already"}
    operator_id = int(shift["operator_id"])
    intervals = await fetch_hourly_intervals(conn, shift.get("started_at"), ended)
    amount = split_hourly_fund(intervals, rate).get(operator_id, Decimal("0.00"))
    if amount <= 0:
        return {"accrued": False, "amount_rub": 0.0, "reason": "zero"}
    await conn.execute(
        """
        INSERT INTO operator_payroll_ledger (
            type, amount_rub, shift_id, operator_id, note
        ) VALUES ('hourly', $1, $2, $3, $4)
        ON CONFLICT DO NOTHING
        """,
        amount,
        shift_id,
        operator_id,
        f"Почасовая оплата смены #{shift_id}",
    )
    return {"accrued": True, "amount_rub": float(amount), "reason": "accrued"}


def attach_open_shift_hourly(stats: dict, preview: dict | None) -> dict:
    """Keep order pay separate and fold the live hour share into earnings_rub.

    The ledger row is still written once, when the shift closes. earnings_rub
    is what the operator dashboard already renders, so the sitting operator
    sees the hour share move without a second balance.
    """
    out = dict(stats or {})
    deals = round(float(out.get("earnings_rub") or 0), 2)
    applies = bool(preview and preview.get("applies"))
    forecast = round(float((preview or {}).get("forecast_rub") or 0), 2) if applies else 0.0
    out["deal_earnings_rub"] = deals
    out["hourly_applies"] = applies
    out["hourly_forecast_rub"] = forecast
    out["hourly_rate_rub"] = round(float((preview or {}).get("rate_rub") or 0), 2) if applies else 0.0
    out["earnings_rub"] = round(deals + forecast, 2)
    return out


async def open_shift_hourly_preview(conn, operator_id: int) -> dict:
    """Forecast only. The balance is written when the shift closes."""
    row = await conn.fetchrow(
        """
        SELECT id, started_at, hourly_enabled, hourly_rate_rub
        FROM operator_shifts
        WHERE operator_id = $1 AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        operator_id,
    )
    if not row:
        return {"open": False, "applies": False, "rate_rub": 0.0, "forecast_rub": 0.0, "started_at": None}
    rate = await _pool_rate(conn, dict(row))
    started = row["started_at"]
    if rate <= 0:
        return {
            "open": True,
            "applies": False,
            "rate_rub": 0.0,
            "forecast_rub": 0.0,
            "started_at": started.isoformat() if hasattr(started, "isoformat") else None,
        }
    now = datetime.now(timezone.utc)
    intervals = await fetch_hourly_intervals(conn, started, now)
    forecast = split_hourly_fund(intervals, rate).get(int(operator_id), Decimal("0.00"))
    return {
        "open": True,
        "applies": True,
        "rate_rub": float(rate),
        "forecast_rub": float(forecast),
        "started_at": started.isoformat() if hasattr(started, "isoformat") else None,
    }

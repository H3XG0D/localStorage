"""Прогноз, чем залить payin-карту: типичные BUY и закрывающие связки.

BUY не висят в пуле, как SELL. Оператору нужен ориентир «какие чеки бывают»
и как закрыть карту целиком — например 10k+8k+8k завтра после 10:00 МСК.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Sequence
from zoneinfo import ZoneInfo

from payout_requisite_matcher import (
    Candidate,
    Plan,
    build_plan,
    from_kop,
    matcher_limits,
    METHOD_SUB_TOKENS,
    to_kop,
    unreserved_remaining_rub,
)

MSK = ZoneInfo("Europe/Moscow")
LOOKBACK_DAYS = 21
WEEKDAY_LOOKBACK_WEEKS = 4
WEEKDAY_SINCE_DAYS = 35
HOUR_SLACK = 1
MIN_HISTORY_SAMPLES = 8
TYPICAL_MIN_RUB = 1000
TYPICAL_MAX_RUB = 30_000
TOP_AMOUNTS = 8
FALLBACK_TYPICAL_RUB = (2500, 3300, 4900, 5000, 7000)
# PostgreSQL EXTRACT(DOW): 0=воскресенье … 6=суббота (по МСК created_at).
WEEKDAY_RU = (
    "воскресенье",
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
)
WEEKDAY_RU_PAST = (
    "воскресеньям",
    "понедельникам",
    "вторникам",
    "средам",
    "четвергам",
    "пятницам",
    "субботам",
)
DAYTIME_FROM_HOUR = 10
DAYTIME_HOURS = tuple(range(10, 21))
DAYTIME_PREFERRED = (5000, 7000, 8000, 10000, 11000, 12000, 15000, 20000)
CLOSING_GRID = (
    2000, 2500, 3000, 3300, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000,
    7500, 8000, 8500, 9000, 9500, 10000, 11000, 12000, 13000, 14000, 15000,
    16000, 18000, 20000, 22000, 25000, 30000,
)
MIN_CHECK_RUB = 2000
PAID_BUY_STATUSES = ("PAID", "COMPLETED")
DEFAULT_FIRST_CHECK_MINUTES = 25
DEFAULT_GAP_MINUTES = 30
MAX_GAP_MINUTES = 180
MAX_FIRST_CHECK_MINUTES = 120
DAYTIME_END_HOUR = 18


def hour_msk(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(MSK).hour


def weekday_msk(now: datetime | None = None) -> int:
    """DOW по МСК как PostgreSQL EXTRACT(DOW): 0=воскресенье, 6=суббота."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    py_dow = current.astimezone(MSK).weekday()  # Mon=0 … Sun=6
    return (py_dow + 1) % 7


def weekday_label_ru(dow: int | None = None, *, now: datetime | None = None) -> str:
    idx = int(dow if dow is not None else weekday_msk(now))
    return WEEKDAY_RU[idx % 7]


def weekday_past_label_ru(dow: int | None = None, *, now: datetime | None = None) -> str:
    idx = int(dow if dow is not None else weekday_msk(now))
    return WEEKDAY_RU_PAST[idx % 7]


def resolve_typical_from_weekday(
    dow_samples: Sequence,
    fallback_samples: Sequence,
) -> tuple[list[int], str, int]:
    """Типичные суммы: сначала тот же день недели, иначе смесь / 21-дневный час."""
    _amounts, _, dow_raw = typical_amounts_from_samples(dow_samples, fallback=())
    if dow_raw >= MIN_HISTORY_SAMPLES and _amounts:
        return _amounts, "weekday_history", dow_raw
    if dow_raw >= 1:
        merged = list(dow_samples) + list(fallback_samples)
        amounts, _, raw = typical_amounts_from_samples(merged, fallback=FALLBACK_TYPICAL_RUB)
        return amounts, "weekday_mixed", raw
    return typical_amounts_from_samples(fallback_samples)


def _time_phrase(hour: int, *, source: str | None, weekday_past: str | None) -> str:
    clock = f"{hour:02d}:00 МСК"
    if source in ("weekday_history", "weekday_mixed") and weekday_past:
        return f"По прошлым {weekday_past} в {clock}"
    return f"В {clock}"


def hour_window(hour: int, slack: int = HOUR_SLACK) -> list[int]:
    return [(int(hour) + delta) % 24 for delta in range(-slack, slack + 1)]


def daytime_close_label(now: datetime | None = None) -> str:
    """После 18:00 МСК дневной поток уже не поможет — следующее окно завтра с 10."""
    hour = hour_msk(now)
    if hour < DAYTIME_FROM_HOUR:
        return f"сегодня после {DAYTIME_FROM_HOUR:02d}:00 МСК"
    if hour < DAYTIME_END_HOUR:
        return f"сегодня после {DAYTIME_FROM_HOUR:02d}:00 МСК"
    return f"завтра после {DAYTIME_FROM_HOUR:02d}:00 МСК"


def minutes_until_daytime_start(now: datetime | None = None) -> int:
    """Минуты до ближайшего старта дневного окна 10:00–18:00 МСК."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(MSK)
    hour = local.hour
    if DAYTIME_FROM_HOUR <= hour < DAYTIME_END_HOUR:
        return 0
    if hour < DAYTIME_FROM_HOUR:
        target = local.replace(hour=DAYTIME_FROM_HOUR, minute=0, second=0, microsecond=0)
    else:
        target = (local + timedelta(days=1)).replace(
            hour=DAYTIME_FROM_HOUR, minute=0, second=0, microsecond=0
        )
    return max(0, int((target - local).total_seconds() // 60))


def _median_minutes(rows: Sequence, field: str, *, cap: int | None = None) -> tuple[int, int]:
    values: list[float] = []
    for row in rows:
        raw = row[field] if isinstance(row, dict) else getattr(row, field, None)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if cap is not None and value > cap:
            continue
        values.append(value)
    if not values:
        return 0, 0
    ordered = sorted(values)
    median = int(round(ordered[len(ordered) // 2]))
    return median, len(values)


def resolve_gap_minutes(
    dow_gaps: Sequence,
    fallback_gaps: Sequence,
) -> tuple[int, str, int]:
    """Медиана минут между чеками: DOW+час → смесь → 21 день → константа."""
    gap, dow_raw = _median_minutes(dow_gaps, "gap_minutes", cap=MAX_GAP_MINUTES)
    if dow_raw >= MIN_HISTORY_SAMPLES and gap > 0:
        return gap, "weekday_history", dow_raw
    if dow_raw >= 1:
        merged = list(dow_gaps) + list(fallback_gaps)
        gap, raw = _median_minutes(merged, "gap_minutes", cap=MAX_GAP_MINUTES)
        return gap or DEFAULT_GAP_MINUTES, "weekday_mixed", raw
    gap, raw = _median_minutes(fallback_gaps, "gap_minutes", cap=MAX_GAP_MINUTES)
    if raw >= MIN_HISTORY_SAMPLES and gap > 0:
        return gap, "history", raw
    if raw >= 1:
        return gap or DEFAULT_GAP_MINUTES, "mixed", raw
    return DEFAULT_GAP_MINUTES, "fallback", 0


def resolve_first_check_minutes(
    dow_rows: Sequence,
    fallback_rows: Sequence,
) -> tuple[int, str, int]:
    """Медиана минут до первого PAID чека на карте."""
    first, dow_raw = _median_minutes(dow_rows, "first_minutes", cap=MAX_FIRST_CHECK_MINUTES)
    if dow_raw >= MIN_HISTORY_SAMPLES and first > 0:
        return first, "weekday_history", dow_raw
    if dow_raw >= 1:
        merged = list(dow_rows) + list(fallback_rows)
        first, raw = _median_minutes(merged, "first_minutes", cap=MAX_FIRST_CHECK_MINUTES)
        return first or DEFAULT_FIRST_CHECK_MINUTES, "weekday_mixed", raw
    first, raw = _median_minutes(fallback_rows, "first_minutes", cap=MAX_FIRST_CHECK_MINUTES)
    if raw >= MIN_HISTORY_SAMPLES and first > 0:
        return first, "history", raw
    if raw >= 1:
        return first or DEFAULT_FIRST_CHECK_MINUTES, "mixed", raw
    return DEFAULT_FIRST_CHECK_MINUTES, "fallback", 0


def estimate_fill_minutes(
    *,
    checks_count: int,
    first_min: int,
    gap_min: int,
    now: datetime | None = None,
) -> int:
    wait = minutes_until_daytime_start(now)
    first = int(first_min) + wait
    gap = max(1, int(gap_min))
    count = max(1, int(checks_count))
    return first + max(0, count - 1) * gap


def _minutes_word(minutes: int) -> str:
    value = max(1, int(minutes))
    if value % 10 == 1 and value % 100 != 11:
        unit = "минуту"
    elif 2 <= value % 10 <= 4 and not (12 <= value % 100 <= 14):
        unit = "минуты"
    else:
        unit = "минут"
    return f"{value} {unit}"


def _hours_word(hours: int) -> str:
    value = max(1, int(hours))
    if value % 10 == 1 and value % 100 != 11:
        unit = "ч"
    elif 2 <= value % 10 <= 4 and not (12 <= value % 100 <= 14):
        unit = "ч"
    else:
        unit = "ч"
    return f"{value} {unit}"


def format_fill_eta_minutes(minutes: int) -> str:
    mins = max(1, int(minutes))
    if mins < 60:
        return f"~{_minutes_word(mins)}"
    hours = mins // 60
    rem = mins % 60
    if rem == 0:
        return f"~{_hours_word(hours)}"
    return f"~{_hours_word(hours)} {_minutes_word(rem)}"


def build_split_payload(
    splits: Sequence[tuple[int, ...]],
    *,
    first_min: int,
    gap_min: int,
    now: datetime | None = None,
) -> list[dict]:
    payload: list[dict] = []
    for parts in splits:
        count = len(parts)
        fill_minutes = estimate_fill_minutes(
            checks_count=count,
            first_min=first_min,
            gap_min=gap_min,
            now=now,
        )
        payload.append(
            {
                "checks": [int(part) for part in parts],
                "sum_rub": int(sum(parts)),
                "checks_count": count,
                "fill_minutes": fill_minutes,
                "fill_eta_label": format_fill_eta_minutes(fill_minutes),
            }
        )
    return payload


def round_typical_rub(amount) -> int:
    if amount is None or amount == "":
        return 0
    try:
        kop = to_kop(amount)
    except (InvalidOperation, ValueError, TypeError):
        return 0
    hundreds = (Decimal(kop) / Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, int(hundreds) * 100)


def typical_amounts_from_samples(samples: Sequence, *, fallback: Sequence[int] = FALLBACK_TYPICAL_RUB) -> tuple[list[int], str, int]:
    """Округлённые суммы, от частых к редким. source: history / mixed / fallback."""
    counted: Counter[int] = Counter()
    raw = 0
    for sample in samples:
        value = sample["fiat_amount"] if isinstance(sample, dict) else sample
        amount = round_typical_rub(value)
        if TYPICAL_MIN_RUB <= amount <= TYPICAL_MAX_RUB:
            counted[amount] += 1
            raw += 1
    ranked = [amount for amount, _ in counted.most_common(TOP_AMOUNTS)]
    fallback_list = [int(v) for v in fallback]
    if raw >= MIN_HISTORY_SAMPLES and ranked:
        return ranked, "history", raw
    if raw >= 1:
        merged = list(dict.fromkeys(ranked + fallback_list))
        return merged[:TOP_AMOUNTS], "mixed", raw
    return list(fallback_list), "fallback", raw


def sample_weights(samples: Sequence) -> Counter[int]:
    counted: Counter[int] = Counter()
    for sample in samples:
        value = sample["fiat_amount"] if isinstance(sample, dict) else sample
        amount = round_typical_rub(value)
        if TYPICAL_MIN_RUB <= amount <= TYPICAL_MAX_RUB:
            counted[amount] += 1
    return counted


def synthetic_candidates(amounts: Sequence[int], max_checks: int) -> list[Candidate]:
    """Каждую типичную сумму повторяем до max_checks — иначе нельзя сложить 3×5000."""
    slots = max(1, int(max_checks))
    out: list[Candidate] = []
    for amount in amounts:
        kop = to_kop(amount)
        if kop <= 0:
            continue
        for index in range(slots):
            out.append(Candidate(order_id=f"typ:{int(amount)}:{index + 1}", amount_kop=kop))
    return out


def _is_nice(amount: int) -> bool:
    if amount < MIN_CHECK_RUB:
        return False
    if amount in CLOSING_GRID:
        return True
    return amount % 1000 == 0 or amount % 500 == 0


def _split_key(parts: tuple[int, ...], weights: Counter[int]) -> tuple:
    preferred = set(DAYTIME_PREFERRED) | {amt for amt, count in weights.most_common(8) if count >= 2}
    unpreferred = sum(0 if part in preferred else 1 for part in parts)
    evenness = max(parts) - min(parts) if parts else 0
    roundness = sum(0 if part % 1000 == 0 else 1 for part in parts)
    popularity = -sum(weights.get(part, 0) for part in parts)
    return (unpreferred, evenness, roundness, popularity, len(parts))


def closing_splits(
    remaining_rub,
    max_checks: int,
    weights: Counter[int] | None = None,
) -> list[tuple[int, ...]]:
    """Закрывающие связки круглыми чеками: 10+8+8, 15+11 и т.п."""
    remaining = int(Decimal(str(remaining_rub)))
    max_checks = max(1, int(max_checks))
    weights = weights or Counter()
    if remaining < MIN_CHECK_RUB:
        return []
    grid = [amt for amt in CLOSING_GRID if MIN_CHECK_RUB <= amt <= remaining]
    found: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()

    def add(parts: tuple[int, ...]) -> None:
        if not parts or sum(parts) != remaining:
            return
        ordered = tuple(sorted(parts, reverse=True))
        if ordered in seen:
            return
        seen.add(ordered)
        found.append(ordered)

    add((remaining,))
    if max_checks >= 2:
        for first in grid:
            second = remaining - first
            if _is_nice(second):
                add((first, second))
    if max_checks >= 3:
        for i, first in enumerate(grid):
            for second in grid[i:]:
                third = remaining - first - second
                if _is_nice(third):
                    add((first, second, third))

    found.sort(key=lambda parts: _split_key(parts, weights))
    by_count: dict[int, tuple[int, ...]] = {}
    for parts in found:
        by_count.setdefault(len(parts), parts)
    if not by_count:
        return []
    prefer_one = remaining <= 15000 and 1 in by_count
    counts = (1, 2, 3) if prefer_one else (3, 2, 1)
    best_unpref = min(_split_key(parts, weights)[0] for parts in by_count.values())
    ordered: list[tuple[int, ...]] = []
    for count in counts:
        if count not in by_count or count > max_checks:
            continue
        if count == 1 and remaining > 15000:
            continue
        candidate = by_count[count]
        if _split_key(candidate, weights)[0] > best_unpref:
            continue
        ordered.append(candidate)
    return ordered


def plan_from_split(parts: Sequence[int]) -> Plan:
    orders = [
        Candidate(order_id=f"typ:{int(amount)}:{index + 1}", amount_kop=to_kop(amount))
        for index, amount in enumerate(parts)
    ]
    return Plan(orders=orders, doliv_kop=0, leftover_kop=0)


def format_split(parts: Sequence[int]) -> str:
    return " + ".join(f"{int(amount):,}".replace(",", " ") for amount in parts) + " ₽"


def fill_hint(
    *,
    remaining_rub,
    plan: Plan | None,
    typical: Sequence[int],
    hour: int,
    max_checks: int,
    solo: bool,
    source: str | None = None,
    weekday_past: str | None = None,
) -> str | None:
    remaining = Decimal(str(remaining_rub))
    typical_txt = " / ".join(f"{int(v):,}".replace(",", " ") for v in typical[:5]) or "—"
    when = _time_phrase(hour, source=source, weekday_past=weekday_past)
    if solo:
        leftover = remaining - Decimal(int(typical[-1]) if typical else 5000)
        if plan is not None:
            leftover = from_kop(plan.leftover_kop)
        if leftover > 0:
            leftover_txt = f"{leftover:,.0f}".replace(",", " ")
            return (
                f"Первый час — один чек. {when} чаще {typical_txt} ₽; "
                f"остаток около {leftover_txt} ₽ не закроется, пока не выйдет окно."
            )
        return f"Первый час — один чек. {when} типичный как раз около карты."
    if plan is None:
        return f"{when} типичные чеки {typical_txt} ₽ — под эту сумму не из чего сложить план."
    leftover = from_kop(plan.leftover_kop)
    if leftover <= 0:
        return None
    leftover_txt = f"{leftover:,.0f}".replace(",", " ")
    return f"Типичные чеки {when} ({typical_txt} ₽) оставляют {leftover_txt} ₽."


def _annotate(plan: Plan | None, extra: dict) -> Plan | None:
    if plan is None:
        plan = Plan(orders=[], leftover_kop=to_kop(extra.get("free_rub") or 0))
    plan.extra = extra
    return plan


async def load_typical_buy_samples(
    conn,
    *,
    method: str,
    crypto: str | None,
    now: datetime | None = None,
    hours: Sequence[int] | None = None,
    weekday: int | None = None,
) -> list:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    hour = hour_msk(current)
    sub_token = METHOD_SUB_TOKENS.get(str(method).lower())
    coin = (crypto or "").split("_", 1)[0].strip().lower() or None
    lookback_days = WEEKDAY_SINCE_DAYS if weekday is not None else LOOKBACK_DAYS
    since = (current.astimezone(timezone.utc) - timedelta(days=lookback_days)).replace(tzinfo=None)
    slots = list(hours) if hours is not None else hour_window(hour)
    try:
        return await conn.fetch(
            """
            SELECT o.fiat_amount
            FROM orders o
            WHERE lower(o.direction) = 'buy'
              AND o.status = ANY($1::text[])
              AND o.created_at >= $2
              AND o.fiat_amount > 0
              AND ($3::text IS NULL OR upper(o.sub_token) = $3)
              AND ($4::text IS NULL OR lower(split_part(o.crypto, '_', 1)) = $4)
              AND EXTRACT(HOUR FROM timezone('Europe/Moscow', o.created_at))::int = ANY($5::int[])
              AND ($6::int IS NULL OR EXTRACT(DOW FROM timezone('Europe/Moscow', o.created_at))::int = $6)
            ORDER BY o.created_at DESC
            LIMIT 400
            """,
            list(PAID_BUY_STATUSES),
            since,
            sub_token,
            coin,
            slots,
            int(weekday) if weekday is not None else None,
        )
    except Exception:
        return []


async def load_payin_check_gap_minutes(
    conn,
    *,
    method: str,
    crypto: str | None,
    now: datetime | None = None,
    weekday: int | None = None,
) -> list:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    hour = hour_msk(current)
    method_key = str(method or "").strip().lower() or None
    coin = (crypto or "").split("_", 1)[0].strip().lower() or None
    lookback_days = WEEKDAY_SINCE_DAYS if weekday is not None else LOOKBACK_DAYS
    since = (current.astimezone(timezone.utc) - timedelta(days=lookback_days)).replace(tzinfo=None)
    slots = hour_window(hour)
    try:
        return await conn.fetch(
            """
            WITH paid AS (
                SELECT
                    a.requisite_id,
                    a.paid_at,
                    LAG(a.paid_at) OVER (
                        PARTITION BY a.requisite_id ORDER BY a.paid_at
                    ) AS prev_paid
                FROM payout_requisite_allocations a
                JOIN operator_payout_requisites r ON r.id = a.requisite_id
                WHERE a.status = 'PAID'
                  AND a.kind = 'payin'
                  AND lower(r.direction) = 'payin'
                  AND a.paid_at >= $1
                  AND ($2::text IS NULL OR lower(r.method) = $2)
                  AND ($3::text IS NULL OR lower(r.crypto) = $3)
            )
            SELECT EXTRACT(EPOCH FROM (paid_at - prev_paid)) / 60.0 AS gap_minutes
            FROM paid
            WHERE prev_paid IS NOT NULL
              AND paid_at > prev_paid
              AND EXTRACT(EPOCH FROM (paid_at - prev_paid)) / 60.0 <= $4
              AND EXTRACT(HOUR FROM timezone('Europe/Moscow', paid_at))::int = ANY($5::int[])
              AND ($6::int IS NULL
                   OR EXTRACT(DOW FROM timezone('Europe/Moscow', paid_at))::int = $6)
            ORDER BY gap_minutes
            LIMIT 400
            """,
            since,
            method_key,
            coin,
            MAX_GAP_MINUTES,
            slots,
            int(weekday) if weekday is not None else None,
        )
    except Exception:
        return []


async def load_first_check_minutes(
    conn,
    *,
    method: str,
    crypto: str | None,
    now: datetime | None = None,
    weekday: int | None = None,
) -> list:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    hour = hour_msk(current)
    method_key = str(method or "").strip().lower() or None
    coin = (crypto or "").split("_", 1)[0].strip().lower() or None
    lookback_days = WEEKDAY_SINCE_DAYS if weekday is not None else LOOKBACK_DAYS
    since = (current.astimezone(timezone.utc) - timedelta(days=lookback_days)).replace(tzinfo=None)
    slots = hour_window(hour)
    try:
        return await conn.fetch(
            """
            WITH first_paid AS (
                SELECT
                    MIN(a.paid_at) AS first_paid_at,
                    r.created_at AS card_created
                FROM operator_payout_requisites r
                JOIN payout_requisite_allocations a ON a.requisite_id = r.id
                WHERE lower(r.direction) = 'payin'
                  AND a.status = 'PAID'
                  AND a.kind = 'payin'
                  AND a.paid_at >= $1
                  AND ($2::text IS NULL OR lower(r.method) = $2)
                  AND ($3::text IS NULL OR lower(r.crypto) = $3)
                GROUP BY r.id, r.created_at
            )
            SELECT EXTRACT(EPOCH FROM (first_paid_at - card_created)) / 60.0 AS first_minutes
            FROM first_paid
            WHERE first_paid_at IS NOT NULL
              AND first_paid_at > card_created
              AND EXTRACT(EPOCH FROM (first_paid_at - card_created)) / 60.0 <= $4
              AND EXTRACT(HOUR FROM timezone('Europe/Moscow', first_paid_at))::int = ANY($5::int[])
              AND ($6::int IS NULL
                   OR EXTRACT(DOW FROM timezone('Europe/Moscow', first_paid_at))::int = $6)
            ORDER BY first_minutes
            LIMIT 400
            """,
            since,
            method_key,
            coin,
            MAX_FIRST_CHECK_MINUTES,
            slots,
            int(weekday) if weekday is not None else None,
        )
    except Exception:
        return []


async def load_fill_timing(conn, *, method: str, crypto: str | None, now: datetime | None, dow: int) -> tuple[int, int, str, str]:
    """first_min, gap_min, gap_source, first_source."""
    dow_gaps = await load_payin_check_gap_minutes(
        conn, method=method, crypto=crypto, now=now, weekday=dow
    )
    hour_gaps = await load_payin_check_gap_minutes(conn, method=method, crypto=crypto, now=now)
    gap_min, gap_source, _gap_raw = resolve_gap_minutes(dow_gaps, hour_gaps)

    dow_first = await load_first_check_minutes(
        conn, method=method, crypto=crypto, now=now, weekday=dow
    )
    hour_first = await load_first_check_minutes(conn, method=method, crypto=crypto, now=now)
    first_min, first_source, _first_raw = resolve_first_check_minutes(dow_first, hour_first)
    return first_min, gap_min, gap_source, first_source


async def forecast_payin_plan(conn, row, *, now: datetime | None = None) -> tuple[Plan | None, Decimal]:
    free = await unreserved_remaining_rub(conn, row)
    hour = hour_msk(now)
    dow = weekday_msk(now)
    dow_label = weekday_label_ru(dow)
    dow_past = weekday_past_label_ru(dow)
    solo_checks, doliv_limit_rub = matcher_limits(row, now=now)
    card_checks = max(1, int(row.get("max_checks") or 3))
    method = row.get("method") or "sbp"
    crypto = row.get("crypto")
    dow_now_samples = await load_typical_buy_samples(
        conn, method=method, crypto=crypto, now=now, weekday=dow
    )
    dow_day_samples = await load_typical_buy_samples(
        conn,
        method=method,
        crypto=crypto,
        now=now,
        hours=DAYTIME_HOURS,
        weekday=dow,
    )
    now_samples = await load_typical_buy_samples(conn, method=method, crypto=crypto, now=now)
    day_samples = await load_typical_buy_samples(
        conn,
        method=method,
        crypto=crypto,
        now=now,
        hours=DAYTIME_HOURS,
    )
    typical, source, raw = resolve_typical_from_weekday(dow_now_samples, now_samples)
    weight_samples = dow_day_samples if dow_day_samples else day_samples
    weights = sample_weights(weight_samples)
    splits = closing_splits(free, card_checks, weights) if free > 0 else []
    first_min, gap_min, gap_source, first_source = await load_fill_timing(
        conn, method=method, crypto=crypto, now=now, dow=dow
    )
    splits_payload = build_split_payload(
        splits, first_min=first_min, gap_min=gap_min, now=now
    )
    close_when = daytime_close_label(now)
    extra = {
        "kind": "forecast",
        "hour_msk": hour,
        "weekday_dow": dow,
        "weekday_label": dow_label,
        "weeks_looked": WEEKDAY_LOOKBACK_WEEKS,
        "typical_rub": [float(v) for v in typical],
        "samples": raw,
        "source": source,
        "solo_window": solo_checks == 1,
        "free_rub": float(free),
        "close_when": close_when,
        "close_after_hour_msk": DAYTIME_FROM_HOUR,
        "gap_minutes": gap_min,
        "gap_source": gap_source,
        "first_check_minutes": first_min,
        "first_check_source": first_source,
        "splits": splits_payload,
    }
    if free <= 0:
        extra["hint"] = None
        empty = Plan()
        empty.extra = extra
        return empty, free

    now_candidates = synthetic_candidates(typical, solo_checks)
    now_plan = build_plan(
        free,
        now_candidates,
        max_checks=solo_checks,
        doliv_limit_rub=doliv_limit_rub,
    )
    extra["now_hint"] = fill_hint(
        remaining_rub=free,
        plan=now_plan,
        typical=typical,
        hour=hour,
        max_checks=solo_checks,
        solo=solo_checks == 1,
        source=source,
        weekday_past=dow_past,
    )
    extra["now_orders"] = (now_plan.as_dict()["orders"] if now_plan else [])
    if now_plan and now_plan.closes and len(now_plan.orders) == 1:
        solo_minutes = estimate_fill_minutes(
            checks_count=1,
            first_min=first_min,
            gap_min=gap_min,
            now=now,
        )
        extra["first_check_eta_label"] = format_fill_eta_minutes(solo_minutes)

    if splits:
        plan = plan_from_split(splits[0])
        primary = format_split(splits[0])
        primary_eta = splits_payload[0].get("fill_eta_label") if splits_payload else None
        alt_parts = splits[1] if len(splits) > 1 else None
        alt = format_split(alt_parts) if alt_parts else ""
        alt_eta = splits_payload[1].get("fill_eta_label") if len(splits_payload) > 1 else None
        weekday_note = (
            f" По прошлым {dow_past} — типичные чеки этого дня."
            if source in ("weekday_history", "weekday_mixed")
            else ""
        )
        primary_line = f"{close_when} закрыть {primary}"
        if primary_eta:
            primary_line += f" ({primary_eta})"
        alt_line = ""
        if alt:
            alt_line = f" Или {alt}"
            if alt_eta:
                alt_line += f" ({alt_eta})"
            alt_line += "."
        extra["hint"] = (
            primary_line + "."
            + alt_line
            + weekday_note
            + " К оплате с комиссией остаток будет меньше ввода."
        )
        extra["commission_note"] = "К оплате с комиссией остаток будет меньше ввода."
        return _annotate(plan, extra), free

    extra["hint"] = extra["now_hint"]
    return _annotate(now_plan, extra), free

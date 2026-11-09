"""Read-only observations and empirical traffic estimates, never payment decisions."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
import asyncio
import time

from payin_requisite_rail import PayinCandidate, fit_payin

MSK = ZoneInfo("Europe/Moscow")
UTC = timezone.utc
_history_cache = None
_history_at = 0.0
_history_lock = asyncio.Lock()


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def estimate(row, history, *, now):
    """Replay current amount rules over 35 complete historical wall-clock windows.

    Probabilities are empirical frequencies, including zero-event windows. No
    assumption of a constant Poisson rate or observed Telegram delivery.
    """
    now = utc(now)
    free = max(Decimal("0"), Decimal(str(row["amount_rub"]))
               - Decimal(str(row.get("paid_rub") or 0))
               - Decimal(str(row.get("reserved_rub") or 0)))
    candidate = PayinCandidate(
        id=int(row["id"]), operator_id=int(row["operator_id"]),
        method=row["method"], requisites="", bank=None, holder_name=None,
        cost_pct=Decimal(str(row.get("cost_pct") or 0)), crypto=row.get("crypto") or "btc",
        deadline_at=row.get("deadline_at"), max_checks=int(row.get("max_checks") or 1),
        free_rub=free, used_checks=int(row.get("used_checks") or 0),
        created_at=row.get("created_at"), first_paid_at=row.get("first_paid_at"),
        doliv_limit_rub=int(row.get("doliv_limit_rub") or 0),
    )
    reasons = []
    if row.get("status") not in ("OPEN", "RESERVED", "PARTIAL"):
        reasons.append("Реквизит не в активном приёме")
    if not row.get("confirmed_at"):
        reasons.append("Ждёт включения")
    if not row.get("deadline_at") or utc(row["deadline_at"]) <= now:
        reasons.append("Срок приёма истёк")
    if row.get("has_open_reserve") or Decimal(str(row.get("reserved_rub") or 0)) > 0:
        reasons.append("Есть назначенный платёж: ждём его завершения")
    if free <= 0:
        reasons.append("Свободного остатка нет")
    if candidate.used_checks >= candidate.max_checks:
        reasons.append("Лимит платежей занят")

    # A card request can use SBP too, as in collect_payin_pool. Crypto is
    # deliberately not filtered: reserve_payin_slot does not accept crypto.
    methods = ("SBPRUB", "CARDRUB") if candidate.method == "sbp" else ("CARDRUB",)
    samples = [dict(h) for h in history if str(h.get("sub_token") or "").upper() in methods]
    local = now.astimezone(MSK)
    windows = []
    paid_amounts = []
    for day in range(1, 36):
        start = local - timedelta(days=day)
        matches = []
        for h in samples:
            offset = (utc(h["created_at"]) - start.astimezone(UTC)).total_seconds() / 60
            if not 0 <= offset < 60:
                continue
            # Age / hunt changes over the next hour are applied at arrival.
            arrival = now + timedelta(minutes=offset)
            fit = fit_payin([candidate], h["fiat_amount"], now=arrival)
            if fit.candidate is not None:
                matches.append((offset, h))
        windows.append((start.weekday() == local.weekday(), matches))
    same = [events for same_day, events in windows if same_day]
    use_same = sum(len(events) for events in same) >= 8
    selected = same if use_same else [events for _, events in windows]
    matches = [h for events in selected for _, h in events]
    paid = [h for h in matches if h["status"] in ("PAID", "COMPLETED")]
    resolved = [h for h in matches if h["status"] in ("PAID", "COMPLETED", "CANCELED", "EXPIRED", "FAILED")]
    for h in paid:
        paid_amounts.append(float(h["fiat_amount"]))
    n = len(selected)
    probabilities = {str(minutes): round(sum(any(offset < minutes for offset, _ in events)
                                            for events in selected) / n, 4)
                     for minutes in (15, 30, 60)}
    # Actual sequential examples; do not claim that median division closes a card.
    states = [(candidate, [])]
    solutions = []
    amounts = sorted(set(paid_amounts))
    if len(amounts) > 20:
        amounts = [amounts[round(i * (len(amounts) - 1) / 19)] for i in range(20)]
    for _ in range(max(0, min(5, candidate.max_checks - candidate.used_checks))):
        next_states = {}
        for state, sequence in states:
            for amount in amounts:
                fit = fit_payin([state], amount, now=now)
                if fit.candidate is None:
                    continue
                left = state.free_rub - fit.pay_rub
                seq = sequence + [float(fit.pay_rub)]
                if left == 0:
                    solutions.append(seq)
                elif left > 0:
                    updated = replace(state, free_rub=left, used_checks=state.used_checks + 1,
                                      first_paid_at=state.first_paid_at or now)
                    next_states[(left, updated.used_checks)] = (updated, seq)
        states = list(next_states.values())[:100]
    return {
        "computed_at": now.isoformat(),
        "readiness": {"ready": not reasons, "reasons": reasons,
                      "free_rub": float(free), "reserved_rub": float(row.get("reserved_rub") or 0)},
        "traffic": {
            "sample_days": 35, "comparison_windows": n, "sample_orders": len(samples),
            "matching_created": len(matches), "matching_paid": len(paid),
            "probability_15m": probabilities["15"] if samples else None,
            "probability_30m": probabilities["30"] if samples else None,
            "probability_60m": probabilities["60"] if samples else None,
            "payment_conversion": round(len(paid) / len(resolved), 4) if resolved else None,
            "resolved_orders": len(resolved),
            "confidence": "none" if not samples else "medium" if len(matches) >= 30 else "low",
            "source": "general_buy_history" if use_same else "fallback" if samples else "none",
            "method": candidate.method, "all_crypto": True,
            "typical_rub": [min(paid_amounts), max(paid_amounts)] if paid_amounts else [],
            "payment_sequences": sorted(solutions, key=len)[:3],
            "model": "historical_windows",
            "limitations": "Поток созданных BUY с известным способом оплаты, без ручных OP-заявок. "
                "История покупателя на момент попытки и конкуренция реквизитов не восстановлены. "
                "Подгонка предполагает согласие покупателя. Это ориентир потока, не вероятность выдачи этой карте.",
        },
    }


async def diagnose(conn, row, *, now=None):
    now = utc(now or datetime.now(UTC))
    # UTC naive in orders; convert to MSK in Python, once. A 36-day read
    # covers 35 complete comparison windows including crossings of midnight.
    global _history_cache, _history_at
    async with _history_lock:
        if _history_cache is None or time.monotonic() - _history_at >= 60:
            _history_cache = await conn.fetch("""
        SELECT created_at, fiat_amount, sub_token, status
        FROM orders WHERE lower(direction) = 'buy'
          AND created_at >= $1 AND created_at < $2
          AND fiat_amount > 0 AND upper(order_id) NOT LIKE 'OP%'
          AND upper(sub_token) IN ('SBPRUB', 'CARDRUB')
            """, (now - timedelta(days=36)).replace(tzinfo=None), now.replace(tzinfo=None))
            _history_at = time.monotonic()
        history = _history_cache
    facts = dict(await conn.fetchrow("""
        SELECT count(*)::int AS assigned_count,
          count(*) FILTER (WHERE a.status='PAID')::int AS paid_count,
          count(*) FILTER (WHERE a.status='CANCELED')::int AS canceled_count,
          min(a.created_at) AS first_assigned_at, max(a.created_at) AS last_assigned_at,
          min(a.paid_at) AS first_paid_at,
          (array_agg(a.order_id ORDER BY a.created_at DESC, a.id DESC))[1] AS last_order_id,
          count(*) FILTER (WHERE o.order_id IS NULL OR o.payin_requisite_id IS DISTINCT FROM a.requisite_id)::int AS inconsistent_count
        FROM payout_requisite_allocations a LEFT JOIN orders o ON o.order_id=a.order_id
        WHERE a.requisite_id=$1 AND a.kind='payin'
    """, int(row["id"])))
    result = estimate({**dict(row), "first_paid_at": facts.pop("first_paid_at")}, history, now=now)
    facts["health"] = "error" if facts["inconsistent_count"] else "working" if facts["assigned_count"] else "no_data"
    for key in ("first_assigned_at", "last_assigned_at"):
        facts[key] = utc(facts[key]).isoformat() if facts[key] else None
    result["issuance"] = facts
    result["traffic"]["history_cache_age_seconds"] = round(time.monotonic() - _history_at)
    return result

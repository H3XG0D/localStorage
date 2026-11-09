"""Подбор SELL-заявок под реквизит оператора за минимальное число чеков.

Ядро (`build_plan`) чистое и работает в копейках, поэтому тестируется без БД.
DB-обёртки грузят кандидатов и пишут аудит в `payout_requisite_plans`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)

# Кандидатов ограничиваем сверху, иначе перебор троек деградирует на большом пуле.
CANDIDATE_LIMIT = 200
DEFAULT_WINDOW_MINUTES = 180
DEFAULT_DOLIV_LIMIT_RUB = 1000
DEFAULT_MAX_CHECKS = 3
# Payin на сумму до этой включительно живёт одним клиентским чеком, без долива.
ONE_CHECK_MAX_RUB = Decimal("2000")
# Первый час карты — только один клиентский чек, без долива.
FIRST_SOLO_MINUTES = 60
# Округление котировки вверх до остатка карты / цели слота (доля от котировки).
MATCH_ROUND_CAP_RUB = 150
MATCH_ROUND_PCT = Decimal("0.05")
# Точный перебор комбинаций — до троек; на больших max_checks добираем жадно.
EXACT_COMBINATION_DEPTH = 3

METHOD_SUB_TOKENS = {"card": "CARDRUB", "sbp": "SBPRUB"}

ACTIVE_REQUISITE_STATUSES = ("OPEN", "RESERVED", "PARTIAL")
LIST_REQUISITE_STATUSES = ("QUEUED",) + ACTIVE_REQUISITE_STATUSES
ACTIVE_ALLOCATION_STATUSES = ("RESERVED", "PAID")
CANDIDATE_ORDER_STATUSES = ("PENDING", "OPERATOR_PENDING")


def to_kop(value) -> int:
    """Рубли → копейки. Целые копейки — единственная единица внутри подбора."""
    return int((Decimal(str(value)) * 100).to_integral_value())


def from_kop(value: int) -> Decimal:
    return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))


def _as_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def requisite_age_minutes(created_at, *, now: datetime | None = None) -> float:
    created = _as_utc(created_at)
    if created is None:
        return FIRST_SOLO_MINUTES
    current = now or datetime.now(timezone.utc)
    current = _as_utc(current) or current
    return max(0.0, (current - created).total_seconds() / 60.0)


def in_solo_window(created_at, *, now: datetime | None = None) -> bool:
    return requisite_age_minutes(created_at, now=now) < FIRST_SOLO_MINUTES


def payin_one_check_only(amount) -> bool:
    """Сумма payin до 2000 ₽ закрывается одним чеком и без долива."""
    if amount is None or amount == "":
        return False
    try:
        value = Decimal(str(amount))
    except Exception:
        return False
    return value > 0 and value <= ONE_CHECK_MAX_RUB


def payin_stored_limits(
    amount,
    *,
    max_checks: int = DEFAULT_MAX_CHECKS,
    doliv_limit_rub: int = DEFAULT_DOLIV_LIMIT_RUB,
) -> tuple[int, int]:
    if payin_one_check_only(amount):
        return 1, 0
    return max(1, int(max_checks)), max(0, int(doliv_limit_rub))


def matcher_limits(row, *, now: datetime | None = None) -> tuple[int, int]:
    """Первый час: 1 чек и без долива. Потом — лимиты с карточки.

    Payin до 2000 ₽ остаётся одним чеком без долива всё время жизни.
    """
    max_checks = max(1, int((row or {}).get("max_checks") or DEFAULT_MAX_CHECKS))
    raw_doliv = (row or {}).get("doliv_limit_rub")
    doliv = int(raw_doliv) if raw_doliv is not None else DEFAULT_DOLIV_LIMIT_RUB
    direction = str((row or {}).get("direction") or "").lower()
    if direction == "payin" and payin_one_check_only((row or {}).get("amount_rub")):
        return 1, 0
    if in_solo_window((row or {}).get("created_at"), now=now):
        return 1, 0
    return max_checks, max(0, doliv)


@dataclass(frozen=True)
class Candidate:
    order_id: str
    amount_kop: int
    user_id: int | None = None
    crypto: str | None = None
    sub_token: str | None = None
    created_at: object | None = None
    requisites: str | None = None

    @property
    def amount_rub(self) -> Decimal:
        return from_kop(self.amount_kop)


@dataclass
class Plan:
    orders: list[Candidate] = field(default_factory=list)
    doliv_kop: int = 0
    leftover_kop: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def orders_kop(self) -> int:
        return sum(c.amount_kop for c in self.orders)

    @property
    def checks_count(self) -> int:
        """Сколько физических переводов: заявки + долив (он тоже чек)."""
        return len(self.orders) + (1 if self.doliv_kop else 0)

    @property
    def closes(self) -> bool:
        return self.leftover_kop == 0

    def score(self) -> tuple[int, int, int, int, int, int, int]:
        """Лексикографический score, меньше — лучше.

        Сначала закрывающие планы. Чистый долив без клиентов проигрывает любой
        клиентской схеме. Среди клиентских меньше заявок важнее меньшего числа
        физических переводов: один клиент (+ долив) бьёт двух точных клиентов.
        """
        return (
            0 if self.closes else 1,
            self.leftover_kop,
            0 if self.orders else 1,
            len(self.orders) if self.orders else 99,
            self.checks_count,
            self.doliv_kop,
            -self.orders_kop,
        )

    def as_dict(self) -> dict:
        payload = {
            "orders": [
                {
                    "order_id": c.order_id,
                    "amount_rub": float(c.amount_rub),
                    "user_id": c.user_id,
                    "crypto": c.crypto,
                    "synthetic": str(c.order_id).startswith("typ:"),
                }
                for c in self.orders
            ],
            "checks_count": self.checks_count,
            "orders_count": len(self.orders),
            "orders_sum_rub": float(from_kop(self.orders_kop)),
            "doliv_rub": float(from_kop(self.doliv_kop)),
            "leftover_rub": float(from_kop(self.leftover_kop)),
            "closes": self.closes,
        }
        if self.extra:
            payload.update(self.extra)
        return payload


def _make_plan(
    orders: Sequence[Candidate],
    remaining_kop: int,
    doliv_limit_kop: int,
    max_checks: int,
) -> Plan:
    total = sum(c.amount_kop for c in orders)
    gap = remaining_kop - total
    if gap < 0:
        raise ValueError("combination exceeds remaining amount")
    # Долив — отдельный физический чек; не выходим за max_checks.
    slots_left = int(max_checks) - len(orders)
    doliv = gap if slots_left >= 1 and 0 < gap <= doliv_limit_kop else 0
    return Plan(orders=list(orders), doliv_kop=doliv, leftover_kop=gap - doliv)


def _best(current: Plan | None, contender: Plan) -> Plan:
    if current is None or contender.score() < current.score():
        return contender
    return current


def _best_pair(pool: list[Candidate], remaining_kop: int) -> list[Candidate] | None:
    """Пара с максимальной суммой, не превышающей остаток (pool отсортирован по возрастанию)."""
    best: list[Candidate] | None = None
    best_sum = -1
    left, right = 0, len(pool) - 1
    while left < right:
        total = pool[left].amount_kop + pool[right].amount_kop
        if total > remaining_kop:
            right -= 1
            continue
        if total > best_sum:
            best_sum = total
            best = [pool[left], pool[right]]
        left += 1
    return best


def _best_triple(pool: list[Candidate], remaining_kop: int) -> list[Candidate] | None:
    best: list[Candidate] | None = None
    best_sum = -1
    n = len(pool)
    for i in range(n - 2):
        head = pool[i]
        # pool отсортирован по возрастанию: если даже три минимальных не влезают,
        # дальше суммы только растут.
        if head.amount_kop * 3 > remaining_kop:
            break
        budget = remaining_kop - head.amount_kop
        left, right = i + 1, n - 1
        while left < right:
            total = pool[left].amount_kop + pool[right].amount_kop
            if total > budget:
                right -= 1
                continue
            if head.amount_kop + total > best_sum:
                best_sum = head.amount_kop + total
                best = [head, pool[left], pool[right]]
            left += 1
    return best


def _greedy_fill(pool: list[Candidate], remaining_kop: int, max_items: int) -> list[Candidate] | None:
    """Жадно добираем от крупных к мелким — страховка для max_checks > 3."""
    picked: list[Candidate] = []
    budget = remaining_kop
    for cand in sorted(pool, key=lambda c: c.amount_kop, reverse=True):
        if len(picked) >= max_items:
            break
        if cand.amount_kop <= budget:
            picked.append(cand)
            budget -= cand.amount_kop
    return picked or None


def build_plan(
    remaining_rub,
    candidates: Iterable[Candidate],
    *,
    max_checks: int = DEFAULT_MAX_CHECKS,
    doliv_limit_rub=DEFAULT_DOLIV_LIMIT_RUB,
) -> Plan | None:
    """Лучший план закрытия остатка. None — если закрыть нечем совсем."""
    remaining_kop = to_kop(remaining_rub)
    if remaining_kop <= 0:
        return None
    doliv_limit_kop = to_kop(doliv_limit_rub)
    max_checks = max(1, int(max_checks))

    pool = sorted(
        (c for c in candidates if 0 < c.amount_kop <= remaining_kop),
        key=lambda c: c.amount_kop,
    )

    best: Plan | None = None

    # Чистый долив: возможен только если остаток целиком в лимите доливщика.
    if 0 < remaining_kop <= doliv_limit_kop:
        best = _best(best, _make_plan([], remaining_kop, doliv_limit_kop, max_checks))

    if not pool:
        return best

    for cand in pool:
        best = _best(best, _make_plan([cand], remaining_kop, doliv_limit_kop, max_checks))

    if max_checks >= 2:
        pair = _best_pair(pool, remaining_kop)
        if pair:
            best = _best(best, _make_plan(pair, remaining_kop, doliv_limit_kop, max_checks))

    if max_checks >= 3:
        triple = _best_triple(pool, remaining_kop)
        if triple:
            best = _best(best, _make_plan(triple, remaining_kop, doliv_limit_kop, max_checks))

    if max_checks > EXACT_COMBINATION_DEPTH:
        greedy = _greedy_fill(pool, remaining_kop, max_checks)
        if greedy:
            best = _best(best, _make_plan(greedy, remaining_kop, doliv_limit_kop, max_checks))

    return best


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

REQUISITE_COLUMNS = """
    id, operator_id, label, direction, method, requisites, bank, holder_name,
    amount_rub, cost_pct, crypto, paid_rub, max_checks, doliv_limit_rub,
    status, deadline_at, closed_at, close_note, confirmed_at, confirmed_by,
    source_sell_order_id, source_withdrawal_id, client_due_rub, subsidy_cap_rub,
    created_at, updated_at
"""


def _row_field(row, key: str):
    if row is None:
        return None
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key)
    try:
        return row[key]
    except Exception:
        return None


def is_triangle_row(row) -> bool:
    """Payin card linked to a SELL or to a card withdrawal."""
    if bool(str(_row_field(row, "source_sell_order_id") or "").strip()):
        return True
    withdrawal_id = _row_field(row, "source_withdrawal_id")
    return withdrawal_id not in (None, "")


def remaining_rub(row) -> Decimal:
    amount = Decimal(str(row["amount_rub"]))
    paid = Decimal(str(row["paid_rub"] or 0))
    return (amount - paid).quantize(Decimal("0.01"))


async def reserved_kop(conn, requisite_id: int) -> int:
    value = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'RESERVED'
        """,
        int(requisite_id),
    )
    return to_kop(value or 0)


async def unreserved_remaining_rub(conn, row) -> Decimal:
    """Остаток минус уже забронированное — именно под него ищем новый план."""
    free_kop = to_kop(remaining_rub(row)) - await reserved_kop(conn, int(row["id"]))
    return from_kop(max(0, free_kop))


_POOL_ORDERS_SQL = """
        SELECT o.order_id, o.user_id, o.fiat_amount, o.crypto, o.sub_token,
               o.requisites, o.created_at
        FROM orders o
        WHERE lower(o.direction) = 'sell'
          AND o.status = ANY($1::text[])
          -- Рубли уходят только после подтверждения прихода крипты оператором.
          AND o.crypto_confirmed_at IS NOT NULL
          AND (o.expires_at IS NULL OR o.expires_at > now())
          AND ($2::text IS NULL OR o.sub_token IS NULL OR upper(o.sub_token) = $2)
          AND o.fiat_amount > 0
          AND ($3::numeric IS NULL OR o.fiat_amount <= $3)
          AND NOT EXISTS (
              SELECT 1 FROM payout_requisite_allocations a
              WHERE a.order_id = o.order_id AND a.status = ANY($4::text[])
          )
          -- Карта этого продавца уже стоит под BUY — не платим с другой карты.
          AND NOT EXISTS (
              SELECT 1 FROM operator_payout_requisites r
              WHERE r.source_sell_order_id = o.order_id
                AND r.status = ANY($5::text[])
          )
        ORDER BY o.fiat_amount DESC, o.created_at ASC
        LIMIT $6
"""


def _candidates_from_rows(rows) -> list[Candidate]:
    out: list[Candidate] = []
    for r in rows:
        raw_req = r["requisites"] if "requisites" in r else None
        out.append(
            Candidate(
                order_id=str(r["order_id"]),
                amount_kop=to_kop(r["fiat_amount"]),
                user_id=r["user_id"],
                crypto=r["crypto"],
                sub_token=r["sub_token"],
                created_at=r["created_at"],
                requisites=str(raw_req).strip() if raw_req else None,
            )
        )
    return out


def pool_order_payload(candidate: Candidate) -> dict:
    created = candidate.created_at
    created_at = created.isoformat() if hasattr(created, "isoformat") else created
    return {
        "order_id": candidate.order_id,
        "fiat_amount": float(candidate.amount_rub),
        "crypto": candidate.crypto,
        "sub_token": candidate.sub_token,
        "requisites": candidate.requisites,
        "created_at": created_at,
    }


async def load_pool_orders(
    conn,
    *,
    method: str | None = None,
    max_amount_rub=None,
    limit: int = CANDIDATE_LIMIT,
) -> list[Candidate]:
    """SELL в пуле выплат: крипта подтверждена, без активной брони на карте."""
    sub_token = METHOD_SUB_TOKENS.get(str(method).lower()) if method else None
    cap = Decimal(str(max_amount_rub)) if max_amount_rub is not None else None
    rows = await conn.fetch(
        _POOL_ORDERS_SQL,
        list(CANDIDATE_ORDER_STATUSES),
        sub_token,
        cap,
        list(ACTIVE_ALLOCATION_STATUSES),
        list(LIST_REQUISITE_STATUSES),
        int(limit),
    )
    return _candidates_from_rows(rows)


async def load_candidates(
    conn,
    *,
    method: str,
    max_amount_rub,
    limit: int = CANDIDATE_LIMIT,
) -> list[Candidate]:
    return await load_pool_orders(
        conn,
        method=method,
        max_amount_rub=max_amount_rub,
        limit=limit,
    )


async def plan_for_requisite(conn, row) -> tuple[Plan | None, Decimal]:
    direction = str(row.get("direction") or "payout").lower()
    triangle = is_triangle_row(row)
    if direction == "payin" and not triangle:
        from payin_fill_forecast import forecast_payin_plan

        return await forecast_payin_plan(conn, row)
    free = await unreserved_remaining_rub(conn, row)
    if free <= 0:
        return None, free
    candidates: list[Candidate] = []
    if direction != "payin":
        candidates = await load_candidates(
            conn,
            method=row["method"],
            max_amount_rub=free,
        )
    max_checks, doliv_limit_rub = matcher_limits(row)
    plan = build_plan(
        free,
        candidates,
        max_checks=max_checks,
        doliv_limit_rub=doliv_limit_rub,
    )
    if in_solo_window(row.get("created_at")) and plan is not None and not plan.closes:
        plan = None
    if plan is not None and triangle:
        plan.extra["kind"] = "triangle"
        sell_id = str(row.get("source_sell_order_id") or "").strip()
        if sell_id:
            plan.extra["source_sell_order_id"] = sell_id
        withdrawal_id = row.get("source_withdrawal_id")
        if withdrawal_id not in (None, ""):
            plan.extra["source_withdrawal_id"] = int(withdrawal_id)
    return plan, free


async def store_plan(conn, requisite_id: int, plan: Plan | None, free_rub: Decimal) -> None:
    payload = plan.as_dict() if plan else {"orders": [], "closes": False}
    payload["free_rub"] = float(free_rub)
    await conn.execute(
        """
        INSERT INTO payout_requisite_plans
            (requisite_id, plan, checks_count, doliv_rub, leftover_rub)
        VALUES ($1, $2::jsonb, $3, $4, $5)
        """,
        int(requisite_id),
        json.dumps(payload, ensure_ascii=False),
        int(plan.checks_count) if plan else 0,
        from_kop(plan.doliv_kop) if plan else Decimal("0.00"),
        from_kop(plan.leftover_kop) if plan else free_rub,
    )


async def latest_plan(conn, requisite_id: int) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT plan, checks_count, doliv_rub, leftover_rub, computed_at, is_applied
        FROM payout_requisite_plans
        WHERE requisite_id = $1
        ORDER BY computed_at DESC, id DESC
        LIMIT 1
        """,
        int(requisite_id),
    )
    if not row:
        return None
    raw = row["plan"]
    payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    payload["computed_at"] = row["computed_at"].isoformat() if row["computed_at"] else None
    payload["is_applied"] = bool(row["is_applied"])
    return payload


async def recompute_plan(pool, requisite_id: int) -> dict | None:
    """Пересчитать и сохранить план по одному реквизиту."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites WHERE id = $1",
            int(requisite_id),
        )
        if not row or row["status"] not in ACTIVE_REQUISITE_STATUSES:
            return None
        plan, free = await plan_for_requisite(conn, row)
        await store_plan(conn, int(row["id"]), plan, free)
    payload = plan.as_dict() if plan else {"orders": [], "closes": False}
    payload["free_rub"] = float(free)
    return payload


async def active_requisites(conn) -> list:
    return await conn.fetch(
        f"""
        SELECT {REQUISITE_COLUMNS}
        FROM operator_payout_requisites
        WHERE status = ANY($1::text[])
          AND COALESCE(direction, 'payout') = 'payout'
        ORDER BY deadline_at ASC
        """,
        list(ACTIVE_REQUISITE_STATUSES),
    )


async def active_payin_requisites(conn) -> list:
    """Открытые и очередные карты приёма — для прогноза заливки, не для SELL-snap."""
    return await conn.fetch(
        f"""
        SELECT {REQUISITE_COLUMNS}
        FROM operator_payout_requisites
        WHERE status = ANY($1::text[])
          AND COALESCE(direction, 'payout') = 'payin'
        ORDER BY deadline_at ASC
        """,
        list(LIST_REQUISITE_STATUSES),
    )

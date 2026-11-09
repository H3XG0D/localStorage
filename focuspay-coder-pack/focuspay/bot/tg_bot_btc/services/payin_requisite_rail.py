"""BUY-пейин на карты реквизитчиков. Зеркало exchange-backend/payin_requisite_rail.py."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

DIRECTION_PAYIN = "payin"
DIRECTION_PAYOUT = "payout"
DEFAULT_MIN_BUY_PAID = 3
ROUND_UP_CAP_RUB = 500
PAYIN_PAYMENT_WINDOW_MINUTES = 30
DEFAULT_CRYPTO = "usdt"
FIRST_SOLO_MINUTES = 60
MATCH_ROUND_CAP_RUB = 150
FAT_FIRST_MIN_RUB = 8000
FAT_FIRST_SHARE = Decimal("0.40")
HUNT_MINUTES = 45
HUNT_CLOSE_SHARE = Decimal("0.80")
HUNT_TAIL_MINUTES = 90
MIN_LEFTOVER_AFTER_FAT_RUB = 2000
ONE_CHECK_MAX_RUB = Decimal("2000")
BAND_FLOOR_PCT = Decimal("0.90")
BAND_PROFIT_SHARE = Decimal("0.05")

ACTIVE_REQUISITE_STATUSES = ("OPEN", "RESERVED", "PARTIAL")
ACTIVE_ALLOCATION_STATUSES = ("RESERVED", "PAID")
METHOD_SUB_TOKENS = {"card": "CARDRUB", "sbp": "SBPRUB"}
SUB_TOKEN_METHODS = {v: k for k, v in METHOD_SUB_TOKENS.items()}

REQUISITE_COLUMNS = """
    id, operator_id, label, direction, method, requisites, bank, holder_name,
    amount_rub, cost_pct, crypto, paid_rub, max_checks, doliv_limit_rub,
    status, deadline_at, closed_at, close_note, confirmed_at, confirmed_by,
    source_sell_order_id, source_withdrawal_id, client_due_rub, subsidy_cap_rub,
    created_at, updated_at
"""


def to_kop(value) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


def from_kop(value: int) -> Decimal:
    return (Decimal(int(value)) / 100).quantize(Decimal("0.01"))


def remaining_rub(row) -> Decimal:
    amount = Decimal(str(row["amount_rub"]))
    paid = Decimal(str(row["paid_rub"] or 0))
    return (amount - paid).quantize(Decimal("0.01"))


def payin_card_fee_pct(cost_pct) -> float:
    return float(Decimal(str(cost_pct or 0)) / 100)


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
    if bool(str(_row_field(row, "source_sell_order_id") or "").strip()):
        return True
    return _row_field(row, "source_withdrawal_id") not in (None, "")


def band_floor_rub(nominal) -> Decimal:
    amount = Decimal(str(nominal or 0))
    if amount <= 0:
        return Decimal("0.00")
    return (amount * BAND_FLOOR_PCT).quantize(Decimal("0.01"))


def subsidy_cap_from_profit(profit) -> Decimal:
    value = Decimal(str(profit or 0))
    if value <= 0:
        return Decimal("0.00")
    return (value * BAND_PROFIT_SHARE).quantize(Decimal("0.01"))


def estimated_buy_profit_rub(nominal) -> Decimal:
    amount = Decimal(str(nominal or 0))
    if amount <= 0:
        return Decimal("0.00")
    from services.runtime_settings import buy_markup

    markup = Decimal(str(buy_markup(manual=False, amount_rub=float(amount))))
    if markup <= 1:
        return Decimal("0.00")
    return (amount * (markup - Decimal(1)) / markup).quantize(Decimal("0.01"))


def frozen_subsidy_cap_rub(nominal) -> Decimal:
    return subsidy_cap_from_profit(estimated_buy_profit_rub(nominal))


def triangle_band_notice(*, due, nominal, cap) -> str:
    promised = Decimal(str(due or 0)).quantize(Decimal("0.01"))
    card = Decimal(str(nominal or 0)).quantize(Decimal("0.01"))
    ceiling = (card + Decimal(str(cap or 0))).quantize(Decimal("0.01"))
    floor = band_floor_rub(card)
    return (
        f"На карту может прийти от {floor:.0f} до {ceiling:.0f} ₽. "
        f"Если меньше {promised:.0f} ₽ — недостающее зачислим на баланс. "
        "Если больше — разницу доплатит FocusPay."
    )


def band_short_closes(row, paid_kop: int, paid_checks: int) -> bool:
    if _row_field(row, "client_due_rub") in (None, ""):
        return False
    if not is_triangle_row(row):
        return False
    if int(paid_checks) != 1:
        return False
    nominal = to_kop(_row_field(row, "amount_rub") or 0)
    paid = int(paid_kop)
    if nominal <= 0 or paid <= 0 or paid >= nominal:
        return False
    floor = to_kop(band_floor_rub(from_kop(nominal)))
    cap = to_kop(_row_field(row, "subsidy_cap_rub") or 0)
    return floor <= paid <= nominal + cap


def is_payin_order(row) -> bool:
    return row is not None and row.get("payin_requisite_id") is not None


def bill_from_requisite(row) -> dict:
    return {
        "bank": str(row.get("bank") or "").strip(),
        "reciver": str(row.get("requisites") or "").strip(),
        "fio": str(row.get("holder_name") or "").strip(),
    }


def payin_min_buy_paid() -> int:
    try:
        from services.runtime_settings import get_settings_sync

        return max(
            0,
            int(get_settings_sync().get("payin_requisite_min_buy_paid", DEFAULT_MIN_BUY_PAID)),
        )
    except Exception:
        return DEFAULT_MIN_BUY_PAID


@dataclass(frozen=True)
class PayinCandidate:
    id: int
    operator_id: int
    method: str
    requisites: str
    bank: str | None
    holder_name: str | None
    cost_pct: Decimal
    crypto: str
    deadline_at: datetime | None
    max_checks: int
    free_rub: Decimal
    used_checks: int
    created_at: datetime | None = None
    first_paid_at: datetime | None = None
    doliv_limit_rub: int = 1000
    amount_rub: Decimal | None = None
    from_withdrawal: bool = False
    is_triangle: bool = False
    client_due_rub: Decimal | None = None
    subsidy_cap_rub: Decimal | None = None


def payin_one_check_only(amount) -> bool:
    if amount is None or amount == "":
        return False
    try:
        value = Decimal(str(amount))
    except Exception:
        return False
    return value > 0 and value <= ONE_CHECK_MAX_RUB


def payin_stored_limits(amount, *, max_checks: int, doliv_limit_rub: int) -> tuple[int, int]:
    if payin_one_check_only(amount):
        return 1, 0
    return max(1, int(max_checks)), max(0, int(doliv_limit_rub))


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
    current = _as_utc(now) or datetime.now(timezone.utc)
    return max(0.0, (current - created).total_seconds() / 60.0)


def in_solo_window(created_at, *, now: datetime | None = None) -> bool:
    return requisite_age_minutes(created_at, now=now) < FIRST_SOLO_MINUTES


def _now_utc(now: datetime | None = None) -> datetime:
    return _as_utc(now) or datetime.now(timezone.utc)


def fat_first_min_kop(free_kop: int) -> int:
    share = int((Decimal(max(0, int(free_kop))) * FAT_FIRST_SHARE).to_integral_value())
    return max(to_kop(FAT_FIRST_MIN_RUB), share)


def is_fat_partial(quote_kop: int, free_kop: int) -> bool:
    gap = int(free_kop) - int(quote_kop)
    return int(quote_kop) >= fat_first_min_kop(free_kop) and gap >= to_kop(MIN_LEFTOVER_AFTER_FAT_RUB)


def hunt_closes(quote_kop: int, free_kop: int) -> bool:
    if int(free_kop) <= 0 or int(quote_kop) <= 0:
        return False
    return int(quote_kop) * 100 >= int(free_kop) * int(HUNT_CLOSE_SHARE * 100)


def in_hunt_window(candidate: PayinCandidate, *, now: datetime | None = None) -> bool:
    if int(candidate.used_checks or 0) != 1:
        return False
    paid = _as_utc(candidate.first_paid_at)
    if paid is None:
        return False
    elapsed = (_now_utc(now) - paid).total_seconds() / 60.0
    return 0 <= elapsed < HUNT_MINUTES


def hunt_finished(candidate: PayinCandidate, *, now: datetime | None = None) -> bool:
    if int(candidate.used_checks or 0) < 1:
        return False
    paid = _as_utc(candidate.first_paid_at)
    if paid is None:
        return False
    return (_now_utc(now) - paid).total_seconds() / 60.0 >= HUNT_MINUTES


def payin_followup_deadline(*, now: datetime | None = None) -> datetime:
    return _now_utc(now) + timedelta(minutes=HUNT_MINUTES + HUNT_TAIL_MINUTES)


def payin_keep_open(row, *, first_paid_at=None, now: datetime | None = None) -> bool:
    if remaining_rub(row) <= 0:
        return False
    if Decimal(str(row.get("paid_rub") or 0)) <= 0:
        return False
    paid = _as_utc(first_paid_at)
    if paid is None:
        return True
    return _now_utc(now) < paid + timedelta(minutes=HUNT_MINUTES + HUNT_TAIL_MINUTES)


def closes_with_doliv(candidate: PayinCandidate, quote_kop: int, *, now: datetime | None = None) -> bool:
    leftover = to_kop(candidate.free_rub) - int(quote_kop)
    if leftover <= 0:
        return False
    if in_solo_window(candidate.created_at, now=now):
        return False
    return leftover <= to_kop(candidate.doliv_limit_rub or 0)


def allows_partial(candidate: PayinCandidate, quote_kop: int, *, now: datetime | None = None) -> bool:
    free_kop = to_kop(candidate.free_rub)
    if quote_kop <= 0 or quote_kop > free_kop:
        return False
    if payin_one_check_only(candidate.amount_rub):
        return False
    if in_hunt_window(candidate, now=now):
        return hunt_closes(quote_kop, free_kop) or closes_with_doliv(candidate, quote_kop, now=now)
    if is_fat_partial(quote_kop, free_kop):
        return True
    if closes_with_doliv(candidate, quote_kop, now=now):
        return True
    if not in_solo_window(candidate.created_at, now=now):
        return True
    return hunt_finished(candidate, now=now)


@dataclass(frozen=True)
class PayinFit:
    kind: str
    candidate: PayinCandidate | None
    quote_rub: Decimal
    pay_rub: Decimal
    credit_rub: Decimal
    offer_mode: str = "none"
    closes: bool = False
    subsidy_rub: Decimal = Decimal("0.00")

    @property
    def offer(self) -> bool:
        return self.kind == "round_up" and self.credit_rub > 0 and self.offer_mode in ("silent", "happy")

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "offer": self.offer,
            "offer_mode": self.offer_mode,
            "closes": self.closes,
            "quote_rub": float(self.quote_rub),
            "pay_rub": float(self.pay_rub),
            "credit_rub": float(self.credit_rub),
            "subsidy_rub": float(self.subsidy_rub),
        }


def round_cap_kop(quote_kop: int) -> int:
    """Допуск подгонки: фикс ROUND_UP_CAP_RUB, не больше самой котировки.
    Зеркало exchange-backend/payin_requisite_rail.py."""
    quote = max(0, int(quote_kop))
    if quote <= 0:
        return 1
    return max(1, min(to_kop(ROUND_UP_CAP_RUB), quote))


def slot_target_kop(candidate: PayinCandidate) -> int:
    checks_left = max(1, int(candidate.max_checks or 1) - int(candidate.used_checks or 0))
    free = to_kop(candidate.free_rub)
    if free <= 0:
        return 0
    return free // checks_left


def _fit(
    kind: str,
    candidate: PayinCandidate | None,
    quote: Decimal,
    pay: Decimal,
    credit: Decimal,
    *,
    offer_mode: str = "none",
    closes: bool = False,
    subsidy: Decimal | None = None,
) -> PayinFit:
    return PayinFit(
        kind,
        candidate,
        quote,
        pay,
        credit,
        offer_mode=offer_mode,
        closes=closes,
        subsidy_rub=subsidy if subsidy is not None else Decimal("0.00"),
    )


def _deadline_sort(value: datetime | None) -> datetime:
    deadline = value or datetime.max.replace(tzinfo=timezone.utc)
    if deadline.tzinfo is None:
        return deadline.replace(tzinfo=timezone.utc)
    return deadline.astimezone(timezone.utc)


def _empty_fit(quote: Decimal) -> PayinFit:
    return _fit("none", None, quote, quote, Decimal("0.00"))


def _triangle_band_fit(
    candidates: list[PayinCandidate],
    quote: Decimal,
    buy_profit_rub,
) -> PayinFit | None:
    quote_kop = to_kop(quote)
    live_cap = None
    if buy_profit_rub is not None:
        live_cap = to_kop(subsidy_cap_from_profit(buy_profit_rub))
    ranked: list[tuple[tuple, PayinCandidate, str, int]] = []
    for candidate in candidates:
        if (
            not candidate.is_triangle
            or candidate.client_due_rub is None
            or int(candidate.used_checks or 0) != 0
        ):
            continue
        nominal = to_kop(candidate.amount_rub if candidate.amount_rub is not None else candidate.free_rub)
        if nominal <= 0 or to_kop(candidate.free_rub) < nominal:
            continue
        floor = to_kop(band_floor_rub(from_kop(nominal)))
        cap = to_kop(candidate.subsidy_cap_rub or 0)
        if live_cap is not None:
            cap = min(cap, live_cap)
        if quote_kop < floor or quote_kop == nominal:
            continue
        if quote_kop < nominal:
            gap = nominal - quote_kop
            ranked.append(((gap, 0, _deadline_sort(candidate.deadline_at), int(candidate.id)), candidate, "short", gap))
        elif quote_kop <= nominal + cap:
            gap = quote_kop - nominal
            ranked.append(((gap, 1, _deadline_sort(candidate.deadline_at), int(candidate.id)), candidate, "long", gap))
    if not ranked:
        return None
    _key, chosen, side, gap = min(ranked, key=lambda item: item[0])
    if side == "short":
        return _fit("band", chosen, quote, quote, Decimal("0.00"), closes=True)
    return _fit("band", chosen, quote, quote, Decimal("0.00"), closes=True, subsidy=from_kop(gap))


def fit_payin(
    candidates: list[PayinCandidate],
    amount_rub,
    *,
    now: datetime | None = None,
    buy_profit_rub=None,
) -> PayinFit:
    quote = Decimal(str(amount_rub)).quantize(Decimal("0.01"))
    quote_kop = to_kop(quote)
    if quote_kop <= 0:
        return _empty_fit(quote)
    cap_kop = round_cap_kop(quote_kop)
    eligible = [
        c
        for c in candidates
        if to_kop(c.free_rub) >= quote_kop and c.used_checks < max(1, int(c.max_checks or 1))
    ]

    def free_gap(c: PayinCandidate) -> int:
        return to_kop(c.free_rub) - quote_kop

    exact = [c for c in eligible if free_gap(c) == 0]
    if exact:
        chosen = min(exact, key=lambda c: (_deadline_sort(c.deadline_at), int(c.id)))
        return _fit("exact", chosen, quote, quote, Decimal("0.00"), closes=True)

    banded = _triangle_band_fit(candidates, quote, buy_profit_rub)
    if banded is not None:
        return banded

    happy = [c for c in eligible if not c.is_triangle and 0 < free_gap(c) <= cap_kop]
    if happy:
        chosen = min(happy, key=lambda c: (free_gap(c), _deadline_sort(c.deadline_at), int(c.id)))
        return _fit(
            "round_up",
            chosen,
            quote,
            chosen.free_rub,
            from_kop(free_gap(chosen)),
            offer_mode="happy",
            closes=True,
        )

    partial = [
        c
        for c in eligible
        if not c.is_triangle and free_gap(c) > cap_kop and allows_partial(c, quote_kop, now=now)
    ]
    if partial:
        chosen = min(partial, key=lambda c: (free_gap(c), _deadline_sort(c.deadline_at), int(c.id)))
        return _fit("as_quoted", chosen, quote, quote, Decimal("0.00"), closes=False)

    silent_pool: list[tuple[PayinCandidate, int]] = []
    for c in eligible:
        if c.is_triangle:
            continue
        target = slot_target_kop(c)
        free = to_kop(c.free_rub)
        if target <= quote_kop or target >= free:
            continue
        bump = target - quote_kop
        if 0 < bump <= cap_kop:
            silent_pool.append((c, bump))
    if silent_pool:
        chosen, bump = min(
            silent_pool,
            key=lambda item: (item[1], _deadline_sort(item[0].deadline_at), int(item[0].id)),
        )
        return _fit(
            "round_up",
            chosen,
            quote,
            from_kop(slot_target_kop(chosen)),
            from_kop(bump),
            offer_mode="silent",
            closes=False,
        )

    return _empty_fit(quote)


def pick_payin_candidate(
    candidates: list[PayinCandidate],
    amount_rub,
    *,
    now: datetime | None = None,
    accept_round_up: bool = False,
) -> PayinCandidate | None:
    fit = fit_payin(candidates, amount_rub, now=now)
    if fit.kind in ("exact", "as_quoted", "band"):
        return fit.candidate
    if fit.kind == "round_up" and (accept_round_up or fit.offer_mode == "silent"):
        return fit.candidate
    return None


async def buy_paid_count(conn, user_id: int) -> int:
    if not user_id:
        return 0
    value = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM orders
        WHERE user_id = $1
          AND lower(direction) = 'buy'
          AND status IN ('PAID', 'COMPLETED')
        """,
        int(user_id),
    )
    return int(value or 0)


async def user_can_use_payin_rail(conn, user_id: int) -> bool:
    return await buy_paid_count(conn, user_id) >= payin_min_buy_paid()


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


async def _used_checks(conn, requisite_id: int) -> int:
    value = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = ANY($2::text[])
        """,
        int(requisite_id),
        list(ACTIVE_ALLOCATION_STATUSES),
    )
    return int(value or 0)


async def _first_paid_at(conn, requisite_id: int):
    return await conn.fetchval(
        """
        SELECT MIN(paid_at)
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'PAID'
        """,
        int(requisite_id),
    )


async def load_payin_candidates(
    conn,
    *,
    method: str,
    for_update: bool = True,
) -> list[PayinCandidate]:
    lock = "FOR UPDATE SKIP LOCKED" if for_update else ""
    rows = await conn.fetch(
        f"""
        SELECT {REQUISITE_COLUMNS}
        FROM operator_payout_requisites
        WHERE COALESCE(direction, 'payout') = 'payin'
          AND status = ANY($1::text[])
          AND confirmed_at IS NOT NULL
          AND deadline_at > now()
          AND method = $2
        {lock}
        """,
        list(ACTIVE_REQUISITE_STATUSES),
        str(method).lower(),
    )
    out: list[PayinCandidate] = []
    for row in rows:
        rid = int(row["id"])
        open_reserve = await conn.fetchval(
            """
            SELECT 1 FROM payout_requisite_allocations
            WHERE requisite_id = $1 AND status = 'RESERVED'
            LIMIT 1
            """,
            rid,
        )
        if open_reserve:
            continue
        free_kop = to_kop(remaining_rub(row)) - await reserved_kop(conn, rid)
        if free_kop <= 0:
            continue
        amount = Decimal(str(row["amount_rub"] or 0))
        max_checks, doliv_limit = payin_stored_limits(
            amount,
            max_checks=int(row["max_checks"] or 1),
            doliv_limit_rub=int(row["doliv_limit_rub"] or 0),
        )
        out.append(
            PayinCandidate(
                id=rid,
                operator_id=int(row["operator_id"]),
                method=str(row["method"]),
                requisites=str(row["requisites"]),
                bank=row["bank"],
                holder_name=row["holder_name"],
                cost_pct=Decimal(str(row["cost_pct"] or 0)),
                crypto=str(row["crypto"] or DEFAULT_CRYPTO),
                deadline_at=row["deadline_at"],
                max_checks=max_checks,
                free_rub=(Decimal(free_kop) / 100).quantize(Decimal("0.01")),
                used_checks=await _used_checks(conn, rid),
                created_at=row["created_at"],
                first_paid_at=await _first_paid_at(conn, rid),
                doliv_limit_rub=doliv_limit,
                amount_rub=amount,
                from_withdrawal=_row_withdrawal(row),
                is_triangle=is_triangle_row(row),
                client_due_rub=(
                    Decimal(str(due)).quantize(Decimal("0.01"))
                    if (due := _row_field(row, "client_due_rub")) not in (None, "")
                    else None
                ),
                subsidy_cap_rub=(
                    Decimal(str(cap)).quantize(Decimal("0.01"))
                    if (cap := _row_field(row, "subsidy_cap_rub")) not in (None, "")
                    else None
                ),
            )
        )
    return out


def _methods_for_sub_token(sub_token: str) -> list[str]:
    wanted = (sub_token or "CARDRUB").upper()
    methods: list[str] = []
    primary = SUB_TOKEN_METHODS.get(wanted)
    if primary:
        methods.append(primary)
    if wanted == "CARDRUB" and "sbp" not in methods:
        methods.append("sbp")
    return methods


def _row_withdrawal(row) -> bool:
    try:
        raw = row["source_withdrawal_id"]
    except Exception:
        return False
    return raw not in (None, "")


async def collect_payin_pool(conn, sub_token: str, *, for_update: bool = True) -> list[PayinCandidate]:
    """Телефон вывода не отдаём покупке на карту. СБП-покупка его видит."""
    methods = _methods_for_sub_token(sub_token)
    primary = methods[0] if methods else ""
    pool: list[PayinCandidate] = []
    for method in methods:
        found = await load_payin_candidates(conn, method=method, for_update=for_update)
        if method != primary:
            found = [c for c in found if not c.from_withdrawal]
        pool.extend(found)
    return pool


async def payin_reviewer_on_shift() -> bool:
    """Полная смена (клиент + финансы). Ошибка проверки — карты нет."""
    try:
        from services.operator_availability import has_operator_on_shift

        return bool(await has_operator_on_shift())
    except Exception:
        logger.warning("payin rail shift check failed", exc_info=True)
        return False


async def preview_payin_fit(
    conn,
    *,
    amount_rub,
    sub_token: str,
    user_id: int,
    buy_profit_rub=None,
) -> PayinFit:
    quote = Decimal(str(amount_rub)).quantize(Decimal("0.01"))
    if not await payin_reviewer_on_shift():
        return _empty_fit(quote)
    if not await user_can_use_payin_rail(conn, user_id):
        return _empty_fit(quote)
    pool = await collect_payin_pool(conn, sub_token, for_update=False)
    return fit_payin(pool, quote, buy_profit_rub=buy_profit_rub)


async def reserve_payin_slot(
    conn,
    *,
    order_id: str,
    amount_rub,
    sub_token: str,
    operator_id: int | None = None,
    accept_round_up: bool = False,
    buy_profit_rub=None,
) -> tuple[PayinCandidate, PayinFit] | None:
    quote = Decimal(str(amount_rub)).quantize(Decimal("0.01"))
    pool = await collect_payin_pool(conn, sub_token, for_update=True)
    fit = fit_payin(pool, quote, buy_profit_rub=buy_profit_rub)
    if fit.candidate is None or fit.kind == "none":
        return None
    if fit.kind == "round_up" and not accept_round_up and fit.offer_mode != "silent":
        return None
    pay = fit.pay_rub
    credit = fit.credit_rub if fit.kind == "round_up" else Decimal("0.00")
    chosen = fit.candidate
    alloc_op = int(operator_id or chosen.operator_id)
    await conn.fetchrow(
        """
        INSERT INTO payout_requisite_allocations
            (requisite_id, order_id, kind, amount_rub, status, operator_id)
        VALUES ($1, $2, 'payin', $3, 'RESERVED', $4)
        RETURNING id
        """,
        chosen.id,
        str(order_id),
        pay,
        alloc_op,
    )
    await conn.execute(
        """
        UPDATE operator_payout_requisites
        SET status = CASE
                WHEN status = 'OPEN' THEN 'RESERVED'
                ELSE status
            END,
            updated_at = now()
        WHERE id = $1
        """,
        chosen.id,
    )
    return chosen, PayinFit(
        fit.kind,
        chosen,
        quote,
        pay,
        credit,
        offer_mode=fit.offer_mode,
        closes=fit.closes,
        subsidy_rub=fit.subsidy_rub,
    )


async def release_payin_allocation(conn, order_id: str) -> int | None:
    alloc = await conn.fetchrow(
        """
        UPDATE payout_requisite_allocations
        SET status = 'CANCELED', updated_at = now()
        WHERE order_id = $1 AND kind = 'payin' AND status = 'RESERVED'
        RETURNING id, requisite_id
        """,
        str(order_id),
    )
    if not alloc:
        return None
    await _refresh_payin_status(conn, int(alloc["requisite_id"]))
    return int(alloc["requisite_id"])


async def settle_payin_allocation(conn, order_id: str) -> int | None:
    alloc = await conn.fetchrow(
        """
        UPDATE payout_requisite_allocations
        SET status = 'PAID', paid_at = COALESCE(paid_at, now()), updated_at = now()
        WHERE order_id = $1 AND kind = 'payin' AND status = 'RESERVED'
        RETURNING id, requisite_id, amount_rub
        """,
        str(order_id),
    )
    if not alloc:
        return None
    requisite_id = int(alloc["requisite_id"])
    await conn.execute(
        """
        UPDATE operator_payout_requisites
        SET paid_rub = LEAST(paid_rub + $2, amount_rub + COALESCE(subsidy_cap_rub, 0)),
            updated_at = now()
        WHERE id = $1
        """,
        requisite_id,
        Decimal(str(alloc["amount_rub"])),
    )
    paid_n = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'PAID'
        """,
        requisite_id,
    )
    row = await conn.fetchrow(
        f"SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites WHERE id = $1",
        requisite_id,
    )
    if (
        row is not None
        and int(paid_n or 0) == 1
        and remaining_rub(row) > 0
        and not band_short_closes(row, to_kop(row["paid_rub"]), int(paid_n or 0))
    ):
        followup = payin_followup_deadline()
        await conn.execute(
            """
            UPDATE operator_payout_requisites
            SET deadline_at = GREATEST(deadline_at, $2), updated_at = now()
            WHERE id = $1
            """,
            requisite_id,
            followup,
        )
    await _refresh_payin_status(conn, requisite_id)
    return requisite_id


async def _refresh_payin_status(conn, requisite_id: int) -> None:
    row = await conn.fetchrow(
        f"SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites WHERE id = $1",
        int(requisite_id),
    )
    if not row or row["status"] in ("CLOSED", "CANCELED", "EXPIRED", "QUEUED"):
        return
    paid_kop = to_kop(row["paid_rub"] or 0)
    amount_kop = to_kop(row["amount_rub"])
    paid_checks = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'PAID'
        """,
        int(requisite_id),
    )
    if paid_kop >= amount_kop or band_short_closes(row, paid_kop, int(paid_checks or 0)):
        await conn.execute(
            """
            UPDATE operator_payout_requisites
            SET status = 'CLOSED', closed_at = COALESCE(closed_at, now()), updated_at = now()
            WHERE id = $1
            """,
            int(requisite_id),
        )
        return
    has_reserved = await reserved_kop(conn, requisite_id) > 0
    if has_reserved:
        status = "RESERVED"
    elif paid_kop > 0:
        status = "PARTIAL"
    else:
        status = "OPEN"
    await conn.execute(
        "UPDATE operator_payout_requisites SET status = $2, updated_at = now() WHERE id = $1",
        int(requisite_id),
        status,
    )


def payment_expires_at(deadline_at, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)
    window_end = current + timedelta(minutes=PAYIN_PAYMENT_WINDOW_MINUTES)
    if deadline_at is None:
        return window_end
    end = deadline_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    return min(end, window_end)

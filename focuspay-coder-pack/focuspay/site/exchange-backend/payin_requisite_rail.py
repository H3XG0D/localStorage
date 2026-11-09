"""BUY-пейин на карты реквизитчиков вместо провайдера карт.

Клиент с достаточным числом оплаченных покупок получает карту/СБП из пула
`direction='payin'`. Экономия идёт через `orders.card_fee_pct = cost_pct/100`,
а не отдельной проводкой в журнале: иначе комиссия задвоилась бы с PnL.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from payout_requisite_cost import DEFAULT_CRYPTO
from payout_requisite_matcher import (
    ACTIVE_ALLOCATION_STATUSES,
    ACTIVE_REQUISITE_STATUSES,
    DEFAULT_WINDOW_MINUTES,
    METHOD_SUB_TOKENS,
    REQUISITE_COLUMNS,
    _row_field,
    from_kop,
    in_solo_window,
    is_triangle_row,
    matcher_limits,
    payin_one_check_only,
    payin_stored_limits,
    remaining_rub,
    reserved_kop,
    to_kop,
)

logger = logging.getLogger(__name__)

DIRECTION_PAYIN = "payin"
DIRECTION_PAYOUT = "payout"
DEFAULT_MIN_BUY_PAID = 3
ROUND_UP_CAP_RUB = 500
PAYIN_PAYMENT_WINDOW_MINUTES = 30
FAT_FIRST_MIN_RUB = 8000
FAT_FIRST_SHARE = Decimal("0.40")
HUNT_MINUTES = 45
HUNT_CLOSE_SHARE = Decimal("0.80")
HUNT_TAIL_MINUTES = 90
MIN_LEFTOVER_AFTER_FAT_RUB = 2000
WITHDRAWAL_WAIT_MINUTES = 30
MANUAL_PAYOUT_NOTE = "выплатить вручную"
BAND_FLOOR_PCT = Decimal("0.90")
BAND_PROFIT_SHARE = Decimal("0.05")

SUB_TOKEN_METHODS = {v: k for k, v in METHOD_SUB_TOKENS.items()}


def requisite_direction(row) -> str:
    value = str((row or {}).get("direction") or DIRECTION_PAYOUT).strip().lower()
    return DIRECTION_PAYIN if value == DIRECTION_PAYIN else DIRECTION_PAYOUT


def is_payin_order(row) -> bool:
    return row is not None and row.get("payin_requisite_id") is not None


def order_reki_payfast_id(row) -> str:
    """UUID реки из снимка. В PayFast API его не подставляем."""
    if not row:
        return ""
    snap = _snapshot_dict(row.get("payment_snapshot"))
    return str(snap.get("reki_payfast_id") or "").strip()


def payin_card_fee_pct(cost_pct) -> float:
    """Дробь для `orders.card_fee_pct`: +3% → 0.03, −1% → −0.01."""
    return float(Decimal(str(cost_pct or 0)) / 100)


def band_floor_rub(nominal) -> Decimal:
    """Нижняя граница одного чека: 90% номинала карты."""
    amount = Decimal(str(nominal or 0))
    if amount <= 0:
        return Decimal("0.00")
    return (amount * BAND_FLOOR_PCT).quantize(Decimal("0.01"))


def subsidy_cap_from_profit(profit) -> Decimal:
    """Доплата FocusPay не больше 5% прибыли покупки."""
    value = Decimal(str(profit or 0))
    if value <= 0:
        return Decimal("0.00")
    return (value * BAND_PROFIT_SHARE).quantize(Decimal("0.01"))


def estimated_buy_profit_rub(nominal) -> Decimal:
    """Прибыль покупки на сумму карты при текущем авто-спреде, без комиссии карты и кешбэка."""
    amount = Decimal(str(nominal or 0))
    if amount <= 0:
        return Decimal("0.00")
    from runtime_settings import buy_markup

    markup = Decimal(str(buy_markup(manual=False, amount_rub=float(amount))))
    if markup <= 1:
        return Decimal("0.00")
    return (amount * (markup - Decimal(1)) / markup).quantize(Decimal("0.01"))


def frozen_subsidy_cap_rub(nominal) -> Decimal:
    """Потолок доплаты, который замораживается при открытии карты."""
    return subsidy_cap_from_profit(estimated_buy_profit_rub(nominal))


def triangle_band_notice(*, due, nominal, cap) -> str:
    """Текст клиенту: коридор его карты, не общий пример."""
    promised = Decimal(str(due or 0)).quantize(Decimal("0.01"))
    card = Decimal(str(nominal or 0)).quantize(Decimal("0.01"))
    ceiling = (card + Decimal(str(cap or 0))).quantize(Decimal("0.01"))
    floor = band_floor_rub(card)
    return (
        f"На карту может прийти от {floor:.0f} до {ceiling:.0f} ₽. "
        f"Если меньше {promised:.0f} ₽ — недостающее зачислим на баланс. "
        "Если больше — разницу доплатит FocusPay."
    )


def _money(value, default: Decimal | None = None) -> Decimal:
    if value in (None, ""):
        return default if default is not None else Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def triangle_balance_return(row) -> Decimal:
    """Недостача до обещания. Бонус продажи, который не пришёл на карту, не доплачиваем."""
    if _row_field(row, "client_due_rub") in (None, ""):
        return Decimal("0.00")
    paid = _money(_row_field(row, "paid_rub"))
    if paid <= 0:
        return Decimal("0.00")
    due = _money(_row_field(row, "client_due_rub"))
    return max(Decimal("0.00"), (due - paid).quantize(Decimal("0.01")))


def triangle_subsidy_amount(row) -> Decimal:
    """Сколько сверх номинала карты доплатил FocusPay."""
    nominal = _money(_row_field(row, "amount_rub"))
    paid = _money(_row_field(row, "paid_rub"))
    raw = max(Decimal("0.00"), (paid - nominal).quantize(Decimal("0.01")))
    cap = _money(_row_field(row, "subsidy_cap_rub"))
    if cap > 0:
        raw = min(raw, cap)
    return raw


def band_short_closes(row, paid_kop: int, paid_checks: int) -> bool:
    """Один чек внутри коридора ниже номинала закрывает карту."""
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


def payin_min_buy_paid() -> int:
    try:
        from runtime_settings import get_settings_sync

        return max(0, int(get_settings_sync().get("payin_requisite_min_buy_paid", DEFAULT_MIN_BUY_PAID)))
    except Exception:
        return DEFAULT_MIN_BUY_PAID


def bill_from_requisite(row) -> dict:
    return {
        "bank": str(row.get("bank") or "").strip(),
        "reciver": str(row.get("requisites") or "").strip(),
        "fio": str(row.get("holder_name") or "").strip(),
    }


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

    @property
    def leftover_rub(self) -> Decimal:
        return self.free_rub


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
    """Допуск подгонки: фикс ROUND_UP_CAP_RUB независимо от котировки.

    Решение владельца 2026-11-08: карта 3990 при котировке 3600 должна
    предлагаться (зазор 390). Процентный допуск (MATCH_ROUND_PCT) остаётся
    только у payout-матчера. Доплата не может превышать саму котировку.
    """
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
        subsidy_rub=subsidy or Decimal("0.00"),
    )


def _as_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _now_utc(now: datetime | None = None) -> datetime:
    current = _as_utc(now) or datetime.now(timezone.utc)
    return current


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
    """Не гасить payin с остатком, пока идёт охота и хвост на два мелких."""
    if remaining_rub(row) <= 0:
        return False
    if Decimal(str(row.get("paid_rub") or 0)) <= 0:
        return False
    paid = _as_utc(first_paid_at)
    if paid is None:
        return True
    return _now_utc(now) < paid + timedelta(minutes=HUNT_MINUTES + HUNT_TAIL_MINUTES)


def parse_sell_fiat_bill(text: str, *, sub_token: str | None = None) -> dict:
    """Карта/СБП продавца из свободного текста заявки → поля payin-реквизита."""
    raw = (text or "").strip()
    digits = re.sub(r"\D", "", raw)
    wanted = (sub_token or "").strip().upper()
    if wanted == "CARDRUB":
        method = "card"
    elif wanted == "SBPRUB":
        method = "sbp"
    elif len(digits) >= 16:
        method = "card"
    else:
        method = "sbp"
    if method == "card":
        requisites = digits[:19] if len(digits) >= 16 else digits
    else:
        requisites = digits
        if requisites.startswith("8") and len(requisites) == 11:
            requisites = "7" + requisites[1:]
    leftover = re.sub(r"[\d+\s\-().]+", " ", raw).strip()
    leftover = re.sub(r"\s+", " ", leftover)
    bank = leftover[:128] if len(leftover) >= 2 else "банк"
    clean = re.sub(r"\D", "", requisites)
    if method == "card" and len(clean) < 16:
        raise ValueError("Не разобрали номер карты продавца")
    if method == "sbp" and len(clean) < 10:
        raise ValueError("Не разобрали телефон СБП продавца")
    return {
        "method": method,
        "requisites": requisites,
        "bank": bank,
        "holder_name": "клиент",
    }


def closes_with_doliv(candidate: PayinCandidate, quote_kop: int, *, now: datetime | None = None) -> bool:
    leftover = to_kop(candidate.free_rub) - int(quote_kop)
    if leftover <= 0:
        return False
    _max, doliv_rub = matcher_limits(
        {
            "direction": "payin",
            "amount_rub": candidate.amount_rub,
            "max_checks": candidate.max_checks,
            "doliv_limit_rub": candidate.doliv_limit_rub,
            "created_at": candidate.created_at,
        },
        now=now,
    )
    del _max
    return leftover <= to_kop(doliv_rub)


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
    """Один чек на пустую карту треугольника: от 90% номинала и не выше потолка доплаты."""
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
    return _fit(
        "band",
        chosen,
        quote,
        quote,
        Decimal("0.00"),
        closes=True,
        subsidy=from_kop(gap),
    )


def fit_payin(
    candidates: list[PayinCandidate],
    amount_rub,
    *,
    now: datetime | None = None,
    buy_profit_rub=None,
) -> PayinFit:
    """exact / коридор треугольника / happy close ±5% / as_quoted / silent к цели слота ±5% / none."""
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

    def pick(pool: list[PayinCandidate], key) -> PayinCandidate:
        return min(pool, key=key)

    exact = [c for c in eligible if free_gap(c) == 0]
    if exact:
        chosen = pick(exact, lambda c: (_deadline_sort(c.deadline_at), int(c.id)))
        return _fit("exact", chosen, quote, quote, Decimal("0.00"), closes=True)

    banded = _triangle_band_fit(candidates, quote, buy_profit_rub)
    if banded is not None:
        return banded

    happy = [c for c in eligible if not c.is_triangle and 0 < free_gap(c) <= cap_kop]
    if happy:
        chosen = pick(happy, lambda c: (free_gap(c), _deadline_sort(c.deadline_at), int(c.id)))
        credit = from_kop(free_gap(chosen))
        return _fit(
            "round_up",
            chosen,
            quote,
            chosen.free_rub,
            credit,
            offer_mode="happy",
            closes=True,
        )

    partial = [
        c
        for c in eligible
        if not c.is_triangle and free_gap(c) > cap_kop and allows_partial(c, quote_kop, now=now)
    ]
    if partial:
        chosen = pick(partial, lambda c: (free_gap(c), _deadline_sort(c.deadline_at), int(c.id)))
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
        pay = from_kop(slot_target_kop(chosen))
        credit = from_kop(bump)
        return _fit(
            "round_up",
            chosen,
            quote,
            pay,
            credit,
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
    # silent — тихая доплата к цели слота, без явного оффера клиенту
    if fit.kind == "round_up" and (accept_round_up or fit.offer_mode == "silent"):
        return fit.candidate
    return None


async def buy_paid_count(conn, user_id: int) -> int:
    """Оплаченные BUY по `orders.user_id` — как в buyer_profile_service."""
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


async def _open_reserve_count(conn, requisite_id: int) -> int:
    value = await conn.fetchval(
        """
        SELECT COUNT(*)::int
        FROM payout_requisite_allocations
        WHERE requisite_id = $1 AND status = 'RESERVED'
        """,
        int(requisite_id),
    )
    return int(value or 0)


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
        # Один живой RESERVED на карту — следующий BUY только после PAID/cancel.
        if await _open_reserve_count(conn, rid) > 0:
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
        triangle = is_triangle_row(row)
        due_raw = _row_field(row, "client_due_rub")
        cap_raw = _row_field(row, "subsidy_cap_rub")
        cap = (
            Decimal(str(cap_raw)).quantize(Decimal("0.01"))
            if cap_raw not in (None, "")
            else None
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
                is_triangle=triangle,
                client_due_rub=(
                    Decimal(str(due_raw)).quantize(Decimal("0.01"))
                    if due_raw not in (None, "")
                    else None
                ),
                subsidy_cap_rub=cap,
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


async def collect_payin_pool(
    conn,
    sub_token: str,
    *,
    for_update: bool = True,
) -> list[PayinCandidate]:
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
        from operator_availability import has_operator_on_shift

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
    """Подобрать и забронировать payin-реквизит под BUY. None — пусто, идём на PayFast."""
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
    """Снять бронь, если клиент так и не заплатил. Возвращает id реквизита."""
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
    requisite_id = int(alloc["requisite_id"])
    await _refresh_payin_status(conn, requisite_id)
    return requisite_id


async def settle_payin_allocation(conn, order_id: str) -> int | None:
    """Рубли на карте подтверждены оператором — закрыть бронь и накрутить paid_rub."""
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
    from datetime import timedelta

    window_end = current + timedelta(minutes=PAYIN_PAYMENT_WINDOW_MINUTES)
    if deadline_at is None:
        return window_end
    end = deadline_at
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    return min(end, window_end)


TRIANGLE_SELL_STATUSES = ("PENDING", "OPERATOR_PENDING", "AWAITING_CHECK", "COMPLETED")


def _snapshot_dict(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return {}
    return dict(value) if isinstance(value, dict) else {}


async def complete_triangle_sell(row, op: dict) -> dict | None:
    """Карта треугольника закрыта BUY+доливом — SELL в PAID, в кассу только долив."""
    if not is_triangle_row(row):
        return None
    if str(row.get("status") or "") != "CLOSED" and to_kop(row.get("paid_rub")) < to_kop(
        row.get("amount_rub")
    ):
        return None
    sell_id = str(row.get("source_sell_order_id") or "").strip()
    if not sell_id:
        return None
    op_id = int((op or {}).get("id") or row.get("operator_id") or 0)
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        sell = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1",
            sell_id,
        )
        if not sell:
            return None
        status = str(sell["status"] or "").upper()
        if status != "PAID" and status not in TRIANGLE_SELL_STATUSES:
            logger.warning(
                "triangle sell %s status %s — skip PAID",
                sell_id,
                sell["status"],
            )
            return None
        returned = triangle_balance_return(row)
        if returned > 0 and sell.get("user_id") and row.get("id"):
            from user_unified_balance import credit_triangle_shortfall

            await credit_triangle_shortfall(
                user_id=int(sell["user_id"]),
                requisite_id=int(row["id"]),
                amount_rub=float(returned),
            )
        if status == "PAID":
            return {"order_id": sell_id, "already_paid": True, "balance_return_rub": float(returned)}
        doliv_rub = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)
            FROM payout_requisite_allocations
            WHERE requisite_id = $1 AND kind = 'doliv' AND status = 'PAID'
            """,
            int(row["id"]),
        )
        buy_rub = await conn.fetchval(
            """
            SELECT COALESCE(SUM(amount_rub), 0)
            FROM payout_requisite_allocations
            WHERE requisite_id = $1 AND kind = 'payin' AND status = 'PAID'
            """,
            int(row["id"]),
        )

    from bot_status_bridge import update_order_status as bot_set_status

    ok = False
    try:
        ok = bool(await bot_set_status(sell_id, "PAID"))
    except Exception as exc:
        logger.warning("triangle sell_paid bridge %s: %s", sell_id, exc)
    snap = _snapshot_dict(sell.get("payment_snapshot") if hasattr(sell, "get") else None)
    if not snap:
        try:
            snap = _snapshot_dict(sell["payment_snapshot"])
        except Exception:
            snap = {}
    snap["payout_channel"] = "triangle"
    snap["triangle_buy_rub"] = float(buy_rub or 0)
    snap["triangle_doliv_rub"] = float(doliv_rub or 0)
    crypto_received = float(sell["crypto_amount"] or 0)
    fiat_paid = float(doliv_rub or 0)
    async with pool.acquire() as conn:
        async with conn.transaction():
            if not ok:
                updated = await conn.fetchrow(
                    """
                    UPDATE orders
                    SET status = 'PAID',
                        operator_id = COALESCE(operator_id, $2),
                        finance_operator_id = COALESCE(finance_operator_id, $2),
                        operator_crypto_received = $3,
                        operator_fiat_paid_out = $4,
                        payment_snapshot = $5::jsonb,
                        updated_at = now()
                    WHERE order_id = $1
                      AND status = ANY($6::text[])
                    RETURNING *
                    """,
                    sell_id,
                    op_id or None,
                    crypto_received,
                    fiat_paid,
                    json.dumps(snap, ensure_ascii=False),
                    list(TRIANGLE_SELL_STATUSES),
                )
            else:
                updated = await conn.fetchrow(
                    """
                    UPDATE orders
                    SET operator_id = COALESCE(operator_id, $2),
                        finance_operator_id = COALESCE(finance_operator_id, $2),
                        operator_crypto_received = $3,
                        operator_fiat_paid_out = $4,
                        payment_snapshot = $5::jsonb,
                        updated_at = now()
                    WHERE order_id = $1
                    RETURNING *
                    """,
                    sell_id,
                    op_id or None,
                    crypto_received,
                    fiat_paid,
                    json.dumps(snap, ensure_ascii=False),
                )
    if not updated:
        return None
    try:
        from bot_status_bridge import notify_order_completed_for_user

        notice = dict(updated)
        notice["triangle_paid_rub"] = float(_money(_row_field(row, "paid_rub")))
        notice["triangle_return_rub"] = float(triangle_balance_return(row))
        notice["triangle_subsidy_rub"] = float(triangle_subsidy_amount(row))
        await notify_order_completed_for_user(notice)
    except Exception as exc:
        logger.warning("triangle sell notify %s: %s", sell_id, exc)
    return {"order_id": sell_id, "already_paid": False, "doliv_rub": fiat_paid}


async def _finance_operator_id(conn) -> int | None:
    value = await conn.fetchval(
        """
        SELECT id FROM operator_accounts
        WHERE is_active
          AND (
            operator_role = 'finance'
            OR 'finance' = ANY(COALESCE(operator_roles, ARRAY[]::text[]))
          )
        ORDER BY id
        LIMIT 1
        """
    )
    return int(value) if value is not None else None


_TRIANGLE_LIVE = ("QUEUED", "OPEN", "RESERVED", "PARTIAL")


def live_triangle_label(method, status) -> str | None:
    """Подпись живой карты вывода. Пусто, если карты в приёме нет."""
    state = str(status or "")
    if state == "QUEUED":
        return "Ждёт включения"
    if state not in ("OPEN", "RESERVED", "PARTIAL"):
        return None
    if str(method or "").lower() == "sbp":
        return "В приёме, СБП"
    return "В приёме, карта"


def missing_triangle_label(wd: dict) -> str | None:
    """Почему вывод на карту ещё не стоит в приёме. Крипта сюда не входит."""
    if str((wd or {}).get("method") or "").lower() != "card":
        return None
    if (wd or {}).get("triangle_gave_up"):
        return "Ручная выплата: покупатель не нашёлся"
    from runtime_settings import triangle_enabled

    if not triangle_enabled():
        return "Не встал: треугольник выключен"
    try:
        parse_sell_fiat_bill(str((wd or {}).get("requisites") or ""))
    except ValueError:
        return "Не встал: не разобрали номер"
    return "Не встал: приём ещё не открыт"


async def open_withdrawal_triangle(wd: dict) -> dict | None:
    """Карта или телефон вывода сразу в открытый приём. Крипта и мусор — None."""
    from runtime_settings import triangle_enabled

    if not triangle_enabled():
        return None
    if str((wd or {}).get("method") or "").lower() != "card":
        return None
    withdrawal_id = int(wd["id"])
    try:
        bill = parse_sell_fiat_bill(str(wd.get("requisites") or ""))
    except ValueError:
        logger.info("withdrawal %s requisites are not a card or phone", withdrawal_id)
        return None
    if bill.get("method") not in ("card", "sbp"):
        return None
    payout = wd.get("payout_amount_rub")
    raw_amount = payout if payout is not None else wd.get("amount_rub")
    amount = Decimal(str(raw_amount or 0)).quantize(Decimal("0.01"))
    if amount <= 0:
        return None
    max_checks, doliv_limit = payin_stored_limits(amount)
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        operator_id = await _finance_operator_id(conn)
        if operator_id is None:
            logger.warning("withdrawal %s triangle skipped: no finance operator", withdrawal_id)
            return None
        deadline = datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_WINDOW_MINUTES)
        try:
            row = await conn.fetchrow(
                f"""
                INSERT INTO operator_payout_requisites (
                    operator_id, label, direction, method, requisites, bank, holder_name,
                    amount_rub, cost_pct, crypto, max_checks, doliv_limit_rub, status,
                    deadline_at, confirmed_at, confirmed_by, source_withdrawal_id,
                    client_due_rub, subsidy_cap_rub
                )
                VALUES (
                    $1, $2, 'payin', $3, $4, $5, $6,
                    $7, 0, 'usdt', $8, $9, 'OPEN',
                    $10, now(), $1, $11, $12, $13
                )
                RETURNING {REQUISITE_COLUMNS}
                """,
                operator_id,
                f"Вывод #{withdrawal_id}",
                bill["method"],
                bill["requisites"],
                bill["bank"],
                bill["holder_name"],
                amount,
                max_checks,
                doliv_limit,
                deadline,
                withdrawal_id,
                amount,
                frozen_subsidy_cap_rub(amount),
            )
        except Exception as exc:
            err = str(exc).lower()
            if "ux_payout_req_source_withdrawal_live" not in err and "unique" not in err:
                raise
            row = await conn.fetchrow(
                f"""
                SELECT {REQUISITE_COLUMNS} FROM operator_payout_requisites
                WHERE source_withdrawal_id = $1
                  AND status = ANY($2::text[])
                LIMIT 1
                """,
                withdrawal_id,
                ["QUEUED", "OPEN", "RESERVED", "PARTIAL"],
            )
            if row is None:
                raise
    return dict(row) if row else None


async def reopen_pending_withdrawal_triangles(conn) -> int:
    """Pending-выводы на карту без живой карты и без оплаченного чека — снова в приём."""
    rows = await conn.fetch(
        """
        SELECT w.*
        FROM user_referral_withdrawals w
        WHERE w.status = 'pending'
          AND lower(w.method) = 'card'
          AND NOT EXISTS (
              SELECT 1 FROM operator_payout_requisites r
              WHERE r.source_withdrawal_id = w.id
                AND r.status = ANY($1::text[])
          )
          AND NOT EXISTS (
              SELECT 1 FROM operator_payout_requisites r
              WHERE r.source_withdrawal_id = w.id
                AND r.close_note = $2
          )
          AND NOT EXISTS (
              SELECT 1
              FROM payout_requisite_allocations a
              JOIN operator_payout_requisites r ON r.id = a.requisite_id
              WHERE r.source_withdrawal_id = w.id
                AND a.status = 'PAID'
          )
        ORDER BY w.id
        LIMIT 50
        """,
        list(_TRIANGLE_LIVE),
        MANUAL_PAYOUT_NOTE,
    )
    opened = 0
    for row in rows:
        try:
            out = await open_withdrawal_triangle(dict(row))
        except Exception:
            logger.exception("triangle reopen withdrawal %s failed", row.get("id"))
            continue
        if out:
            opened += 1
    return opened


async def give_up_idle_withdrawal_triangles(conn, *, minutes: int = WITHDRAWAL_WAIT_MINUTES) -> list[dict]:
    """Карта вывода без брони и оплаты дольше `minutes` — снять с приёма под ручную выплату.

    Вызывать в транзакции: строки карт блокируются до проверки броней, чтобы не
    снять карту, на которую покупатель только что встал.
    """
    rows = await conn.fetch(
        """
        SELECT r.id, r.operator_id, r.label, r.method, r.amount_rub, r.source_withdrawal_id
        FROM operator_payout_requisites r
        JOIN user_referral_withdrawals w ON w.id = r.source_withdrawal_id
        WHERE r.source_withdrawal_id IS NOT NULL
          AND r.status = ANY($1::text[])
          AND w.status = 'pending'
          AND COALESCE(r.paid_rub, 0) = 0
          AND r.created_at <= now() - make_interval(mins => $2)
        ORDER BY r.id
        FOR UPDATE OF r
        """,
        list(_TRIANGLE_LIVE),
        int(minutes),
    )
    gave_up: list[dict] = []
    for row in rows:
        busy = await conn.fetchval(
            """
            SELECT 1 FROM payout_requisite_allocations
            WHERE requisite_id = $1 AND status IN ('RESERVED', 'PAID')
            LIMIT 1
            """,
            int(row["id"]),
        )
        if busy:
            continue
        await conn.execute(
            """
            UPDATE operator_payout_requisites
            SET status = 'CANCELED', closed_at = now(), close_note = $2, updated_at = now()
            WHERE id = $1
            """,
            int(row["id"]),
            MANUAL_PAYOUT_NOTE,
        )
        gave_up.append(dict(row))
    return gave_up


def manual_payout_message(row: dict, minutes: int = WITHDRAWAL_WAIT_MINUTES) -> str:
    wd_id = int(row["source_withdrawal_id"])
    amount = float(row.get("amount_rub") or 0)
    via = "СБП" if str(row.get("method") or "").lower() == "sbp" else "карту"
    return (
        f"<b>Вывод #{wd_id}: выплатить вручную</b>\n"
        f"За {minutes} мин в приёме ни один покупатель не попал в {amount:.0f} ₽ на {via}.\n"
        "Карта снята с приёма, ручная отметка оплаты открыта.\n"
        "Операторка → Заявки → Выводы."
    )


async def complete_triangle_withdrawal(row, op: dict | None = None) -> dict | None:
    """Карта треугольника закрыта — вывод на карту становится оплаченным."""
    if not is_triangle_row(row):
        return None
    raw_id = row.get("source_withdrawal_id") if hasattr(row, "get") else None
    if raw_id in (None, ""):
        return None
    paid_kop = to_kop(row.get("paid_rub"))
    amount_kop = to_kop(row.get("amount_rub"))
    closed = str(row.get("status") or "") == "CLOSED"
    if paid_kop <= 0 or (not closed and paid_kop < amount_kop):
        return None
    withdrawal_id = int(raw_id)
    from user_referral_withdraw import (
        get_withdrawal,
        notify_withdrawal_completed,
        process_withdrawal_paid,
    )

    existing = await get_withdrawal(withdrawal_id)
    if not existing:
        return None
    already = str(existing["status"] or "") == "paid"
    if not already:
        if str(existing["status"] or "") != "pending":
            logger.warning(
                "triangle withdrawal %s status %s — skip paid",
                withdrawal_id,
                existing["status"],
            )
            return None
        paid, err = await process_withdrawal_paid(withdrawal_id)
        if not paid:
            logger.warning("triangle withdrawal %s not paid: %s", withdrawal_id, err)
            return None
        existing = paid
    balance_return = triangle_balance_return(row)
    if balance_return > 0 and row.get("id"):
        from user_unified_balance import credit_triangle_shortfall

        await credit_triangle_shortfall(
            user_id=int(existing["referrer_user_id"]),
            requisite_id=int(row["id"]),
            amount_rub=float(balance_return),
            withdrawal_id=withdrawal_id,
        )
    if already:
        return {
            "withdrawal_id": withdrawal_id,
            "already_paid": True,
            "balance_return_rub": float(balance_return),
        }
    try:
        await notify_withdrawal_completed(
            existing,
            card_paid_rub=float(_money(row.get("paid_rub"))),
            balance_return_rub=float(balance_return),
            subsidy_rub=float(triangle_subsidy_amount(row)),
        )
    except Exception as exc:
        logger.warning("triangle withdrawal notify %s: %s", withdrawal_id, exc)
    del op
    return {
        "withdrawal_id": withdrawal_id,
        "already_paid": False,
        "balance_return_rub": float(balance_return),
    }

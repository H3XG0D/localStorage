"""Тестовая оценка: прошла бы заявка через автопилот (реквизиты без смены + автовыплата).

Считается так, будто тумблеры включены: цель — увидеть на живых заявках, что
сделал бы автопилот, до того как его включать. Список заявок оценивается пачкой
без сетевых вызовов (signer, Payfast); живые проверки — только в карточке.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from auto_settings import (
    auto_mode_enabled,
    auto_no_shift_enabled,
    auto_no_shift_max_rub,
    auto_no_shift_min_buy_paid,
    auto_payout_enabled,
    auto_payout_max_rub,
    auto_whitelist_user_ids,
)

AUTO_COINS = ("btc", "ltc")


@dataclass
class PreviewContext:
    """Данные по клиентам страницы, собранные одним проходом."""

    paid_buys: dict[int, list[datetime]] = field(default_factory=dict)
    overrides: dict[int, bool | None] = field(default_factory=dict)
    banned: set[int] = field(default_factory=set)


def _coin(crypto: Any) -> str:
    return str(crypto or "").split("_")[0].strip().lower()


def _paid_before(ctx: PreviewContext, user_id: int, created_at: Any) -> int:
    times = ctx.paid_buys.get(user_id) or []
    if not isinstance(created_at, datetime):
        return len(times)
    return sum(1 for t in times if t < created_at)


_PF_CONFIRMED = frozenset({"COMPLETED", "PAID"})
_PF_WAITING = frozenset({"CREATED", "PENDING", "AWAITING_CHECK", "OPERATOR_PENDING"})
_PF_DETAIL = {
    "confirmed": "оплата подтверждена",
    "waiting": "ждём подтверждения",
    "not_paid": "не оплачена",
}


def payfast_state(status: Any) -> str:
    """Оценка по статусу заявки: COMPLETED ставится только после апрува Payfast."""
    st = str(status or "").strip().upper()
    if st in _PF_CONFIRMED:
        return "confirmed"
    if st in _PF_WAITING:
        return "waiting"
    return "not_paid"


_BLOCKER_TEXT = {
    "no_address": "нет адреса кошелька",
    "no_crypto_amount": "нет суммы монет",
    "signer": "кошелёк недоступен",
    "hot_balance": "мало на горячем кошельке",
    "daily_cap": "дневной лимит исчерпан",
    "payfast_live": "Payfast сейчас не подтверждает оплату",
}

_MOMENT_RANK = {
    "would_send_now": 0,
    "would_send": 1,
    "blocked_now": 2,
    "waiting_payfast": 3,
    "manual": 4,
    "already_sent": 5,
    "n/a": 6,
}


def _blocker_phrase(key: str) -> str:
    return _BLOCKER_TEXT.get(key, key)


def payout_moment(order: dict, preview: dict, live_checks: list[dict] | None = None) -> dict:
    """В какой момент по этой заявке ушли бы монеты.

    live_checks is None — кошелёк ещё не смотрели, фразу «сейчас» не ставим.
    Пустой список значит «смотрели, препятствий нет».
    """
    if preview.get("verdict") == "n/a":
        return {
            "key": "n/a",
            "headline": "Продажа — автовывод не применяется",
            "send_text": "Автовывод не применяется",
            "blockers": [],
            "steps": [],
        }

    reasons = list(preview.get("reasons") or [])
    client_reasons = [r for r in reasons if r not in ("payfast_waiting", "payfast_not_paid_order")]
    pf = payfast_state(order.get("status"))
    status = str(order.get("status") or "").strip().upper()
    already = bool(str(order.get("payout_tx_hash") or "").strip()) or status == "PAID"
    address = str(order.get("requisites") or "").strip()
    try:
        amount = float(order.get("crypto_amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0

    blockers: list[str] = []
    if not already and not client_reasons and pf == "confirmed":
        if not address:
            blockers.append("no_address")
        if amount <= 0:
            blockers.append("no_crypto_amount")
        if live_checks is not None:
            blockers.extend(str(c.get("key") or "") for c in live_checks if not c.get("ok") and c.get("key"))

    if already:
        key = "already_sent"
        send_text = "Монеты уже отправлены клиенту"
        headline = "По этой заявке монеты уже отправлены"
    elif client_reasons or pf == "not_paid":
        key = "manual"
        send_text = "Автовывод не случился бы"
        headline = "По этой заявке автовывод не случился бы — ушло бы оператору"
    elif pf == "waiting":
        key = "waiting_payfast"
        send_text = "После подтверждения Payfast случился бы автовывод"
        headline = "По этой заявке автовывод случился бы после подтверждения Payfast"
    elif blockers:
        key = "blocked_now"
        send_text = "Сейчас монеты бы не ушли: " + ", ".join(_blocker_phrase(b) for b in blockers)
        headline = "По этой заявке клиент подходит, но сейчас монеты бы не ушли"
    elif live_checks is not None:
        key = "would_send_now"
        send_text = "Сейчас случился бы автовывод — монеты ушли бы клиенту"
        headline = "По этой заявке сейчас случился бы автовывод"
    else:
        key = "would_send"
        send_text = "Случился бы автовывод — монеты ушли бы клиенту"
        headline = "По этой заявке случился бы автовывод"

    req_ok = not client_reasons
    steps = [
        {
            "key": "requisites",
            "state": "done" if req_ok else "block",
            "text": "Реквизиты выдали бы автоматически" if req_ok else "Реквизиты выдал бы оператор",
        },
        {
            "key": "payfast",
            "state": {"confirmed": "done", "waiting": "wait", "not_paid": "block"}[pf],
            "text": {
                "confirmed": "Payfast подтвердил оплату",
                "waiting": "Ждём подтверждения Payfast",
                "not_paid": "Оплата не подтверждена",
            }[pf],
        },
        {
            "key": "send",
            "state": {
                "would_send_now": "now",
                "would_send": "now",
                "waiting_payfast": "wait",
                "manual": "block",
                "already_sent": "done",
                "blocked_now": "block",
            }[key],
            "text": send_text,
        },
    ]
    return {
        "key": key,
        "headline": headline,
        "send_text": send_text,
        "blockers": blockers,
        "steps": steps,
    }


def with_live_checks(preview: dict, live_checks: list[dict], order: dict) -> dict:
    """Дописать живые проверки кошелька и пересчитать момент отправки."""
    preview["live_checks"] = live_checks
    blocked = [c["key"] for c in live_checks if not c.get("ok")]
    if preview.get("verdict") == "auto" and blocked:
        preview["live_blocked"] = blocked
    else:
        preview.pop("live_blocked", None)
    preview["moment"] = payout_moment(order, preview, live_checks)
    return preview


def preview_order_autopay(order: dict, ctx: PreviewContext) -> dict:
    direction = str(order.get("direction") or "").strip().lower()
    toggles = {
        "mode": auto_mode_enabled(),
        "no_shift": auto_no_shift_enabled(),
        "payout": auto_payout_enabled(),
    }
    if direction != "buy":
        out = {
            "verdict": "n/a",
            "reasons": ["sell_requires_shift"],
            "checks": [],
            "toggles": toggles,
        }
        out["moment"] = payout_moment(order, out)
        return out

    user_id = int(order.get("user_id") or 0)
    coin = _coin(order.get("crypto"))
    fiat = float(order.get("fiat_amount") or 0)
    min_paid = auto_no_shift_min_buy_paid()
    paid = _paid_before(ctx, user_id, order.get("created_at"))
    override = ctx.overrides.get(user_id)
    whitelist = auto_whitelist_user_ids()
    cap = min(auto_no_shift_max_rub() or 0, auto_payout_max_rub() or 0)

    pf_state = payfast_state(order.get("status"))
    checks: list[dict] = [
        {
            "key": "payfast",
            "ok": pf_state == "confirmed",
            "pending": pf_state == "waiting",
            "detail": _PF_DETAIL[pf_state],
        },
        {
            "key": "coin",
            "ok": coin in AUTO_COINS,
            "detail": coin.upper() or "—",
        },
        {
            "key": "amount_cap",
            "ok": cap <= 0 or fiat <= cap + 0.01,
            "detail": f"{fiat:,.0f} / {cap:,.0f} ₽".replace(",", " "),
        },
        {
            "key": "not_banned",
            "ok": user_id not in ctx.banned,
            "detail": "",
        },
        {
            "key": "override",
            "ok": override is not False,
            "detail": {True: "всегда авто", False: "никогда авто", None: "по правилам"}[override],
        },
    ]
    if override is not True:
        checks.append(
            {
                "key": "paid_buys",
                "ok": paid >= min_paid,
                "detail": f"{paid} из {min_paid}",
            }
        )
        if whitelist:
            checks.append(
                {
                    "key": "whitelist",
                    "ok": user_id in whitelist,
                    "detail": "",
                }
            )
    client_reasons = [c["key"] for c in checks if not c["ok"] and c["key"] != "payfast"]
    if client_reasons:
        verdict, reasons = "manual", client_reasons
    elif pf_state == "waiting":
        verdict, reasons = "waiting", ["payfast_waiting"]
    elif pf_state == "not_paid":
        verdict, reasons = "manual", ["payfast_not_paid_order"]
    else:
        verdict, reasons = "auto", []
    out = {
        "verdict": verdict,
        "reasons": reasons,
        "checks": checks,
        "toggles": toggles,
    }
    out["moment"] = payout_moment(order, out)
    return out


async def build_preview_context(conn, user_ids: Iterable[Any]) -> PreviewContext:
    ids = sorted({int(u) for u in user_ids if u})
    ctx = PreviewContext()
    if not ids:
        return ctx
    rows = await conn.fetch(
        """
        SELECT user_id, created_at
        FROM orders
        WHERE user_id = ANY($1::bigint[])
          AND lower(direction) = 'buy'
          AND status IN ('PAID', 'COMPLETED')
        """,
        ids,
    )
    for r in rows:
        ctx.paid_buys.setdefault(int(r["user_id"]), []).append(r["created_at"])
    users = await conn.fetch(
        """
        SELECT user_id, auto_service_override, is_banned
        FROM bot_users
        WHERE user_id = ANY($1::bigint[])
        """,
        ids,
    )
    for u in users:
        uid = int(u["user_id"])
        ctx.overrides[uid] = u["auto_service_override"]
        if u["is_banned"]:
            ctx.banned.add(uid)
    return ctx


async def live_payfast_check(order: dict) -> dict | None:
    """Живой запрос в Payfast (только чтение) — то же, что воркер спросит перед отправкой."""
    if str(order.get("status") or "").upper() != "COMPLETED":
        return None
    from payfast_payin_guard import payfast_status_from_payload, verify_payfast_ready_for_payout

    ok, err, resp = await verify_payfast_ready_for_payout(order, require_uuid=True)
    status = payfast_status_from_payload(resp or {}) if resp else ""
    return {
        "key": "payfast_live",
        "ok": bool(ok),
        "detail": status or (err or ""),
        "reason": err,
    }


async def live_payout_checks(conn) -> list[dict]:
    """Проверки, зависящие от текущего состояния кошелька и лимитов (только карточка)."""
    from auto_payout_guard import hot_spendable_rub, signer_circuit_closed
    from auto_payout_worker import daily_cap_room
    from auto_settings import auto_min_hot_balance_rub

    circuit = await signer_circuit_closed(conn)
    hot_rub = await hot_spendable_rub(conn)
    floor = auto_min_hot_balance_rub()
    room = await daily_cap_room(conn)
    return [
        {"key": "signer", "ok": bool(circuit), "detail": ""},
        {
            "key": "hot_balance",
            "ok": floor <= 0 or hot_rub >= floor,
            "detail": f"{hot_rub:,.0f} / мин. {floor:,.0f} ₽".replace(",", " "),
        },
        {
            "key": "daily_cap",
            "ok": room > 0,
            "detail": f"осталось {room:,.0f} ₽".replace(",", " "),
        },
    ]


async def payout_shadow_report(conn, *, limit: int = 30) -> list[dict]:
    """Свежие покупки: по каждой — случился бы автовывод сейчас или на каком шаге нет.

    Ничего не отправляет. Живые проверки кошелька одни на весь список.
    """
    rows = await conn.fetch(
        """
        SELECT o.order_id, o.user_id, o.direction, o.crypto, o.fiat_amount, o.status,
               o.created_at, o.requisites, o.crypto_amount, o.payout_tx_hash,
               bu.username, bu.first_name
        FROM orders o
        LEFT JOIN bot_users bu ON bu.user_id = o.user_id
        WHERE lower(o.direction) = 'buy'
          AND o.created_at > now() - interval '7 days'
          AND upper(o.status) NOT IN ('CANCELED', 'EXPIRED', 'FAILED')
        ORDER BY o.created_at DESC
        LIMIT 60
        """
    )
    ctx = await build_preview_context(conn, (r["user_id"] for r in rows))
    try:
        live = await live_payout_checks(conn)
    except Exception:
        live = None
    out: list[dict] = []
    for r in rows:
        order = dict(r)
        preview = preview_order_autopay(order, ctx)
        if live is not None:
            with_live_checks(preview, live, order)
        moment = preview.get("moment") or {}
        name = r["username"]
        created = r["created_at"]
        out.append(
            {
                "order_id": str(r["order_id"]),
                "user_id": int(r["user_id"]) if r["user_id"] is not None else None,
                "username": f"@{name}" if name and not str(name).startswith("@") else name,
                "first_name": r["first_name"],
                "fiat_amount": float(r["fiat_amount"] or 0),
                "crypto": str(r["crypto"] or ""),
                "status": str(r["status"] or ""),
                "created_at": created.isoformat() if created else None,
                "moment_key": moment.get("key"),
                "headline": moment.get("headline") or "",
                "send_text": moment.get("send_text") or "",
                "reasons": list(preview.get("reasons") or []),
                "blockers": list(moment.get("blockers") or []),
            }
        )
    grouped: dict[str, list[dict]] = {}
    for row in out:
        grouped.setdefault(str(row["moment_key"]), []).append(row)
    ordered: list[dict] = []
    for key in sorted(grouped, key=lambda k: _MOMENT_RANK.get(k, 9)):
        ordered.extend(sorted(grouped[key], key=lambda row: row["created_at"] or "", reverse=True))
    return ordered[:limit]

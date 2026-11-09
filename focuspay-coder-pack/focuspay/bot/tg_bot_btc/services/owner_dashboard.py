"""Форматирование /pulse, /dash, /users, /help для владельца."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from services import config_rates
from services.order_ops_notify import format_ops_crypto_amount, operator_url
from services.owner_analytics import (
    AudiencePeriod,
    MoneyPeriod,
    OwnerSnapshot,
    fetch_autopilot_savings,
    fetch_hot_wallet_runway,
    fetch_owner_snapshot,
    fetch_missed_requisites,
    fetch_users_detail,
)

from zoneinfo import ZoneInfo

_MSK = ZoneInfo("Europe/Moscow")


def _fmt_rub(amount: float) -> str:
    return f"<code>{amount:,.0f}</code> ₽".replace(",", " ")


def format_hot_wallet_block(data: dict[str, Any] | None) -> list[str]:
    """Короткий блок /dash. Пустой ответ API — одна строка, без падения сводки."""
    if not data or data.get("available") is not True:
        return ["🔥 Горячий кошелёк: нет данных"]
    lines = ["<b>[🔥] Горячий кошелёк</b>"]
    coins = data.get("coins") or []
    if not coins:
        lines.append("нет данных")
    for coin in coins:
        line = str(coin.get("line") or "").strip()
        if line:
            lines.append(html.escape(line))
    floor = str(data.get("floor_phrase") or "").strip()
    if floor:
        lines.append(html.escape(floor))
    return lines


def format_autopilot_savings_block(data: dict[str, Any] | None) -> list[str]:
    """Короткий блок /dash. Пустой ответ — одна строка."""
    if not data or data.get("net_rub") is None:
        return ["Плюс автопилота: нет данных"]
    lines = ["<b>[+] Автопилот · 7 дней</b>"]
    headline = str(data.get("line") or "").strip()
    if headline:
        lines.append(html.escape(headline))
    lines.append("Кешбэк не поднимаем")
    return lines


def _format_shifts(shifts: list[Any]) -> str:
    if not shifts:
        return "никого"
    parts = []
    for s in shifts:
        name = html.escape(str(s.get("operator_name") or "—"))
        started = s.get("started_at")
        if started and hasattr(started, "strftime"):
            if hasattr(started, "astimezone"):
                started = started.astimezone()
            t = started.strftime("%H:%M")
        else:
            t = "—"
        parts.append(f"{name} (с {t})")
    return ", ".join(parts)


def _format_open_map(open_by_status: dict[str, int]) -> str:
    if not open_by_status:
        return "нет открытых"
    order = ["CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED", "OPERATOR_PENDING"]
    parts = []
    for st in order:
        cnt = open_by_status.get(st, 0)
        if cnt:
            if st == "COMPLETED":
                parts.append(f"COMPLETED {cnt} (крипта)")
            else:
                parts.append(f"{st} {cnt}")
    return " · ".join(parts) if parts else "нет открытых"


def _payin_limits_line() -> str:
    lim = config_rates.MERCHANT_PAYIN_LIMITS
    sbp = lim.get("SBPRUB", {}).get("max_single", 0)
    card = lim.get("CARDRUB", {}).get("max_single", 0)
    return f"СБП {sbp:,} ₽ · карта {card:,} ₽".replace(",", " ")


def _minutes_ago(dt) -> str:
    if dt is None:
        return "—"
    now = datetime.now(timezone.utc)
    if hasattr(dt, "tzinfo") and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif hasattr(dt, "astimezone"):
        dt = dt.astimezone(timezone.utc)
    delta = now - dt
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "только что"
    if mins < 60:
        return f"{mins} мин назад"
    return f"{mins // 60} ч назад"


def _money_line(label: str, m: MoneyPeriod) -> str:
    residual_label = "финальный остаток" if m.from_pnl else "ваша прибыль"
    profit_part = f"{residual_label} {_fmt_rub(m.net_profit_rub)}"
    extras: list[str] = []
    if m.from_pnl:
        extras.append(f"до начисл. {_fmt_rub(m.profit_rub)}")
        if abs(m.external_profit_rub) > 0.009:
            extras.append(f"внештат {_fmt_rub(m.external_profit_rub)}")
        extras.append(f"казино {_fmt_rub(m.casino_profit_rub)}")
        extras.append(f"впн {_fmt_rub(m.vpn_profit_rub)}")
    if m.review_bonus_rub > 0.009:
        extras.append(f"отзывы −{_fmt_rub(m.review_bonus_rub)}")
    if m.wallet_payout_rub > 0.009:
        extras.append(f"кошельки −{_fmt_rub(m.wallet_payout_rub)}")
    if m.focus_lucky_rub > 0.009:
        extras.append(f"FocusLucky −{_fmt_rub(m.focus_lucky_rub)}")
    if m.buy_network_fee_rub > 0.009:
        extras.append(f"сеть −{_fmt_rub(m.buy_network_fee_rub)}")
    if m.cashback_accrual_rub > 0.009:
        extras.append(f"кешбэк −{_fmt_rub(m.cashback_accrual_rub)}")
    if m.referral_accrual_rub > 0.009:
        extras.append(f"рефералка −{_fmt_rub(m.referral_accrual_rub)}")
    if m.partner_accrual_rub > 0.009:
        extras.append(f"партнёрка −{_fmt_rub(m.partner_accrual_rub)}")
    if m.swap_commission_rub > 0.009:
        extras.append(f"swap −{_fmt_rub(m.swap_commission_rub)}")
    if m.operators_payroll_rub > 0.009:
        extras.append(f"ЗП оп. −{_fmt_rub(m.operators_payroll_rub)}")
    if m.admin_salary_rub > 0.009:
        extras.append(f"ЗП адм. −{_fmt_rub(m.admin_salary_rub)}")
    if m.usdt_issued_rub > 0.009:
        extras.append(f"USDT −{_fmt_rub(m.usdt_issued_rub)}")
    if m.manual_expenses_rub > 0.009:
        extras.append(f"расходы −{_fmt_rub(m.manual_expenses_rub)}")
    if extras:
        profit_part += f" ({', '.join(extras)})"
    deals_label = "сделок" if m.from_pnl else "PAID"
    return (
        f"{label}: оборот {_fmt_rub(m.turnover_rub)} · "
        f"{profit_part} · {deals_label} <code>{m.deals}</code>"
    )


def _audience_line(a: AudiencePeriod) -> str:
    return (
        f"Новых /start: <code>{a.bot_new}</code> · "
        f"заходили в бота: <code>{a.bot_active}</code>\n"
        f"Сайт: <code>{a.web_unique_ips}</code> уник. IP · "
        f"<code>{a.web_guest_sessions}</code> гостевых сессий"
    )


def _format_problems_block(snap: OwnerSnapshot, *, detailed: bool = False) -> list[str]:
    lines: list[str] = []
    stale_n = len(snap.stale_completed)
    pending_n = snap.old_pending_count
    if stale_n == 0 and pending_n == 0:
        lines.append("<b>[!] Проблемы:</b> OK")
        return lines

    lines.append("<b>[!] Проблемы</b>")
    if stale_n:
        from services.merchant_order_id import resolve_merchant_display_id

        if detailed:
            for o in snap.stale_completed[:5]:
                oid = html.escape(resolve_merchant_display_id(dict(o)))
                age = int(float(o.get("age_minutes") or 0))
                fiat = float(o.get("fiat_amount") or 0)
                lines.append(
                    f"• крипта не ушла &gt;{config_rates.OWNER_STALE_PAYOUT_MINUTES}м: "
                    f"<code>{oid}</code> · {_fmt_rub(fiat)} · <code>{age}</code> мин"
                )
        else:
            worst = snap.stale_completed[0]
            oid = html.escape(resolve_merchant_display_id(dict(worst)))
            age = int(float(worst.get("age_minutes") or 0))
            extra = f" (+{stale_n - 1})" if stale_n > 1 else ""
            lines.append(
                f"• <code>{stale_n}</code> ждут крипту &gt;{config_rates.OWNER_STALE_PAYOUT_MINUTES}м "
                f"(<code>{oid}</code>, {age}м{extra})"
            )
    if pending_n:
        lines.append(f"• <code>{pending_n}</code> чеков PENDING &gt;15 мин")
    if snap.stale_sell_pending:
        lines.append(
            f"• <code>{snap.stale_sell_pending}</code> SELL ждут оператора &gt;30 мин"
        )
    term = snap.terminal_today
    if detailed and term:
        parts = [f"{k} {v}" for k, v in sorted(term.items()) if v]
        if parts:
            lines.append(f"• сегодня закрыто: {', '.join(parts)}")
    return lines


def _fmt_sum_short(amount: int) -> str:
    """30000 → 30к, 1500000 → 1.5М."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}М".replace(".0М", "М")
    if amount >= 1_000:
        return f"{amount // 1_000}к"
    return str(amount)


def _format_missed_requisites_block(
    count: int,
    rows: list[dict[str, Any]],
) -> list[str]:
    """Блок пропусков для /dash: уникальные пользователи + сумма первой попытки."""
    if not count:
        return ["<b>[🚫] Пропуски (нет реквизитов):</b> нет"]
    seen: set[Any] = set()
    unique_count = 0
    total_fiat = 0
    for row in rows:
        uid = row.get("user_id")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        unique_count += 1
        fiat = row.get("fiat_amount")
        if fiat:
            total_fiat += int(fiat)
    header = f"<b>[🚫] Пропуски:</b> <code>{unique_count}</code> клиентов"
    if total_fiat:
        header += f" · <code>{total_fiat:,}</code> ₽".replace(",", " ")
    return [header]


async def build_pulse_text() -> str:
    from services.owner_promo import best_promo_roi_line

    snap = await fetch_owner_snapshot(period_arg=None, include_week=True)
    ts = snap.fetched_at.strftime("%d.%m.%Y %H:%M")
    lines = [f"<b>PULSE</b> · {html.escape(ts)}", ""] + _format_problems_block(snap, detailed=False)
    promo_line = await best_promo_roi_line(1)
    if promo_line:
        lines.append(promo_line)
    lines.extend(
        [
            "",
            "<b>[$] Сегодня</b>",
            _money_line("Сегодня", snap.money),
            "",
            "<b>[$] За 7 дней</b>",
            _money_line("Неделя", snap.money_week),
            "",
            "<b>[👥] Пользователи (сегодня)</b>",
            _audience_line(snap.audience),
            "",
            f"<b>[⏳] Очередь:</b> {_format_open_map(snap.open_by_status)}",
            f"👷 {_format_shifts(snap.shifts)}",
        ]
    )
    lines.extend(["", *_format_missed_requisites_block(
        snap.missed_requisites_count,
        snap.missed_requisites,
    )])
    if snap.last_paid:
        lines.append(
            f"🕐 Последняя PAID <code>{html.escape(str(snap.last_paid['order_id']))}</code> · "
            f"{_minutes_ago(snap.last_paid.get('closed_at'))}"
        )
    lines.append("")
    lines.append("<i>/dash · /users · /help</i>")
    return "\n".join(lines)


async def build_dash_text(arg: str | None = None) -> str:
    today_str = datetime.now().strftime("%d.%m.%Y")
    include_week = arg is None or (arg or "").strip() == today_str
    snap = await fetch_owner_snapshot(period_arg=arg, include_week=include_week)
    period = html.escape(snap.period_label)
    lines = [
        f"<b>📊 Сводка</b> · {period}",
        "",
        *_format_problems_block(snap, detailed=True),
        "",
        f"<b>[$] Деньги · {period}</b>",
        _money_line("Период", snap.money),
    ]
    if snap.period_days <= 1 and snap.money_week.deals:
        lines.extend(["", "<b>[$] За 7 дней</b>", _money_line("Неделя", snap.money_week)])
    hot = await fetch_hot_wallet_runway()
    lines.extend(["", *format_hot_wallet_block(hot)])
    savings = await fetch_autopilot_savings()
    lines.extend(["", *format_autopilot_savings_block(savings)])
    lines.extend(
        [
            "",
            f"<b>[👥] Пользователи · {period}</b>",
            _audience_line(snap.audience),
        ]
    )
    if snap.period_days <= 1 and (
        snap.audience_week.bot_new or snap.audience_week.bot_active
    ):
        lines.extend(["", "<b>[👥] За 7 дней</b>", _audience_line(snap.audience_week)])
    f = snap.funnel
    if f.starts or f.created_order or f.paid_users:
        conv = (
            f"{100.0 * f.paid_users / f.starts:.0f}%"
            if f.starts
            else "—"
        )
        lines.extend(
            [
                "",
                f"<b>[📈] Воронка новых · {period}</b>",
                f"новый /start <code>{f.starts}</code> → заявка <code>{f.created_order}</code> "
                f"→ PAID <code>{f.paid_users}</code> (конв. {conv})",
            ]
        )

    lines.extend(
        [
            "",
            *_format_missed_requisites_block(
                snap.missed_requisites_count,
                snap.missed_requisites,
            ),
        ]
    )

    def _pf_line(label: str, pf) -> str:
        denom = int(pf.paid) + int(pf.failed)
        if denom <= 0 or pf.conversion_pct is None:
            return f"{label}: нет данных · взято <code>{pf.taken}</code>"
        return (
            f"{label}: <b>{pf.conversion_pct:g}%</b> "
            f"(<code>{pf.paid}</code>/<code>{denom}</code>) · взято <code>{pf.taken}</code>"
        )

    lines.extend(
        [
            "",
            "<b>[BUY] Конверсия taken→paid</b>",
            _pf_line("сегодня", snap.payfast_today),
            _pf_line("30 дней", snap.payfast_30d),
        ]
    )

    lines.extend(
        [
            "",
            f"<b>[⚙️] Операции</b>",
            f"👷 На смене: {_format_shifts(snap.shifts)}",
        ]
    )
    if snap.last_paid:
        lines.append(
            f"🕐 Последняя PAID: <code>{html.escape(str(snap.last_paid['order_id']))}</code> · "
            f"{_fmt_rub(float(snap.last_paid.get('fiat_amount') or 0))} · "
            f"{_minutes_ago(snap.last_paid.get('closed_at'))}"
        )
    lines.extend(
        [
            f"⏳ В работе: {_format_open_map(snap.open_by_status)}",
            f"💳 Лимит payin: {_payin_limits_line()}",
        ]
    )
    if snap.max_open_fiat and snap.max_open_fiat > 0:
        lines.append(f"📈 Макс. открытая заявка: {_fmt_rub(snap.max_open_fiat)}")
    lines.append("")
    lines.append("<i>Пропуски за часы: /misses 24 · Подробнее: /users · Команды: /help</i>")
    return "\n".join(lines)


def _build_misses_by_date_hour(rows: list[dict[str, Any]]) -> list[str]:
    """📅 10.08.2026 / 02:00  10 пропусков · 30к ₽"""
    if not rows:
        return []

    by_date: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        created_at = row.get("created_at")
        if not created_at or not hasattr(created_at, "astimezone"):
            continue
        msk_dt = created_at.astimezone(_MSK)
        date_key = msk_dt.strftime("%d.%m.%Y")
        hour_key = msk_dt.strftime("%H:00")
        if date_key not in by_date:
            by_date[date_key] = {}
        if hour_key not in by_date[date_key]:
            by_date[date_key][hour_key] = {"count": 0, "fiat_sum": 0}
        by_date[date_key][hour_key]["count"] += 1
        fiat = row.get("fiat_amount")
        if fiat:
            by_date[date_key][hour_key]["fiat_sum"] += int(fiat)

    if not by_date:
        return []

    lines: list[str] = []
    for date_key in sorted(by_date.keys()):
        lines.append(f"📅 <b>{date_key}</b>")
        hours_data = by_date[date_key]
        for hour_key in sorted(hours_data.keys()):
            h = hours_data[hour_key]
            count_word = "пропуск" if h["count"] == 1 else (
                "пропуска" if 2 <= h["count"] <= 4 else "пропусков"
            )
            sum_str = f" · {_fmt_sum_short(h['fiat_sum'])} ₽" if h["fiat_sum"] else ""
            lines.append(f"<code>{hour_key}</code>  {h['count']} {count_word}{sum_str}")
        lines.append("")
    return lines


async def _reki_summary_line() -> str | None:
    """Свободные суммы по /reki: расхождение с «реки заняты» видно сразу."""
    try:
        from services.reki_poll import load_snapshot, snapshot_ttl_seconds
        from services.reki_snapshot import ops_summary_line

        return ops_summary_line(await load_snapshot(), ttl_seconds=snapshot_ttl_seconds())
    except Exception:
        return None


async def build_misses_text(hours: int = 24) -> str:
    """Полный список попыток, когда реквизиты не выданы."""
    hours = max(1, min(int(hours), 24 * 365))
    count, rows = await fetch_missed_requisites(hours)
    period = f"за последний {hours} ч." if hours == 1 else f"за последние {hours} ч."
    lines = [f"<b>🚫 Пропуски: нет реквизитов · {period}</b>", ""]
    if not count:
        lines.append("Пропусков нет.")
    else:
        total_fiat = sum(int(r.get("fiat_amount") or 0) for r in rows)
        no_shift_n = sum(1 for r in rows if r.get("reason", "no_shift") == "no_shift")
        all_busy_n = sum(1 for r in rows if r.get("reason") == "all_busy")
        summary = f"Всего: <code>{count}</code>"
        if total_fiat:
            summary += f" · <code>{total_fiat:,}</code> ₽".replace(",", " ")
        breakdown = []
        if no_shift_n:
            breakdown.append(f"🔴 нет смены: {no_shift_n}")
        if all_busy_n:
            breakdown.append(f"🟡 реки заняты: {all_busy_n}")
        if breakdown:
            summary += f" ({', '.join(breakdown)})"
        lines.append(summary)
        if all_busy_n:
            reki_line = await _reki_summary_line()
            if reki_line:
                lines.append(reki_line)
        lines.append("")
        date_hour_lines = _build_misses_by_date_hour(rows)
        if date_hour_lines:
            lines.extend(date_hour_lines)
        if count > len(rows):
            lines.append(f"<i>Показаны первые {len(rows)} из {count}.</i>")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


def build_help_text() -> str:
    return (
        "<b>📖 Команды · группа отчётов</b>\n\n"
        "<b>Владелец финансов</b>\n"
        "/pulse — статус и проблемы за минуту\n"
        "/dash — полная сводка (сегодня)\n"
        "/dash 7 — за 7 дней\n"
        "/dash 15.03.2026 — за дату\n"
        "в /dash всегда: Payfast конверсия сегодня и за 30 дней\n"
        "/users — аудитория и IP (сайт)\n"
        "/users 7 — за неделю\n"
        "/misses [часы] — пропуски без реквизитов, например /misses 24\n"
        "/checks втб 10 — последние апрувнутые чеки отправок из банка (файлами)\n"
        "/help — эта справка\n\n"
        "<b>Админы</b>\n"
        "/stats — PAID по монетам\n"
        "/search — активные заявки\n"
        "/list — последние 30\n"
        "/promo · /post [all|inactive7|paid|referrers] — рассылка\n"
        "/chatid — ID этой группы для .env\n\n"
        "Карточки заявок: кнопки «Выплачено» / «Отменить».\n"
        "<i>IP в /users — только веб-заявки (Telegram IP бот не видит).</i>"
    )


async def build_users_text(days: int = 1) -> str:
    if days < 1:
        days = 1
    if days > 365:
        days = 365
    period = "сегодня" if days == 1 else f"последние {days} дн."
    aud, new_users, top_ips, web_regs = await fetch_users_detail(days)

    lines = [
        f"<b>👥 Пользователи · {html.escape(period)}</b>",
        "",
        f"<b>Каналы:</b> бот /start <code>{aud.bot_new}</code> · "
        f"сайт регистрации <code>{web_regs}</code>",
        "",
        _audience_line(aud),
        "",
        "<i>IP — только события с сайта (web_order_ip_log)</i>",
        "",
    ]
    if new_users:
        lines.append("<b>Новые в боте (/start):</b>")
        for u in new_users[:15]:
            uid = u.get("user_id")
            un = u.get("username")
            name = html.escape(str(u.get("first_name") or "—"))
            handle = f"@{html.escape(un)}" if un else "без @"
            lines.append(f"• {handle} · {name} · <code>{uid}</code>")
    else:
        lines.append("Новых /start за период нет.")

    lines.append("")
    if top_ips:
        lines.append("<b>Топ IP (сайт):</b>")
        for row in top_ips:
            ip = html.escape(str(row.get("ip") or "—"))
            cnt = int(row.get("cnt") or 0)
            lines.append(f"• <code>{ip}</code> — <code>{cnt}</code> событий")
    else:
        lines.append("IP с сайта за период нет.")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


def format_stale_payout_alert(order: dict[str, Any]) -> tuple[str, dict]:
    from services.merchant_order_id import format_ops_order_id_html

    fiat = float(order.get("fiat_amount") or 0)
    crypto = str(order.get("crypto") or "")
    crypto_amt = order.get("crypto_amount")
    age = float(order.get("age_minutes") or 0)
    updated = order.get("updated_at")
    time_str = updated.strftime("%H:%M") if hasattr(updated, "strftime") else "—"

    amount_bit = _fmt_rub(fiat)
    if crypto_amt is not None:
        amount_bit += f" · {format_ops_crypto_amount(crypto_amt, crypto)} {html.escape(crypto)}"

    text = (
        f"⚠️ <b>Крипта не отправлена &gt; {config_rates.OWNER_STALE_PAYOUT_MINUTES} мин</b>\n\n"
        f"{format_ops_order_id_html(order)} · {amount_bit}\n"
        f"COMPLETED с {time_str} (<code>{int(age)}</code> мин)"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔍 Открыть в ops",
                    "url": operator_url(f"/ops/orders?q={order.get('order_id', '')}"),
                }
            ]
        ]
    }
    return text, keyboard

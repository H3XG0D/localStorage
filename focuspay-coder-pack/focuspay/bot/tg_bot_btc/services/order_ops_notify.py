"""Короткие ops-уведомления в админ-группу + ссылка на кабинет оператора."""
from __future__ import annotations

from services.https_fetch import https_urlopen

import asyncio
import html
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from services.text_sanitize import sanitize_telegram_html
from services.payment_snapshot import order_payment_snapshot

logger = logging.getLogger("order_ops_notify")


def miniapp_ops_note(order: dict | None, note: str) -> str:
    """Ops-карточка миниаппки не должна выглядеть как сайт или чат бота."""
    if str((order or {}).get("order_source") or "").strip().lower() != "tg_miniapp":
        return note
    text = str(note or "").strip()
    if text.startswith("Миниаппка"):
        return text
    return f"Миниаппка · {text}" if text else "Миниаппка"


def _trust_level(paid_count: int) -> str:
    if paid_count == 0:
        return "🔴 Новый"
    if paid_count <= 3:
        return "🟡 Начинающий"
    if paid_count <= 9:
        return "🟢 Постоянный"
    if paid_count <= 19:
        return "🔵 Доверенный"
    return "⭐ VIP"


def _format_last_deal(last_paid_at) -> str:
    if last_paid_at is None:
        return "—"
    if isinstance(last_paid_at, str):
        try:
            last_paid_at = datetime.fromisoformat(last_paid_at)
        except ValueError:
            return str(last_paid_at)
    now = datetime.now(tz=timezone.utc)
    if last_paid_at.tzinfo is None:
        last_paid_at = last_paid_at.replace(tzinfo=timezone.utc)
    delta = now - last_paid_at
    days = delta.days
    if days == 0:
        return "сегодня"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"{days} дн. назад"
    if days < 30:
        weeks = days // 7
        return f"{weeks} нед. назад"
    months = days // 30
    return f"{months} мес. назад"


def _format_buyer_stats_block(stats: dict) -> str:
    paid_count = stats.get("paid_count") or 0
    last_paid_at = stats.get("last_paid_at")
    total_volume_rub = float(stats.get("total_volume_rub") or 0)

    trust = _trust_level(paid_count)
    last_str = _format_last_deal(last_paid_at)
    volume_str = f"{total_volume_rub:,.0f} ₽".replace(",", " ")

    taken = stats.get("payfast_taken")
    pf_paid = stats.get("payfast_paid")
    conv_pct = stats.get("conversion_pct")
    failed = int(stats.get("payfast_failed") or 0)
    if taken is not None and pf_paid is not None:
        denom = int(pf_paid) + failed
        if denom > 0 and conv_pct is not None:
            low = ""
            try:
                pct_f = float(conv_pct)
                if pct_f < 50.0:
                    low = " ⚠ низкая"
            except (TypeError, ValueError):
                pass
            conv = f"<b>{conv_pct:g}%</b> ({int(pf_paid)}/{denom}){low}"
        elif denom > 0:
            conv = f"{int(pf_paid)}/{denom}"
        else:
            conv = "нет данных (первая заявка)"
    else:
        conv = "нет данных"

    return (
        "\n👥 <b>Покупатель</b>\n"
        f"🔄 Сделок: <b>{paid_count}</b> · {last_str} · {trust}\n"
        f"📈 Конверсия: {conv} · Объём: <b>{volume_str}</b>"
    )


async def _resolve_buyer_stats(order: dict[str, Any], buyer_stats: dict | None) -> dict | None:
    if buyer_stats is not None:
        return buyer_stats
    uid = order.get("user_id")
    if not uid:
        return None
    try:
        from services.db import get_buyer_ops_stats, get_buyer_payfast_conversion

        stats = await get_buyer_ops_stats(int(uid))
        conv = await get_buyer_payfast_conversion(int(uid))
        stats["payfast_taken"] = conv.get("taken")
        stats["payfast_paid"] = conv.get("paid")
        stats["payfast_failed"] = conv.get("failed")
        stats["conversion_pct"] = conv.get("conversion_pct")
        return stats
    except Exception as e:
        logger.warning("buyer stats fetch failed user=%s: %s", uid, e)
        return None


def _resolve_buyer_stats_sync(order: dict[str, Any], buyer_stats: dict | None) -> dict | None:
    if buyer_stats is not None:
        return buyer_stats
    uid = order.get("user_id")
    if not uid:
        return None
    import asyncio

    from services.db import get_buyer_ops_stats, get_buyer_payfast_conversion

    try:
        asyncio.get_running_loop()
        return None
    except RuntimeError:
        pass
    try:
        stats = asyncio.run(get_buyer_ops_stats(int(uid)))
        conv = asyncio.run(get_buyer_payfast_conversion(int(uid)))
        stats["payfast_taken"] = conv.get("taken")
        stats["payfast_paid"] = conv.get("paid")
        stats["payfast_failed"] = conv.get("failed")
        stats["conversion_pct"] = conv.get("conversion_pct")
        return stats
    except Exception as e:
        logger.warning("buyer stats sync fetch failed user=%s: %s", uid, e)
        return None


def _contact_from_bot_user_row(
    result: dict[str, Any], row: Any
) -> dict[str, Any]:
    if not result["username"]:
        uname = (row.get("username") or "").lstrip("@").strip()
        result["username"] = uname or None
    first = (row.get("first_name") or "").strip()
    result["first_name"] = first or None
    result["first_seen_at"] = row.get("first_seen_at")
    result["last_seen_at"] = row.get("last_seen_at")
    return result


async def _resolve_client_contact(
    order: dict[str, Any], username: str | None
) -> dict[str, Any]:
    uid = order.get("user_id")
    result: dict[str, Any] = {
        "username": None,
        "first_name": None,
        "first_seen_at": None,
        "last_seen_at": None,
    }
    if username:
        uname = username.lstrip("@").strip()
        result["username"] = uname or None
    if not uid:
        return result
    try:
        from services.db import get_bot_user

        row = await get_bot_user(int(uid))
        if not row:
            return result
        return _contact_from_bot_user_row(result, row)
    except Exception as e:
        logger.warning("client contact fetch failed user=%s: %s", uid, e)
    return result


def _resolve_client_contact_sync(
    order: dict[str, Any], username: str | None
) -> dict[str, Any]:
    uid = order.get("user_id")
    result: dict[str, Any] = {
        "username": None,
        "first_name": None,
        "first_seen_at": None,
        "last_seen_at": None,
    }
    if username:
        uname = username.lstrip("@").strip()
        result["username"] = uname or None
    if not uid:
        return result
    import asyncio

    from services.db import get_bot_user

    try:
        asyncio.get_running_loop()
        return result
    except RuntimeError:
        pass
    try:
        row = asyncio.run(get_bot_user(int(uid)))
        if not row:
            return result
        return _contact_from_bot_user_row(result, row)
    except Exception as e:
        logger.warning("client contact sync fetch failed user=%s: %s", uid, e)
    return result


def _order_for_ops_message(order: dict[str, Any], contact: dict[str, Any]) -> dict[str, Any]:
    order_for_text = dict(order)
    first_seen = contact.get("first_seen_at")
    if first_seen is not None:
        order_for_text["bot_first_seen_at"] = first_seen
    return order_for_text


# Как в кабинете оператора (/ops/orders): не :g (режет до ~6 значащих цифр)
_OPS_CRYPTO_DECIMALS = {"btc": 8, "ltc": 8, "usdt": 2, "trx": 2}


def format_ops_crypto_amount(amount, crypto: str) -> str:
    base = str(crypto or "").split("_")[0].lower()
    dec = _OPS_CRYPTO_DECIMALS.get(base, 6)
    return f"{float(amount):.{dec}f}"


def format_ops_crypto_amount_html(amount, crypto: str) -> str:
    """Сумма крипты в <code> — удобно копировать тапом в Telegram."""
    return f"<code>{html.escape(format_ops_crypto_amount(amount, crypto))}</code>"


OPS_MSG_SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

# События, где показываем блок статистики покупателя
_BUYER_STATS_EVENTS = frozenset(
    {
        "awaiting_receipt",
        "receipt_requested_again",
        "video_requested",
        "receipt_attached",
        "receipt_ops_review",
        "awaiting_confirmation",
        "paid",
    }
)

_BILL_EVENTS = frozenset(
    {
        "created",
        "requisites_issued",
        "receipt_attached",
        "receipt_ops_review",
    }
)


def format_receipt_upload_duration(seconds: int) -> str:
    """Человекочитаемая длительность: 15 сек, 1 мин 23 сек."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} сек"
    minutes, rem = divmod(seconds, 60)
    if rem:
        return f"{minutes} мин {rem} сек"
    return f"{minutes} мин"


def format_receipt_upload_delay_line(order: dict[str, Any]) -> str | None:
    """Строка для ops: сколько прошло с открытия реквизитов / запроса PDF до чека."""
    if int(order.get("required_receipt_type") or 2) != 2:
        return None
    from services.db import get_receipt_submitted_at, get_receipt_timer_start_at

    started_at = get_receipt_timer_start_at(order)
    if started_at is None:
        return None
    submitted_at = get_receipt_submitted_at(order) or datetime.now(tz=timezone.utc)
    elapsed = int((submitted_at - started_at).total_seconds())
    return f"⏱ PDF отправлен за {format_receipt_upload_duration(elapsed)}"


def format_reuse_who_html(rows: list[dict] | None, *, limit: int = 5) -> str:
    """Совпадения IP/FP: ops-профиль + t.me (без «написать» в теле)."""
    from urllib.parse import quote

    bits: list[str] = []
    for r in (rows or [])[:limit]:
        uid = r.get("user_id")
        uname = (str(r.get("username") or "").strip().lstrip("@"))
        try:
            uid_i = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            uid_i = None

        parts: list[str] = []
        if uid_i is not None and uid_i > 0:
            profile = operator_client_url(uid_i)
            if uname:
                parts.append(
                    f'<a href="{html.escape(profile)}">@{html.escape(uname)}</a>'
                )
                parts.append(
                    f'<a href="https://t.me/{html.escape(uname)}">'
                    f"t.me/{html.escape(uname)}</a>"
                )
            else:
                parts.append(
                    f'<a href="{html.escape(profile)}">'
                    f"id {html.escape(str(uid_i))}</a>"
                )
                tg = telegram_open_url(uid_i)
                if tg:
                    parts.append(f'<a href="{html.escape(tg)}">Telegram</a>')
        elif uid_i is not None:
            profile = operator_client_url(uid_i)
            if uname:
                label = f"веб @{html.escape(uname)}"
            else:
                label = f"веб id {html.escape(str(uid_i))}"
            parts.append(f'<a href="{html.escape(profile)}">{label}</a>')
            parts.append("нет TG-аккаунта · только сайт")
        else:
            if uname:
                parts.append(f"@{html.escape(uname)}")
            else:
                parts.append("—")

        oid = str(r.get("order_id") or "").strip()
        st = str(r.get("status") or "").strip()
        if oid:
            ourl = operator_url(f"/ops/orders?q={quote(oid, safe='')}")
            parts.append(f'<a href="{html.escape(ourl)}">{html.escape(oid)}</a>')
            if st:
                parts.append(html.escape(st))
        bits.append(" · ".join(parts))
    return "; ".join(bits)


def format_reuse_who_compact(rows: list[dict] | None, *, limit: int = 5) -> str:
    """Короткий список @username / id для строки «общий FP»."""
    bits: list[str] = []
    for r in (rows or [])[:limit]:
        uname = (str(r.get("username") or "").strip().lstrip("@"))
        uid = r.get("user_id")
        if uname:
            bits.append(f"@{html.escape(uname)}")
        elif uid is not None:
            bits.append(f"id {html.escape(str(uid))}")
    return ", ".join(bits)


def format_device_signal_lines(order: dict[str, Any]) -> list[str]:
    """Строки устройства из snapshot / вложенного device_signal (если уже подгружен)."""
    snap = order_payment_snapshot(order)

    sig = order.get("device_signal") or snap.get("device_signal")
    lines: list[str] = []
    if isinstance(sig, dict) and (sig.get("ip") or sig.get("fingerprint") or sig.get("platform")):
        ip = html.escape(str(sig.get("ip") or "—"))
        plat = html.escape(str(sig.get("platform") or "—"))
        tz = html.escape(str(sig.get("timezone") or "—"))
        screen = html.escape(str(sig.get("screen") or "—"))
        fp = str(sig.get("fingerprint") or "")
        fp_short = html.escape((fp[:16] + "…") if len(fp) > 16 else (fp or "—"))
        lines.append("ℹ️ <b>Данные мини-аппа</b>")
        lines.append(f"📱 Устройство: {plat} · {screen}")
        lines.append(f"🌐 IP: <code>{ip}</code> · TZ {tz}")
        lines.append(f"🔏 FP: <code>{fp_short}</code>")
        if snap.get("device_fp_reuse") or snap.get("device_ip_reuse") or snap.get("device_fp_common"):
            if snap.get("device_fp_common"):
                n = snap.get("device_fp_user_count") or snap.get("device_reuse_count") or "?"
                who = format_reuse_who_compact(snap.get("device_fp_matches"))
                who_s = f" ({who})" if who else ""
                lines.append(f"👥 Общий FP модели: {n} акк.{who_s}")
            elif snap.get("device_fp_reuse"):
                fp_who = format_reuse_who_html(snap.get("device_fp_matches"))
                if fp_who:
                    lines.append(f"⚠️ FP совпал с: {fp_who}")
                else:
                    lines.append("⚠️ FP reuse")
            if snap.get("device_ip_reuse"):
                ip_who = format_reuse_who_html(snap.get("device_ip_matches"))
                if ip_who:
                    lines.append(f"⚠️ IP совпал с: {ip_who}")
                else:
                    lines.append(
                        "⚠️ IP совпал с другим аккаунтом "
                        "(список не сохранён — смотрите IP выше в ops)"
                    )
        attr = snap.get("attribution_label")
        if attr:
            lines.append(f"🎯 Реферал: {html.escape(str(attr))}")
        return lines

    # fallback: только IP с orders.client_ip
    cip = order.get("client_ip")
    if cip:
        lines.append("ℹ️ <b>Данные мини-аппа</b>")
        lines.append(f"🌐 IP: <code>{html.escape(str(cip))}</code>")
        if snap.get("device_ip_reuse"):
            ip_who = format_reuse_who_html(snap.get("device_ip_matches"))
            if ip_who:
                lines.append(f"⚠️ IP совпал с: {ip_who}")
            else:
                lines.append(
                    "⚠️ IP reuse — список совпадений не сохранён в заявке"
                )
    attr = snap.get("attribution_label")
    if attr:
        if not lines:
            lines.append("ℹ️ <b>Данные мини-аппа</b>")
        lines.append(f"🎯 Реферал: {html.escape(str(attr))}")
    return lines


def format_bill_lines_for_ops(order: dict[str, Any]) -> list[str]:
    """Реквизиты, которые видел клиент — в карточку оператора."""
    snap = order_payment_snapshot(order)
    bill = snap.get("bill")
    if not isinstance(bill, dict):
        return []
    bank = html.escape(str(bill.get("bank") or "—"))
    rec = html.escape(str(bill.get("reciver") or "—"))
    fio = html.escape(str(bill.get("fio") or "—"))
    return [
        "💳 <b>Реквизиты клиенту</b>",
        f"{bank} · <code>{rec}</code>",
        f"ФИО: {fio}",
    ]


def format_relative_duration(seconds: int) -> str:
    """Относительное время: 45 сек назад, 3 мин назад, 1 ч 12 мин назад."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} сек назад"
    minutes, sec_rem = divmod(seconds, 60)
    if minutes < 60:
        if sec_rem:
            return f"{minutes} мин {sec_rem} сек назад"
        return f"{minutes} мин назад"
    hours, min_rem = divmod(minutes, 60)
    if hours < 24:
        if min_rem:
            return f"{hours} ч {min_rem} мин назад"
        return f"{hours} ч назад"
    days, hour_rem = divmod(hours, 24)
    if hour_rem:
        return f"{days} дн {hour_rem} ч назад"
    return f"{days} дн назад"


def format_start_age_line(order: dict[str, Any]) -> str | None:
    """Строка для ops: когда клиент впервые нажал /start (first_seen_at)."""
    import datetime as dt_mod

    from services.db import _parse_snapshot_datetime

    raw = order.get("bot_first_seen_at")
    if raw is None:
        # старые вызовы могли класть last_seen под bot_last_seen_at — не используем:
        # last_seen обновляется при каждом /start и врёт для повторных клиентов.
        return None
    if isinstance(raw, dt_mod.datetime):
        seen_at = raw
    else:
        seen_at = _parse_snapshot_datetime(raw)
    if seen_at is None:
        return None
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=timezone.utc)
    elapsed = int((datetime.now(tz=timezone.utc) - seen_at).total_seconds())
    return f"первый /start {format_relative_duration(elapsed)}"


EVENT_TITLES = {
    "created": "🆕 Создан обмен",
    "requisites_issued": "👌 Одобрено оператором",
    "awaiting_receipt": "📎 Ожидает чек от клиента",
    "receipt_requested_again": "📎 Мерчант запросил чек повторно",
    "video_requested": "🎥 Запрошено видео у клиента",
    "receipt_attached": "📤 Чек отправлен мерчанту",
    "receipt_ops_review": "🔍 Чек на проверке оператором",
    "awaiting_confirmation": "⏳ Ожидает подтверждения оплаты",
    "merchant_confirmed": "✅ Мерчант подтвердил оплату",
    "awaiting_payout": "✅ Мерчант подтвердил оплату",
    "payout_reminder": "⏳ Ожидает выплату",
    "paid": "💸 Выплачено",
    "canceled": "❌ Отменена",
    "expired": "⌛️ Истекла",
}


def _ops_event_title(event: str, order: dict[str, Any]) -> str:
    """Заголовок карточки; для buy+bill «created» → «Одобрено оператором»."""
    direction = str(order.get("direction") or "buy").lower()
    if event == "created":
        snap = order_payment_snapshot(order)
        bill = snap.get("bill")
        if direction == "buy" and isinstance(bill, dict) and (
            bill.get("reciver") or bill.get("bank")
        ):
            return EVENT_TITLES["requisites_issued"]
    if event == "awaiting_payout" and direction == "sell":
        return "💰 Заявка · продажа"
    if event == "payout_reminder" and direction == "sell":
        return "⏳ Ожидает выплаты ₽"
    return EVENT_TITLES.get(event, "📋 Заявка")


def format_ops_tx_html(tx_hash: str, crypto: str | None = None) -> str | None:
    """Кликабельная TX-ссылка для ops (BTC → mempool.space через build_explorer_url)."""
    tx = str(tx_hash or "").strip()
    if not tx:
        return None
    from services.buy_payout import build_explorer_url

    url = build_explorer_url(str(crypto or "btc"), tx)
    short = tx if len(tx) <= 18 else f"{tx[:10]}…{tx[-6:]}"
    return (
        f'🔗 TX: <a href="{html.escape(url)}">'
        f"{html.escape(short)}</a>"
    )


def _format_ops_tx_line(order: dict[str, Any]) -> str | None:
    return format_ops_tx_html(
        str(order.get("payout_tx_hash") or ""),
        str(order.get("crypto") or ""),
    )


def public_site_url() -> str:
    from services import config_rates

    return (
        os.getenv("PUBLIC_SITE_URL")
        or getattr(config_rates, "PUBLIC_SITE_URL", "")
        or "https://focuspay.org"
    ).rstrip("/")


def operator_url(path: str = "/ops/login") -> str:
    return f"{public_site_url()}{path}"


def operator_client_url(user_id: int | str) -> str:
    """
    Ссылка на профиль клиента в ops.

    Канонический путь панели — /ops/client/{id}. Отрицательные id (веб-клиенты)
    нельзя класть как /ops/client/-33: Telegram обрезает URL на «/-…».
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return operator_url("/ops/client")
    if uid < 0:
        return operator_url(f"/ops/clients?uid={uid}")
    return operator_url(f"/ops/client/{uid}")


def telegram_username_url(username: str | None) -> str | None:
    """Return a Bot API-safe public Telegram URL when a username exists."""
    uname = (username or "").strip().lstrip("@")
    if not uname:
        return None
    return f"https://t.me/{quote(uname, safe='')}"


def telegram_open_url(
    user_id: int | str | None = None,
    username: str | None = None,
) -> str | None:
    """Open the client's Telegram: t.me/@user, else tg://user?id= for TG accounts."""
    try:
        uid = int(user_id) if user_id is not None else 0
    except (TypeError, ValueError):
        uid = 0
    if uid < 0:
        return None
    uname_url = telegram_username_url(username)
    if uname_url:
        return uname_url
    if uid > 0:
        return f"tg://user?id={uid}"
    return None


def ops_client_link_specs(
    user_id: int | str | None,
    username: str | None = None,
) -> list[tuple[str, str]]:
    """(label, url) for ops profile + Telegram. Empty if user_id is missing."""
    if user_id is None or user_id == "":
        return []
    out = [("👤 Профиль клиента", operator_client_url(user_id))]
    tg = telegram_open_url(user_id, username)
    if tg:
        out.append(("💬 Telegram", tg))
    return out


def format_ops_user_line(
    user_id: int | str | None,
    *,
    first_name: str | None = None,
    username: str | None = None,
    include_id: bool = False,
) -> str:
    """
    Единая строка клиента для ops-карточек:
    👤 Name(ops) · @user(t.me) · ID <code>…
    Без @username имя — mention tg://user?id=, чтобы тап открывал Telegram.
    """
    uname = (username or "").strip().lstrip("@") or None
    try:
        uid_i = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        uid_i = None

    if uid_i is not None:
        profile = operator_client_url(uid_i)
        label = html.escape(str(first_name or (f"@{uname}" if uname else uid_i)))
        tg = telegram_open_url(uid_i, uname)
        if uname and uid_i > 0:
            parts = [f'👤 <a href="{html.escape(profile)}">{label}</a>']
            parts.append(
                f'<a href="https://t.me/{html.escape(uname)}">'
                f"@{html.escape(uname)}</a>"
            )
        elif tg:
            parts = [f'👤 <a href="{html.escape(tg)}">{label}</a>']
        else:
            parts = [f'👤 <a href="{html.escape(profile)}">{label}</a>']
            if uname:
                parts.append(f"@{html.escape(uname)}")
        if include_id:
            parts.append(f"ID <code>{html.escape(str(uid_i))}</code>")
        return " · ".join(parts)

    if uname:
        return (
            f'👤 <a href="https://t.me/{html.escape(uname)}">'
            f"@{html.escape(uname)}</a>"
        )
    return "👤 —"


def format_ops_message(
    event: str,
    order: dict[str, Any],
    *,
    username: str | None = None,
    first_name: str | None = None,
    note: str | None = None,
    buyer_stats: dict | None = None,
) -> str:
    from services.merchant_order_id import format_ops_order_id_html

    title = _ops_event_title(event, order)
    direction = html.escape(str(order.get("direction", "buy")).upper())
    status = html.escape(str(order.get("status", "")))
    crypto_raw = str(order.get("crypto", "") or "")
    crypto_base = html.escape(crypto_raw.split("_")[0].upper() or crypto_raw.upper())
    fiat = order.get("fiat_amount")
    crypto_amt = order.get("crypto_amount")
    uid = order.get("user_id")
    user_line = format_ops_user_line(
        uid, first_name=first_name, username=username
    )

    amount_line = ""
    if fiat is not None:
        amount_line = f"💰 <b>{float(fiat):,.0f} ₽</b>".replace(",", " ")
        if crypto_amt is not None:
            amount_line += (
                f" · {format_ops_crypto_amount_html(crypto_amt, crypto_raw)}"
                f" {crypto_base}"
            )
        if status:
            amount_line += f" · {status}"

    lines = [
        f"<b>{title}</b> · {direction}",
        OPS_MSG_SEPARATOR,
        "",
        format_ops_order_id_html(order),
        user_line,
    ]
    if amount_line:
        lines.append(amount_line)
    direction_raw = str(order.get("direction", "buy")).lower()
    if direction_raw == "buy":
        wallet = (order.get("wallet_address") or order.get("requisites") or "").strip()
        if wallet:
            lines.append(f"👛 <code>{html.escape(wallet)}</code>")
    elif direction_raw == "sell":
        payout = (order.get("requisites") or "").strip()
        if payout:
            lines.append(f"👛 Выплата ₽: <code>{html.escape(payout)}</code>")
    if buyer_stats is not None and event in _BUYER_STATS_EVENTS:
        lines.append(_format_buyer_stats_block(buyer_stats))

    bill_lines = format_bill_lines_for_ops(order) if event in _BILL_EVENTS else []
    is_requisites_card = (
        event in ("created", "requisites_issued")
        and direction_raw == "buy"
        and bool(bill_lines)
    )

    if is_requisites_card:
        lines.append("")
        lines.extend(bill_lines)
        lines.append("")
        if note:
            lines.append(html.escape(note))
        else:
            lines.append("Клиент получил реквизиты. Ждём чек об оплате.")
    elif note:
        lines.append("")
        lines.append(
            sanitize_telegram_html(note)
            if event in ("receipt_ops_review", "receipt_attached")
            else html.escape(note)
        )
    elif event == "payout_reminder":
        crypto_raw = str(order.get("crypto") or "btc")
        coin = html.escape(crypto_raw.split("_")[0].upper())
        amt_html = format_ops_crypto_amount_html(
            order.get("crypto_amount") or 0, crypto_raw
        )
        lines.append("")
        lines.append(
            "🔔 Оплата подтверждена, крипта ещё не отправлена.\n"
            f"Проверьте и отправьте {amt_html} {coin} на кошелёк клиента."
        )
    elif event == "merchant_confirmed":
        lines.append("")
        lines.append("Отправьте крипту клиенту")

    if event in ("receipt_ops_review", "receipt_attached"):
        device_lines = format_device_signal_lines(order)
        if device_lines:
            lines.append("")
            lines.extend(device_lines)
        if bill_lines:
            # компактно: 💳 Банк · карта
            snap = order_payment_snapshot(order)
            bill = snap.get("bill")
            if isinstance(bill, dict):
                bank = html.escape(str(bill.get("bank") or "—"))
                rec = html.escape(str(bill.get("reciver") or "—"))
                lines.append(f"💳 {bank} · <code>{rec}</code>")
        delay = format_receipt_upload_delay_line(order)
        if delay:
            lines.append(html.escape(delay))
        start_age = format_start_age_line(order)
        if start_age:
            lines.append(html.escape(start_age))
    if event == "paid":
        tx_line = _format_ops_tx_line(order)
        if tx_line:
            lines.append("")
            lines.append(tx_line)
    return "\n".join(lines)


def build_ops_keyboard(
    order_id: str,
    *,
    user_id: int | None = None,
    username: str | None = None,
    pay_signature: str | None = None,
    sell: bool = False,
    wallet_early: bool = False,
) -> dict:
    """Inline-кнопки: кабинет оператора + опционально pay/cancel + досрочный запрос кошелька."""
    rows: list[list[dict]] = [
        [
            {"text": "👁 Кабинет оператора", "url": operator_url("/ops/login")},
            {"text": "📋 Заявки", "url": operator_url("/ops/orders")},
        ],
        [
            {
                "text": "🔍 Заявка",
                "url": operator_url(f"/ops/orders?q={order_id}"),
            }
        ],
    ]
    client_links = ops_client_link_specs(user_id, username)
    if client_links:
        rows.append([{"text": text, "url": url} for text, url in client_links])
    if pay_signature and wallet_early and not sell:
        rows.append(
            [
                {
                    "text": "⏩ Спросить кошелёк досрочно (убрать 5 мин)",
                    "callback_data": f"wask:{order_id}:{pay_signature}",
                }
            ]
        )
    if pay_signature:
        if sell:
            rows.append(
                [
                    {
                        "text": "✅ Крипта получена",
                        "callback_data": f"pay:{order_id}:{pay_signature}",
                    },
                    {
                        "text": "❌ Не поступила",
                        "callback_data": f"cancel:{order_id}:{pay_signature}",
                    },
                ]
            )
        else:
            rows.append(
                [
                    {
                        "text": "✅ Выплачено",
                        "callback_data": f"pay:{order_id}:{pay_signature}",
                    },
                    {
                        "text": "❌ Отменить",
                        "callback_data": f"cancel:{order_id}:{pay_signature}",
                    },
                ]
            )
    return {"inline_keyboard": rows}


def build_receipt_review_keyboard(
    order_id: str, signature: str, *, payin_rail: bool = False
) -> dict:
    """Inline-кнопки проверки чека. Payfast — «отправить мерчанту», реквизитчик — принять локально."""
    approve_text = "✅ Принять чек" if payin_rail else "✅ Отправить мерчанту"
    return {
        "inline_keyboard": [
            [
                {
                    "text": approve_text,
                    "callback_data": f"rcpt:approve:{order_id}:{signature}",
                },
                {
                    "text": "❌ Отклонить и забанить",
                    "callback_data": f"rcpt:reject:{order_id}:{signature}",
                },
            ],
            [
                {"text": "👁 Кабинет оператора", "url": operator_url("/ops/login")},
                {
                    "text": "🔍 Заявка",
                    "url": operator_url(f"/ops/orders?q={order_id}"),
                },
            ],
        ]
    }


def _admin_chat_id() -> int | None:
    from services import config_rates

    gid = config_rates.ops_group_id()
    return int(gid) if gid else None


def send_telegram_message_http(
    chat_id: int, text: str, reply_markup: dict | None = None
) -> bool:
    """sendMessage без объекта Bot — тот же токен, callback ловит живой бот."""
    import json
    import urllib.request

    from services import config_rates as cfg

    token = getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    if not token or not chat_id:
        return False
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        https_urlopen(req, timeout=15)
        return True
    except Exception as e:
        logger.warning("telegram message http failed chat=%s: %s", chat_id, e)
        return False


def send_local_telegram_file(
    chat_id: int,
    file_path: str,
    *,
    video: bool = False,
    caption: str | None = None,
) -> bool:
    """sendDocument/sendVideo локального файла без объекта Bot."""
    from pathlib import Path

    import requests

    from services import config_rates as cfg

    path = Path(file_path)
    token = getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    if not token or not chat_id or not path.is_file():
        return False
    method = "sendVideo" if video else "sendDocument"
    field = "video" if video else "document"
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]
    try:
        with path.open("rb") as fh:
            response = requests.post(
                url, data=data, files={field: (path.name, fh)}, timeout=60
            )
        body = response.json()
        if body.get("ok"):
            return True
        logger.warning("telegram file http failed chat=%s: %s", chat_id, body)
    except Exception as e:
        logger.warning("telegram file http failed chat=%s: %s", chat_id, e)
    return False


async def _ensure_reuse_matches_on_order(order: dict[str, Any]) -> None:
    """Дописать device_ip/fp_matches в snapshot, если reuse есть, а списка нет."""
    snap = order_payment_snapshot(order)

    need_ip = bool(snap.get("device_ip_reuse")) and not snap.get("device_ip_matches")
    need_fp = bool(snap.get("device_fp_reuse")) and not snap.get("device_fp_matches")
    if not need_ip and not need_fp:
        # Даже без флага — если есть IP/FP сигнала, подтянем совпадения для карточки.
        sig = order.get("device_signal") if isinstance(order.get("device_signal"), dict) else {}
        if not snap.get("device_ip_matches") and (sig.get("ip") or order.get("client_ip")):
            need_ip = True
        if not snap.get("device_fp_matches") and sig.get("fingerprint"):
            need_fp = True
    if not need_ip and not need_fp:
        return

    uid = order.get("user_id")
    try:
        uid_i = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid_i = None
    if not uid_i:
        return

    from services.db import (
        find_fingerprint_reuse,
        find_ip_reuse,
        serialize_reuse_matches,
    )

    sig = order.get("device_signal") if isinstance(order.get("device_signal"), dict) else {}
    patch: dict[str, Any] = {}

    if need_ip:
        client_ip = str(sig.get("ip") or order.get("client_ip") or "").strip() or None
        if client_ip and "/" in client_ip:
            client_ip = client_ip.split("/", 1)[0]
        if client_ip:
            rows = await find_ip_reuse(client_ip, uid_i)
            if rows:
                patch["device_ip_reuse"] = True
                patch["device_ip_matches"] = serialize_reuse_matches(rows)
                patch["device_reuse_count"] = max(
                    int(snap.get("device_reuse_count") or 0),
                    len({r.get("user_id") for r in rows if r.get("user_id") is not None}),
                )

    if need_fp:
        fp = str(sig.get("fingerprint") or "").strip() or None
        if fp:
            rows = await find_fingerprint_reuse(fp, uid_i)
            if rows:
                patch["device_fp_reuse"] = True
                patch["device_fp_matches"] = serialize_reuse_matches(rows)
                patch["device_reuse_count"] = max(
                    int(patch.get("device_reuse_count") or snap.get("device_reuse_count") or 0),
                    len({r.get("user_id") for r in rows if r.get("user_id") is not None}),
                )

    if not patch:
        return
    snap = {**snap, **patch}
    order["payment_snapshot"] = snap
    oid = str(order.get("order_id") or "").strip()
    if oid:
        try:
            from services.db import merge_order_payment_snapshot

            await merge_order_payment_snapshot(oid, patch)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)


def notify_ops_order_sync(
    event: str,
    order: dict[str, Any],
    *,
    username: str | None = None,
    note: str | None = None,
    pay_signature: str | None = None,
    sell: bool = False,
    buyer_stats: dict | None = None,
    wallet_early: bool = False,
) -> None:
    import json
    import urllib.request

    from services import config_rates as cfg

    chat_id = _admin_chat_id()
    if not chat_id:
        logger.warning(
            "ops notify skipped (TELEGRAM_OPS_GROUP_ID not set): event=%s order=%s",
            event,
            order.get("order_id"),
        )
        return

    buyer_stats = _resolve_buyer_stats_sync(order, buyer_stats)
    contact = _resolve_client_contact_sync(order, username)
    order_for_text = _order_for_ops_message(order, contact)
    text = format_ops_message(
        event,
        order_for_text,
        username=contact.get("username") or username,
        first_name=contact.get("first_name"),
        note=note,
        buyer_stats=buyer_stats,
    )
    order_id = str(order.get("order_id", ""))
    markup = build_ops_keyboard(
        order_id,
        user_id=order.get("user_id"),
        username=contact.get("username") or username,
        pay_signature=pay_signature,
        sell=sell,
        wallet_early=wallet_early,
    )
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": markup,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        https_urlopen(req, timeout=10)
    except Exception as e:
        logger.warning(
            "ops notify sync failed event=%s order=%s: %s",
            event,
            order.get("order_id"),
            e,
        )


async def notify_ops_order(
    event: str,
    order: dict[str, Any],
    bot=None,
    *,
    username: str | None = None,
    note: str | None = None,
    pay_signature: str | None = None,
    sell: bool = False,
    buyer_stats: dict | None = None,
    wallet_early: bool = False,
) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    chat_id = _admin_chat_id()
    if not chat_id:
        logger.warning(
            "ops notify skipped (TELEGRAM_OPS_GROUP_ID not set): event=%s order=%s",
            event,
            order.get("order_id"),
        )
        return

    buyer_stats = await _resolve_buyer_stats(order, buyer_stats)
    contact = await _resolve_client_contact(order, username)
    order_for_text = _order_for_ops_message(order, contact)
    if event in ("receipt_attached", "receipt_ops_review"):
        try:
            from services.db import get_latest_device_signal_for_order

            sig = await get_latest_device_signal_for_order(str(order.get("order_id") or ""))
            if sig:
                order_for_text["device_signal"] = {
                    "ip": sig.get("ip"),
                    "fingerprint": sig.get("fingerprint"),
                    "platform": sig.get("platform"),
                    "screen": sig.get("screen"),
                    "timezone": sig.get("timezone"),
                }
        except Exception as e:
            logger.debug("device signal attach: %s", e)
    text = format_ops_message(
        event,
        order_for_text,
        username=contact.get("username") or username,
        first_name=contact.get("first_name"),
        note=note,
        buyer_stats=buyer_stats,
    )
    order_id = str(order.get("order_id", ""))
    raw = build_ops_keyboard(
        order_id,
        user_id=order.get("user_id"),
        username=contact.get("username") or username,
        pay_signature=pay_signature,
        sell=sell,
        wallet_early=wallet_early,
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(btn["text"], url=btn["url"])
                if "url" in btn
                else InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in raw["inline_keyboard"]
        ]
    )

    try:
        if bot:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        else:
            await asyncio.to_thread(
                notify_ops_order_sync,
                event,
                order,
                username=username,
                note=note,
                pay_signature=pay_signature,
                sell=sell,
                buyer_stats=buyer_stats,
                wallet_early=wallet_early,
            )
    except Exception as e:
        logger.warning(
            "ops notify async failed event=%s order=%s: %s",
            event,
            order.get("order_id"),
            e,
        )


async def notify_ops_receipt_review(
    order: dict[str, Any],
    bot,
    *,
    username: str | None = None,
    review_signature: str,
    note: str | None = None,
    prefer_client_review_group: bool = False,
    payin_rail: bool = False,
) -> None:
    """Ops-карточка с кнопками проверки чека перед Payfast / реквизитчиком."""
    from services import config_rates

    chat_id = None
    if prefer_client_review_group:
        chat_id = config_rates.client_review_group_id()
    if not chat_id:
        chat_id = _admin_chat_id()
    if not chat_id:
        logger.warning(
            "ops receipt review skipped (no group): order=%s",
            order.get("order_id"),
        )
        return

    buyer_stats = await _resolve_buyer_stats(order, None)
    contact = await _resolve_client_contact(order, username)
    order_for_text = _order_for_ops_message(order, contact)
    try:
        from services.db import get_latest_device_signal_for_order

        sig = await get_latest_device_signal_for_order(str(order.get("order_id") or ""))
        if sig:
            order_for_text["device_signal"] = {
                "ip": sig.get("ip"),
                "fingerprint": sig.get("fingerprint"),
                "platform": sig.get("platform"),
                "screen": sig.get("screen"),
                "timezone": sig.get("timezone"),
            }
    except Exception as e:
        logger.debug("device signal attach: %s", e)

    # Если reuse-флаг есть, а список «с кем» пуст — добрать live для карточки.
    try:
        await _ensure_reuse_matches_on_order(order_for_text)
    except Exception as e:
        logger.debug("reuse matches enrich: %s", e)

    text = format_ops_message(
        "receipt_ops_review",
        order_for_text,
        username=contact.get("username") or username,
        first_name=contact.get("first_name"),
        note=note or "Проверьте чек перед отправкой мерчанту",
        buyer_stats=buyer_stats,
    )
    order_id = str(order.get("order_id", ""))
    raw = build_receipt_review_keyboard(
        order_id, review_signature, payin_rail=payin_rail
    )
    if bot is None:
        await asyncio.to_thread(send_telegram_message_http, chat_id, text, raw)
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error import BadRequest

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(btn["text"], url=btn["url"])
                if "url" in btn
                else InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"])
                for btn in row
            ]
            for row in raw["inline_keyboard"]
        ]
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        logger.warning(
            "ops receipt review notify failed order=%s: %s",
            order.get("order_id"),
            e,
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as fallback_error:
            logger.warning(
                "ops receipt review fallback failed order=%s: %s",
                order.get("order_id"),
                fallback_error,
            )
    except Exception as e:
        logger.warning(
            "ops receipt review notify failed order=%s: %s",
            order.get("order_id"),
            e,
        )


async def notify_appeals_video(
    order: dict[str, Any],
    *,
    bot=None,
    file_id: str = "",
    local_path: str | None = None,
    as_document: bool = False,
    username: str | None = None,
) -> bool:
    """Видео в группу споров Payfast (только файл + ID заявки). True если ушло."""
    from services import config_rates

    chat_id = config_rates.appeals_group_id()
    if not chat_id or (not file_id and not local_path):
        return False
    if file_id and not bot and not local_path:
        return False

    from services.merchant_order_id import resolve_merchant_display_id

    oid = str(order.get("order_id", "")).strip()
    if not oid:
        return False

    caption = resolve_merchant_display_id(order)

    if local_path and not file_id:
        if bot is None:
            return await asyncio.to_thread(
                send_local_telegram_file,
                int(chat_id),
                local_path,
                video=not as_document,
                caption=caption,
            )
        from pathlib import Path

        path = Path(local_path)
        if not path.is_file():
            return False
        try:
            with path.open("rb") as fh:
                if as_document:
                    await bot.send_document(chat_id=chat_id, document=fh, caption=caption)
                else:
                    await bot.send_video(chat_id=chat_id, video=fh, caption=caption)
            return True
        except Exception as e:
            logger.warning("appeals local video failed chat=%s: %s", chat_id, e)
            if as_document:
                return False
            try:
                with path.open("rb") as fh:
                    await bot.send_document(chat_id=chat_id, document=fh, caption=caption)
                return True
            except Exception as fallback_error:
                logger.warning(
                    "appeals local video document fallback failed chat=%s: %s",
                    chat_id,
                    fallback_error,
                )
                return False

    if not bot or not file_id:
        return False

    async def _send_document() -> None:
        await bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption,
        )

    try:
        if as_document:
            await _send_document()
        else:
            await bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
            )
        return True
    except Exception as e:
        logger.warning("appeals video notify failed chat=%s: %s", chat_id, e)
        if as_document:
            return False
        try:
            await _send_document()
            return True
        except Exception as fallback_error:
            logger.warning(
                "appeals video document fallback failed chat=%s: %s",
                chat_id,
                fallback_error,
            )
            return False


async def notify_ops_withdrawal(
    wd: dict[str, Any],
    bot=None,
    *,
    username: str | None = None,
) -> int | None:
    """Уведомление о выводе баланса — в ту же ops-группу, что и обмены."""
    from services.user_referral_withdraw import (
        format_withdrawal_admin_message,
        withdrawal_admin_keyboard,
    )

    chat_id = _admin_chat_id()
    if not chat_id:
        logger.warning(
            "ops notify skipped (TELEGRAM_OPS_GROUP_ID not set): event=%s order=%s",
            event,
            order.get("order_id"),
        )
        return None

    text = format_withdrawal_admin_message(wd, username)
    keyboard = withdrawal_admin_keyboard(int(wd["id"]), source=wd.get("source"))

    try:
        if bot:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            return sent.message_id
        import json
        import urllib.request

        from services import config_rates as cfg

        url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard.to_dict(),
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        with https_urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return data.get("result", {}).get("message_id")
    except Exception as e:
        logger.warning("ops withdrawal notify failed: %s", e)
    return None

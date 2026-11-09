""" /stat и /check в группе споров Payfast: статистика клиента по ID заявки. """
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.appeals_messages import _extract_appeals_order_ref
from services.payment_snapshot import order_payment_snapshot
from services.config_rates import (
    TELEGRAM_ADMIN_IDS,
    is_appeals_group_chat,
    is_community_chat,
    is_external_deals_group_chat,
    is_news_chat,
    is_ops_group_chat,
    is_reports_group_chat,
)
from services.db import (
    find_order_for_stat,
    get_buyer_stat_summary,
    get_external_client_stat,
    get_external_deal_by_merchant_ref,
)
from services.merchant_order_id import format_ops_order_id_html
from services.order_ops_notify import _format_last_deal, _trust_level
from services.text_sanitize import sanitize_telegram_html

logger = logging.getLogger("appeals_stat")

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_ORDER_ID_RE = re.compile(r"^\d{6,12}$")
_EXT_RE = re.compile(r"^EXT-\d+$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"^[0-9A-Za-z_-]{6,64}$")

_HINT = (
    "Использование: <code>/stat ID_заявки</code> или <code>/check ID</code> "
    "или ответьте командой на видео с ID."
)
_NOT_FOUND = "Заявка не найдена."
_NO_USER = "Не удалось определить клиента по этой заявке."

_STATUS_AS_ORDER = {
    "confirmed": "PAID",
    "pending": "AWAITING_CHECK",
    "awaiting_receipt": "PENDING",
    "cancelled": "CANCELED",
    "canceled": "CANCELED",
}


def can_run_stat(chat_id: int | None, user_id: int | None) -> bool:
    """Админы — в любом служебном чате; остальные — только в рабочих группах."""
    if is_community_chat(chat_id) or is_news_chat(chat_id):
        return False
    uid = int(user_id or 0)
    if uid and uid in TELEGRAM_ADMIN_IDS:
        return True
    return (
        is_appeals_group_chat(chat_id)
        or is_ops_group_chat(chat_id)
        or is_external_deals_group_chat(chat_id)
        or is_reports_group_chat(chat_id)
    )


def parse_stat_ref(raw: str | None) -> str | None:
    """Payfast uuid, наш order_id или EXT-id из аргумента / caption."""
    text = (raw or "").strip()
    if not text:
        return None
    token = text.split()[0].strip().lstrip("#").rstrip(".,;")
    if _UUID_RE.fullmatch(token) or _ORDER_ID_RE.fullmatch(token) or _EXT_RE.fullmatch(token):
        return token
    uuid = _UUID_RE.search(text)
    if uuid:
        return uuid.group(0)
    extracted = _extract_appeals_order_ref(text)
    if extracted:
        return extracted.lstrip("#").rstrip(".,;")
    if _TOKEN_RE.fullmatch(token):
        return token
    return None


def client_alias(user_id: int) -> str:
    """Короткий псевдоним без Telegram id / username."""
    return f"#{abs(int(user_id)) % 10000:04d}"


def fingerprint_alias_seed(
    exchanger_id: int, fingerprint: str | None, deal_id: int | None = None
) -> int:
    """Стабильный seed для #NNNN — без Telegram id и без имени магазина."""
    raw = str(fingerprint or "").strip()
    if raw:
        digest = hashlib.sha256(f"{int(exchanger_id)}:{raw}".encode("utf-8")).hexdigest()
        n = int(digest[:12], 16)
        return n if n > 0 else 1
    if deal_id:
        return abs(int(deal_id))
    return abs(int(exchanger_id or 0))


def deal_status_as_order(status: str | None) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_AS_ORDER.get(key, (str(status or "PENDING").upper() or "PENDING"))


def empty_client_stat() -> dict:
    return {
        "paid_orders": 0,
        "total_orders": 0,
        "buy_paid": 0,
        "buy_failed": 0,
        "conversion_pct": None,
        "turnover_rub": 0.0,
        "first_order_at": None,
        "last_paid_at": None,
    }


def summary_from_client_stat(raw) -> dict:
    """Сводка магазина → те же ключи, что get_buyer_stat_summary."""
    if raw is None:
        return empty_client_stat()
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return empty_client_stat()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return empty_client_stat()
    if not isinstance(raw, dict):
        return empty_client_stat()
    try:
        paid = max(0, int(raw.get("paid_orders") or 0))
    except (TypeError, ValueError):
        paid = 0
    try:
        buy_paid = max(0, int(raw.get("buy_paid") if raw.get("buy_paid") is not None else paid))
    except (TypeError, ValueError):
        buy_paid = paid
    try:
        buy_failed = max(0, int(raw.get("buy_failed") or 0))
    except (TypeError, ValueError):
        buy_failed = 0
    try:
        total = max(0, int(raw.get("total_orders") or 0))
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        total = buy_paid + buy_failed
    denom = buy_paid + buy_failed
    conv_raw = raw.get("conversion_pct")
    if conv_raw is None or conv_raw == "":
        conv = round(100.0 * buy_paid / denom, 1) if denom > 0 else None
    else:
        try:
            conv = round(float(conv_raw), 1)
        except (TypeError, ValueError):
            conv = round(100.0 * buy_paid / denom, 1) if denom > 0 else None
    try:
        turnover = float(raw.get("turnover_rub") or 0)
    except (TypeError, ValueError):
        turnover = 0.0
    return {
        "paid_orders": paid,
        "total_orders": total,
        "buy_paid": buy_paid,
        "buy_failed": buy_failed,
        "conversion_pct": conv,
        "turnover_rub": turnover,
        "first_order_at": raw.get("first_order_at"),
        "last_paid_at": raw.get("last_paid_at"),
    }


def order_from_external_deal(deal: dict) -> dict:
    """HMAC-сделка → как наша BUY-заявка для format_stat_card."""
    deal_id = int(deal.get("id") or 0)
    exchanger_id = int(deal.get("exchanger_id") or 0)
    fingerprint = str(deal.get("customer_fingerprint") or deal.get("fingerprint") or "").strip()
    merchant = str(deal.get("merchant_order_id") or "").strip()
    ext_id = f"EXT-{deal_id}" if deal_id else merchant
    return {
        "order_id": ext_id,
        "merchant_order_id": merchant or ext_id,
        "user_id": fingerprint_alias_seed(exchanger_id, fingerprint, deal_id),
        "status": deal_status_as_order(str(deal.get("status") or "")),
        "fiat_amount": float(deal.get("client_pays_rub") or 0),
        "crypto": str(deal.get("crypto") or "usdt").lower(),
        "direction": "buy",
        "payment_snapshot": deal.get("payment_snapshot"),
    }


def _as_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def _fmt_first_seen(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.strftime("%d.%m.%Y")


def _fmt_volume(amount: float) -> str:
    return f"{float(amount or 0):,.0f} ₽".replace(",", " ")


def _fmt_conversion(summary: dict) -> str:
    paid = int(summary.get("buy_paid") or 0)
    failed = int(summary.get("buy_failed") or 0)
    conv_pct = summary.get("conversion_pct")
    denom = paid + failed
    if denom <= 0:
        return "нет данных (первая заявка)"
    if conv_pct is None:
        return f"{paid}/{denom}"
    low = ""
    try:
        if float(conv_pct) < 50.0:
            low = " ⚠ низкая"
    except (TypeError, ValueError):
        pass
    return f"<b>{conv_pct:g}%</b> ({paid}/{denom}){low}"


def _fmt_receipt_state(order: dict) -> str | None:
    """Одна строка про чек: файл, операторский холд, автоповтор в Payfast."""
    snap = order_payment_snapshot(order)
    receipt_file = str(order.get("receipt_file") or "").strip()
    ops_pending = bool(snap.get("receipt_ops_pending"))
    pending = snap.get("receipt_send_pending")
    pending_active = (
        isinstance(pending, dict)
        and bool(str(pending.get("receipt_name") or "").strip())
        and not pending.get("done_at")
    )
    if not receipt_file and not ops_pending and not pending_active:
        return None
    if ops_pending:
        state = "на проверке у оператора"
    elif pending_active:
        attempts = pending.get("attempts") or 0
        try:
            attempts_n = int(attempts)
        except (TypeError, ValueError):
            attempts_n = 0
        extra = f" · попыток {attempts_n}" if attempts_n > 0 else ""
        state = f"сохранён, автоповтор отправки в Payfast{extra}"
    elif str(order.get("status") or "").upper() == "PENDING":
        state = "отправлен мерчанту"
    else:
        state = "сохранён, ждёт отправки"
    if receipt_file:
        return f"🧾 Чек: {state} · <code>{html.escape(receipt_file)}</code>"
    return f"🧾 Чек: {state}"


def format_stat_card(order: dict, summary: dict) -> str:
    """HTML-карточка без персональных данных клиента."""
    uid = int(order.get("user_id") or 0)
    status = html.escape(str(order.get("status") or "—"))
    crypto = html.escape(str(order.get("crypto") or "—").upper())
    fiat = _fmt_volume(float(order.get("fiat_amount") or 0))
    paid_orders = int(summary.get("paid_orders") or 0)
    total_orders = int(summary.get("total_orders") or 0)
    buy_failed = int(summary.get("buy_failed") or 0)
    turnover = _fmt_volume(float(summary.get("turnover_rub") or 0))
    last_str = _format_last_deal(summary.get("last_paid_at"))
    trust = _trust_level(paid_orders)
    first_seen = _fmt_first_seen(summary.get("first_order_at"))

    lines = [
        "📊 <b>Статистика по заявке</b>",
        format_ops_order_id_html(order),
        f"Статус заявки: <b>{status}</b> · {html.escape(fiat)} · {crypto}",
    ]
    receipt_state = _fmt_receipt_state(order)
    if receipt_state:
        lines.append(receipt_state)
    lines.extend(
        [
            "",
            f"👤 Клиент {html.escape(client_alias(uid))}",
            f"🔄 Оплаченных сделок: <b>{paid_orders}</b> · {html.escape(last_str)} · {trust}",
            f"📈 Конверсия BUY: {_fmt_conversion(summary)}",
            (
                f"🧾 Заявок всего: <b>{total_orders}</b> · оплачено <b>{paid_orders}</b>"
                f" · отменено/просрочено <b>{buy_failed}</b>"
            ),
            f"💰 Объём: <b>{html.escape(turnover)}</b>",
        ]
    )
    if first_seen:
        lines.append(f"🗓 С нами с {html.escape(first_seen)}")
    return sanitize_telegram_html("\n".join(lines))


def _ref_from_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    args = list(getattr(context, "args", None) or [])
    if args:
        joined = " ".join(str(a) for a in args).strip()
        parsed = parse_stat_ref(joined)
        if parsed:
            return parsed
    msg = update.message or update.effective_message
    reply = getattr(msg, "reply_to_message", None) if msg else None
    if reply:
        raw = (getattr(reply, "caption", None) or getattr(reply, "text", None) or "").strip()
        parsed = parse_stat_ref(raw)
        if parsed:
            return parsed
    return None


async def appeals_stat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message or update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat:
        return
    user_id = int(getattr(user, "id", 0) or 0)
    logger.info("stat cmd chat=%s user=%s", chat.id, user_id or None)
    if not can_run_stat(chat.id, user_id):
        logger.info("stat ignored chat=%s user=%s", chat.id, user_id or None)
        return

    ref = _ref_from_update(update, context)
    if not ref:
        await msg.reply_text(_HINT, parse_mode="HTML")
        return

    try:
        order_row = await find_order_for_stat(ref)
    except Exception as e:
        logger.warning("stat lookup failed ref=%s: %s", ref, e)
        await msg.reply_text(_NOT_FOUND)
        return

    if order_row:
        order = _as_dict(order_row)
        uid = order.get("user_id")
        try:
            uid_int = int(uid)
        except (TypeError, ValueError):
            uid_int = 0
        if not uid_int:
            await msg.reply_text(_NO_USER)
            return
        try:
            summary = await get_buyer_stat_summary(uid_int)
        except Exception as e:
            logger.warning("stat summary failed user=%s: %s", uid_int, e)
            await msg.reply_text(_NOT_FOUND)
            return
        text = format_stat_card(order, summary)
        await msg.reply_text(text, parse_mode="HTML")
        logger.info(
            "stat shown ref=%s order=%s alias=%s",
            ref,
            order.get("order_id"),
            client_alias(uid_int),
        )
        return

    try:
        ext_row = await get_external_deal_by_merchant_ref(ref)
    except Exception as e:
        logger.warning("stat external lookup failed ref=%s: %s", ref, e)
        ext_row = None
    if not ext_row:
        await msg.reply_text(_NOT_FOUND)
        return

    deal = _as_dict(ext_row)
    summary = summary_from_client_stat(deal.get("client_stat"))
    if not deal.get("client_stat"):
        fp = str(deal.get("customer_fingerprint") or "").strip()
        try:
            cached = await get_external_client_stat(int(deal.get("exchanger_id") or 0), fp)
        except Exception as e:
            logger.warning("stat fingerprint cache failed ref=%s: %s", ref, e)
            cached = None
        cached_d = _as_dict(cached)
        if cached_d.get("payload") is not None:
            summary = summary_from_client_stat(cached_d.get("payload"))

    order = order_from_external_deal(deal)
    text = format_stat_card(order, summary)
    await msg.reply_text(text, parse_mode="HTML")
    logger.info(
        "stat shown ref=%s ext=%s alias=%s",
        ref,
        deal.get("id"),
        client_alias(int(order.get("user_id") or 0)),
    )

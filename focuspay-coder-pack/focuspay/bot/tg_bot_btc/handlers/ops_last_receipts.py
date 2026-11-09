""" /last N id в группе ops-уведомлений: прошлые чеки покупателя и его заявки. """
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from handlers.appeals_stat import parse_stat_ref
from services.config_rates import is_ops_group_chat
from services.db import (
    buyer_has_orders,
    get_buyer_ops_stats,
    get_recent_receipt_orders,
)
from services.merchant_order_id import resolve_merchant_display_id
from services.order_ops_notify import _trust_level
from services.receipts_storage import receipts_dir
from services.text_sanitize import sanitize_telegram_html

logger = logging.getLogger("ops_last_receipts")

_MSK = timezone(timedelta(hours=3))
_MAX_N = 10
_VIDEO_EXT = frozenset({"mp4", "mov", "avi", "webm", "mkv"})
_CODE_RE = re.compile(r"<code>([^<]+)</code>", re.IGNORECASE)

_HINT = "Использование: <code>/last 5 id</code>"
_NOT_FOUND = "Покупатель не найден."
_LOAD_FAILED = "Не удалось загрузить чеки."


def clamp_last_count(raw: str) -> int | None:
    """1..10. Число больше 10 режется до 10. Ноль и нечисло — нет."""
    text = (raw or "").strip()
    if not text.isdigit():
        return None
    n = int(text)
    if n < 1:
        return None
    return min(n, _MAX_N)


def ref_from_reply_text(raw: str | None) -> str | None:
    """Id из текста карточки: как /stat, плюс <code> в ops-сообщении."""
    text = (raw or "").strip()
    if not text:
        return None
    parsed = parse_stat_ref(text)
    if parsed:
        return parsed
    for match in _CODE_RE.finditer(text):
        inner = match.group(1).strip()
        parsed = parse_stat_ref(inner)
        if parsed:
            return parsed
        if inner.isdigit() and int(inner) > 0:
            return str(int(inner))
    return None


def _ref_from_arg_tokens(tokens: list[str]) -> str | None:
    joined = " ".join(tokens).strip()
    parsed = parse_stat_ref(joined)
    if parsed:
        return parsed
    token = tokens[0].lstrip("#").strip() if tokens else ""
    if token.isdigit() and int(token) > 0:
        return str(int(token))
    return None


def parse_last_request(
    args: list[str] | None,
    *,
    reply_text: str | None = None,
    reply_caption: str | None = None,
) -> tuple[int | None, str | None]:
    """(count, ref). count is None — показать подсказку. ref None — id не разобран."""
    parts = [str(a).strip() for a in (args or []) if str(a).strip()]
    if not parts:
        return None, None
    count = clamp_last_count(parts[0])
    if count is None:
        return None, None
    if len(parts) > 1:
        return count, _ref_from_arg_tokens(parts[1:])
    ref = ref_from_reply_text(reply_caption) or ref_from_reply_text(reply_text)
    return count, ref


def receipt_file_path(receipt_name: str, root: Path) -> Path | None:
    """Только basename внутри каталога чеков. Ссылки наружу и `..` отбрасываются."""
    raw = str(receipt_name or "").strip()
    if not raw or raw in {".", ".."}:
        return None
    if raw != Path(raw).name or "/" in raw or "\\" in raw or "\x00" in raw:
        return None
    base = root.resolve()
    candidate = (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


_DOCUMENT_EXT = frozenset({"pdf", "gif", "jpg", "jpeg", "png", "webp"})


def receipt_is_video(receipt_name: str, order: dict) -> bool:
    """PDF и картинки остаются документом, даже если по заявке запрошено видео."""
    ext = Path(str(receipt_name or "")).suffix.lstrip(".").lower()
    if ext in _VIDEO_EXT:
        return True
    if ext in _DOCUMENT_EXT:
        return False
    try:
        return int(order.get("required_receipt_type") or 2) == 3
    except (TypeError, ValueError):
        return False


def _fmt_when(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)[:16]
    if not isinstance(value, datetime):
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_MSK).strftime("%d.%m %H:%M")


def _fmt_rub(amount) -> str:
    try:
        n = float(amount or 0)
    except (TypeError, ValueError):
        n = 0.0
    return f"{n:,.0f} ₽".replace(",", " ")


def _as_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return {}


def format_order_line(order: dict, *, file_missing: bool) -> str:
    disp = resolve_merchant_display_id(order)
    status = html.escape(str(order.get("status") or "—"))
    when = html.escape(_fmt_when(order.get("created_at")))
    fiat = html.escape(_fmt_rub(order.get("fiat_amount")))
    line = f"🆔 <code>{html.escape(disp)}</code> · {fiat} · {status} · {when}"
    if file_missing:
        line += " · файла нет"
    return line


def format_receipt_caption(order: dict) -> str:
    disp = resolve_merchant_display_id(order)
    status = html.escape(str(order.get("status") or "—"))
    when = html.escape(_fmt_when(order.get("created_at")))
    fiat = html.escape(_fmt_rub(order.get("fiat_amount")))
    return sanitize_telegram_html(
        f"🆔 <code>{html.escape(disp)}</code> · {fiat} · {status} · {when}"
    )


def format_last_summary(user_id: int, stats: dict, orders: list[dict]) -> str:
    paid = int(stats.get("paid_count") or 0)
    trust = _trust_level(paid)
    lines = [
        "🧾 <b>Последние чеки</b>",
        f"👤 ID <code>{html.escape(str(int(user_id)))}</code> · {trust}",
        f"🔄 Сделок: <b>{paid}</b>",
        "",
    ]
    if not orders:
        lines.append("Чеков нет.")
    else:
        for order in orders:
            lines.append(format_order_line(order, file_missing=bool(order.get("_file_missing"))))
    return sanitize_telegram_html("\n".join(lines))


async def resolve_buyer_id(ref: str) -> int | None:
    """Сначала заявка (Payfast / order_id), иначе Telegram id, если у него есть заявки."""
    from services.db import find_order_for_stat

    row = await find_order_for_stat(ref)
    if row:
        order = _as_dict(row)
        try:
            uid = int(order.get("user_id") or 0)
        except (TypeError, ValueError):
            uid = 0
        if uid > 0:
            return uid
    token = str(ref or "").strip()
    if token.isdigit():
        uid = int(token)
        if uid > 0 and await buyer_has_orders(uid):
            return uid
    return None


def _attach_receipt_paths(orders: list[dict], root: Path) -> list[dict]:
    ready: list[dict] = []
    for order in orders:
        name = str(order.get("receipt_file") or "").strip()
        path = receipt_file_path(name, root)
        if path is None or not path.is_file():
            order["_file_missing"] = True
            continue
        order["_file_missing"] = False
        order["_path"] = path
        ready.append(order)
    return ready


async def _send_receipt_file(bot, chat_id: int, path: Path, caption: str, video: bool) -> bool:
    try:
        with path.open("rb") as fh:
            if video:
                await bot.send_video(
                    chat_id=chat_id,
                    video=fh,
                    caption=caption,
                    parse_mode="HTML",
                )
            else:
                await bot.send_document(
                    chat_id=chat_id,
                    document=fh,
                    caption=caption,
                    parse_mode="HTML",
                )
        return True
    except Exception as e:
        logger.warning("last receipt send failed path=%s: %s", path.name, e)
        if not video:
            return False
    try:
        with path.open("rb") as fh:
            await bot.send_document(
                chat_id=chat_id,
                document=fh,
                caption=caption,
                parse_mode="HTML",
            )
        return True
    except Exception as e:
        logger.warning("last receipt document fallback failed path=%s: %s", path.name, e)
        return False


async def ops_last_receipts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message or update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if not is_ops_group_chat(chat.id):
        logger.info("last ignored chat=%s", chat.id)
        return

    reply = getattr(msg, "reply_to_message", None)
    count, ref = parse_last_request(
        list(getattr(context, "args", None) or []),
        reply_text=getattr(reply, "text", None) if reply else None,
        reply_caption=getattr(reply, "caption", None) if reply else None,
    )
    if count is None or not ref:
        await msg.reply_text(_HINT, parse_mode="HTML")
        return

    try:
        buyer_id = await resolve_buyer_id(ref)
    except Exception as e:
        logger.warning("last lookup failed ref=%s: %s", ref, e)
        await msg.reply_text(_NOT_FOUND)
        return
    if not buyer_id:
        await msg.reply_text(_NOT_FOUND)
        return

    try:
        stats = await get_buyer_ops_stats(buyer_id)
        rows = await get_recent_receipt_orders(buyer_id, count)
    except Exception as e:
        logger.warning("last load failed user=%s: %s", buyer_id, e)
        await msg.reply_text(_LOAD_FAILED)
        return

    orders = [_as_dict(row) for row in (rows or [])]
    ready = _attach_receipt_paths(orders, receipts_dir())
    text = format_last_summary(buyer_id, stats or {}, orders)
    await msg.reply_text(text, parse_mode="HTML")

    bot = getattr(context, "bot", None)
    failed = 0
    if bot is None:
        failed = len(ready)
    else:
        for order in ready:
            name = str(order.get("receipt_file") or "")
            ok = await _send_receipt_file(
                bot,
                int(chat.id),
                order["_path"],
                format_receipt_caption(order),
                receipt_is_video(name, order),
            )
            if not ok:
                failed += 1
    if failed:
        await msg.reply_text(f"Не удалось отправить файлов: {failed}.")
    logger.info(
        "last shown ref=%s user=%s orders=%s files=%s failed=%s",
        ref,
        buyer_id,
        len(orders),
        len(ready),
        failed,
    )

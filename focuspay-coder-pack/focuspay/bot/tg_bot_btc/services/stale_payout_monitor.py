"""Алерты владельцу: BUY COMPLETED без PAID дольше порога."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services import config_rates
from services.db import (
    get_negative_ledger_accounts,
    get_stale_completed_buy_orders,
    is_stale_alert_sent,
    mark_stale_alert_sent,
)
from services.owner_dashboard import format_stale_payout_alert

logger = logging.getLogger("stale_payout_monitor")
_NEG_LEDGER_STATE = Path("/var/lib/focuspay/neg-ledger-alert.json")


def _load_neg_sig() -> str | None:
    try:
        raw = json.loads(_NEG_LEDGER_STATE.read_text(encoding="utf-8"))
    except Exception:
        return None
    sig = raw.get("sig") if isinstance(raw, dict) else None
    return str(sig) if sig else None


def _save_neg_sig(sig: str | None) -> None:
    try:
        _NEG_LEDGER_STATE.parent.mkdir(parents=True, exist_ok=True)
        _NEG_LEDGER_STATE.write_text(
            json.dumps({"sig": sig or ""}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        logger.warning("neg ledger state not saved", exc_info=True)


def _notified_set(bot_data: dict) -> set[str]:
    raw = bot_data.get("stale_payout_notified")
    if raw is None:
        raw = set()
        bot_data["stale_payout_notified"] = raw
    return raw


async def _already_notified(bot_data: dict, order_id: str) -> bool:
    if order_id in _notified_set(bot_data):
        return True
    return await is_stale_alert_sent(order_id)


async def stale_payout_monitor_task(
    bot,
    *,
    shutdown_event: asyncio.Event | None = None,
    bot_data: dict | None = None,
) -> None:
    if not config_rates.owner_dashboard_enabled():
        logger.info("owner group not configured — stale payout monitor disabled")
        return

    interval = max(15, int(config_rates.OWNER_MONITOR_INTERVAL_SEC))
    minutes = max(1, int(config_rates.OWNER_STALE_PAYOUT_MINUTES))
    chat_id = config_rates.reports_group_id()
    data = bot_data if bot_data is not None else {}

    while True:
        if shutdown_event and shutdown_event.is_set():
            break
        try:
            stale = await get_stale_completed_buy_orders(minutes)
            notified = _notified_set(data)
            for row in stale:
                oid = str(row["order_id"])
                if await _already_notified(data, oid):
                    continue
                text, raw_kb = format_stale_payout_alert(dict(row))
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(btn["text"], url=btn["url"])
                            for btn in kb_row
                        ]
                        for kb_row in raw_kb["inline_keyboard"]
                    ]
                )
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                notified.add(oid)
                await mark_stale_alert_sent(oid)
        except Exception as e:
            logger.exception("stale_payout_monitor error: %s", e)

        # Алерт об отрицательных балансах леджера (over-spend / over-hold).
        try:
            negatives = await get_negative_ledger_accounts()
            if negatives:
                sig = ";".join(
                    sorted(f"{n['kind']}:{n['ref']}:{round(n['bal'], 2)}" for n in negatives)
                )
                if data.get("neg_ledger_sig") is None:
                    data["neg_ledger_sig"] = _load_neg_sig()
                if data.get("neg_ledger_sig") != sig:
                    data["neg_ledger_sig"] = sig
                    _save_neg_sig(sig)
                    lines = "\n".join(
                        f"• {n['kind']} {n['ref']}: <code>{n['bal']:.2f}</code> ₽"
                        for n in negatives[:20]
                    )
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "🚨 <b>Отрицательный баланс леджера</b>\n"
                            "Возможен over-spend/over-hold — проверьте:\n\n"
                            f"{lines}"
                        ),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
            elif data.get("neg_ledger_sig"):
                data["neg_ledger_sig"] = None
                _save_neg_sig(None)
        except Exception as e:
            logger.exception("negative ledger check error: %s", e)

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def clear_stale_payout_notification(bot_data: dict, order_id: str) -> None:
    """Снять дедуп при PAID/CANCELED."""
    oid = str(order_id)
    notified = bot_data.get("stale_payout_notified")
    if isinstance(notified, set):
        notified.discard(oid)
    from services.db import clear_stale_alert_sent

    await clear_stale_alert_sent(oid)

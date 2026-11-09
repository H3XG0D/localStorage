"""Ops-уведомления по сделкам кабинета внештатника (бот / appeals)."""
from __future__ import annotations

from services.https_fetch import https_urlopen
from services.payment_snapshot import order_payment_snapshot

import html
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("external_deal_ops_notify")

_EVENTS: dict[str, tuple[str, str]] = {
    "video_requested": (
        "🎥",
        "Appeals: PDF не принят · нужно видео · внештатнику показано «напишите оператору»",
    ),
    "success_receipt": ("📎", "Appeals: нужен чек в успешном статусе · ждём PDF"),
}


def _deal_client_label(deal: dict[str, Any]) -> str:
    if deal.get("client_is_new") is not None:
        return "новый" if bool(deal["client_is_new"]) else "повторный"
    label = str(deal.get("deal_client_label") or "").strip().lower()
    if label == "повторный":
        return "повторный"
    return "новый"


def _format_last_confirmed(last_at) -> str:
    if not last_at:
        return "—"
    if isinstance(last_at, str):
        try:
            last_at = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
        except ValueError:
            return "—"
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    delta = now - last_at.astimezone(timezone.utc)
    days = delta.days
    if days <= 0:
        hours = delta.seconds // 3600
        if hours <= 0:
            return "только что"
        return f"{hours} ч. назад"
    if days == 1:
        return "вчера"
    if days < 7:
        return f"{days} дн. назад"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} нед. назад"
    months = days // 30
    return f"{months} мес. назад"


def _format_exchanger_ops_stats_block(stats: dict[str, Any] | None) -> str:
    if not stats:
        return ""
    confirmed = int(stats.get("confirmed_count") or 0)
    turnover = float(stats.get("total_turnover_rub") or 0)
    turnover_str = f"{turnover:,.0f} ₽".replace(",", " ")
    last_str = _format_last_confirmed(stats.get("last_confirmed_at"))
    return (
        "\n👥 <b>Внештатник</b>\n"
        f"🔄 Сделок: <b>{confirmed}</b> · {last_str}\n"
        f"📈 Оборот: <b>{turnover_str}</b>"
    )


def _payfast_id(deal: dict[str, Any]) -> str:
    snap = order_payment_snapshot(deal)
    if snap.get("merchant_uuid"):
        return str(snap["merchant_uuid"])
    mid = str(deal.get("merchant_order_id") or "").strip()
    if mid:
        return mid
    return f"EXT-{deal.get('id', '')}"


def format_external_deal_ops_notify(
    event: str,
    deal: dict[str, Any],
    *,
    note: str | None = None,
    ops_stats: dict[str, Any] | None = None,
) -> str:
    from services.order_ops_notify import OPS_MSG_SEPARATOR

    emoji, default_suffix = _EVENTS.get(event, ("📋", event))
    deal_id = int(deal["id"])
    name = html.escape(str(deal.get("exchanger_name") or ""))
    amount = float(deal.get("client_pays_rub") or 0)
    amount_str = f"{amount:,.0f} ₽".replace(",", " ")
    lines = [
        f"<b>{emoji} Кабинет · сделка #{deal_id}</b>",
        OPS_MSG_SEPARATOR,
        "",
        f"🆔 <code>EXT-{deal_id}</code>",
        f"👤 <b>{name}</b> · {amount_str}",
    ]
    username = str(deal.get("account_username") or "").strip().lstrip("@")
    if username:
        lines.append(
            f'👤 <a href="https://t.me/{html.escape(username)}">'
            f"@{html.escape(username)}</a>"
        )
    lines.append(f"🏷 Клиент: {html.escape(_deal_client_label(deal))}")
    stats_block = _format_exchanger_ops_stats_block(ops_stats)
    if stats_block:
        lines.append(stats_block)
    lines.append("")
    lines.append(note or default_suffix)
    return "\n".join(lines)


async def notify_external_deal_ops(
    event: str,
    deal: dict[str, Any],
    *,
    bot=None,
    note: str | None = None,
) -> None:
    from services import config_rates as cfg

    chat_id = cfg.external_deals_group_id() or cfg.ops_group_id()
    if not chat_id:
        logger.warning(
            "external deal ops skipped (no external/ops group): event=%s deal=%s",
            event,
            deal.get("id"),
        )
        return
    if not cfg.external_deals_group_id():
        logger.info(
            "external deal ops using ops fallback: event=%s deal=%s",
            event,
            deal.get("id"),
        )

    ops_stats = None
    eid = deal.get("exchanger_id")
    if eid:
        try:
            from services.db import get_external_exchanger_ops_stats

            ops_stats = await get_external_exchanger_ops_stats(int(eid))
        except Exception as exc:
            logger.warning("external exchanger stats fetch failed: %s", exc)

    text = format_external_deal_ops_notify(event, deal, note=note, ops_stats=ops_stats)
    if bot is not None:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return
        except Exception as exc:
            logger.warning("external deal ops bot send failed: %s", exc)

    token = cfg.TELEGRAM_BOT_TOKEN
    if not token:
        return
    import json as json_mod
    import urllib.request

    payload = json_mod.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with https_urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as exc:
        logger.warning("external deal ops http send failed: %s", exc)

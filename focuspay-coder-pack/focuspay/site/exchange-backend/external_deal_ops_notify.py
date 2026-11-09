"""Ops-уведомления по сделкам кабинета внештатника."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from external_deal_timing import EXTERNAL_DEAL_CLIENT_PAY_TEXT
from external_exchange_trust import deal_client_label

_CABINET_EVENTS: dict[str, tuple[str, str]] = {
    "created": ("🤝", f"ожидает оплату · {EXTERNAL_DEAL_CLIENT_PAY_TEXT}"),
    "confirm_paid": ("📎", "клиент оплатил · ждём чек"),
    "receipt": ("🧾", "чек отправлен мерчанту · ждём Payfast"),
    "video_requested": (
        "🎥",
        "Appeals: PDF не принят · нужно видео · внештатнику показано «напишите оператору»",
    ),
    "success_receipt": ("📎", "Appeals: нужен чек в успешном статусе · ждём PDF"),
    "cancelled": ("❌", "сделка отменена"),
    "auto_confirmed": ("✅", "Payfast подтвердил · баланс начислен автоматически"),
}


def _deal_id(deal: dict[str, Any]) -> int:
    if deal.get("id") is not None:
        return int(deal["id"])
    nested = deal.get("deal")
    if isinstance(nested, dict) and nested.get("id") is not None:
        return int(nested["id"])
    raise ValueError("deal id missing")


def _client_pays_rub(deal: dict[str, Any]) -> float:
    if deal.get("client_pays_rub") is not None:
        return float(deal["client_pays_rub"])
    nested = deal.get("deal")
    if isinstance(nested, dict) and nested.get("client_pays_rub") is not None:
        return float(nested["client_pays_rub"])
    return 0.0


def _deal_client_is_new(deal: dict[str, Any]) -> bool:
    if deal.get("client_is_new") is not None:
        return bool(deal["client_is_new"])
    if deal.get("deal_client_label"):
        return str(deal["deal_client_label"]).strip().lower() == "новый"
    return True


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


def format_exchanger_ops_stats_block(stats: dict[str, Any] | None) -> str:
    if not stats:
        return ""
    confirmed = int(stats.get("confirmed_count") or 0)
    failed = int(stats.get("failed_count") or 0)
    conv = stats.get("conversion_pct")
    conv_str = f"{conv:g}%" if conv is not None else "—"
    turnover = float(stats.get("total_turnover_rub") or 0)
    turnover_str = f"{turnover:,.0f} ₽".replace(",", " ")
    last_str = _format_last_confirmed(stats.get("last_confirmed_at"))
    return (
        "\n──────────────────\n"
        "👤 <b>Внештатник</b>\n"
        f"• Подтверждено сделок: <b>{confirmed}</b>\n"
        f"• Неуспех: <b>{failed}</b>\n"
        f"• Конверсия: <b>{conv_str}</b>\n"
        f"• Последняя: {last_str}\n"
        f"• Оборот: <b>{turnover_str}</b>"
    )


def format_deal_ops_notify(
    event: str,
    deal: dict[str, Any],
    exchanger: dict[str, Any],
    *,
    note: str | None = None,
    ops_stats: dict[str, Any] | None = None,
) -> str:
    """HTML-сообщение для ops Telegram-группы."""
    emoji, default_suffix = _CABINET_EVENTS.get(event, ("📋", event))
    deal_id = _deal_id(deal)
    name = html.escape(
        str(
            exchanger.get("exchanger_name")
            or exchanger.get("name")
            or ""
        )
    )
    amount = _client_pays_rub(deal)
    amount_str = f"{amount:,.0f} ₽".replace(",", " ")

    lines = [
        f"{emoji} Кабинет · сделка #{deal_id} · <b>{name}</b> · {amount_str}",
        f"🆔 <code>{html.escape(f'EXT-{deal_id}')}</code>",
    ]

    username = str(exchanger.get("username") or exchanger.get("account_username") or "").strip()
    if username:
        lines.append(f"👤 @{html.escape(username.lstrip('@'))}")

    client_label = deal_client_label(_deal_client_is_new(deal))
    lines.append(f"🏷 Клиент: {html.escape(client_label)}")

    payout_on_credit = deal.get("payout_on_credit")
    nested = deal.get("deal") if isinstance(deal.get("deal"), dict) else {}
    if payout_on_credit is None and nested:
        payout_on_credit = nested.get("payout_on_credit")
    if payout_on_credit:
        wallet = str(deal.get("payout_wallet") or nested.get("payout_wallet") or "").strip()
        crypto = str(deal.get("crypto") or nested.get("crypto") or "usdt").upper()
        lines.append(
            "💸 После зачисления: выплата "
            f"{html.escape(crypto)}"
            + (f" на <code>{html.escape(wallet)}</code>" if wallet else "")
        )

    stats_block = format_exchanger_ops_stats_block(ops_stats)
    if stats_block:
        lines.append(stats_block)

    if note:
        lines.append(html.escape(note))
    else:
        lines.append(default_suffix)

    return "\n".join(lines)

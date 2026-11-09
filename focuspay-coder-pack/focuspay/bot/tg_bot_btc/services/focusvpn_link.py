"""Переход в отдельный бот FocusVPN: кнопка меню и короткое описание."""
from __future__ import annotations

import json
import logging

from services.config_rates import vpn_bot_url

logger = logging.getLogger(__name__)

FOCUSVPN_BUTTON = "🛡 Открыть FocusVPN"
DEFAULT_PURCHASE_MIN_EXCHANGES = 10


def progress_bar(have: int, need: int, width: int = 10) -> str:
    if need <= 0:
        return "▰" * width
    filled = min(width, have * width // need)
    return "▰" * filled + "▱" * (width - filled)


def focusvpn_text(
    have: int, need: int, invited_have: int = 0, invited_need: int = 30, *, trusted: bool = False
) -> str:
    head = (
        "🛡 <b>FocusVPN</b> — VPN от FocusPay\n\n"
        "• Пробный период — бесплатно, для всех\n"
        "• Оплата с баланса FocusPay: неделя, месяц, 3 месяца\n"
        "• Управление подпиской и устройствами — в боте FocusVPN\n\n"
    )
    exchanges_open = need <= 0 or have >= need
    invited_open = invited_need > 0 and invited_have >= invited_need
    if trusted or exchanges_open or invited_open:
        return head + "✅ Тарифы для вас уже открыты."
    left = need - have
    return (
        head
        + "<b>Купить можно так:</b> либо "
        + f"{need} обменов, либо {invited_need} приглашённых.\n"
        + f"Обмены: {progress_bar(have, need)} {have} из {need} · осталось {left}\n"
        + f"Приглашённые: {progress_bar(invited_have, invited_need)} {invited_have} из {invited_need}"
    )


def focusvpn_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup([[InlineKeyboardButton(FOCUSVPN_BUTTON, url=vpn_bot_url())]])


def trusted_from_setting(raw, user_id: int) -> bool:
    if not raw:
        return False
    try:
        ids = json.loads(raw) if isinstance(raw, str) else list(raw)
        return int(user_id) in {int(x) for x in ids}
    except (TypeError, ValueError):
        logger.warning("vpn_trusted_ids unreadable; gate stays on")
        return False


async def exchange_progress(user_id: int) -> tuple[int, int, int, int, bool]:
    """Exchanges and invited people, with the two thresholds from vpn_billing settings."""
    from services.cashback_tier import count_completed_exchanges
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        have = await count_completed_exchanges(conn, user_id)
        invited = int(
            await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM user_referral_attributions
                WHERE referrer_user_id = $1
                """,
                int(user_id),
            )
            or 0
        )
        raw = await conn.fetchval("SELECT value FROM app_settings WHERE key = 'vpn_billing'")
        raw_trusted = await conn.fetchval("SELECT value FROM app_settings WHERE key = 'vpn_trusted_ids'")
    need = DEFAULT_PURCHASE_MIN_EXCHANGES
    invited_need = 30
    trusted = trusted_from_setting(raw_trusted, user_id)
    if raw:
        try:
            cfg = json.loads(raw) if isinstance(raw, str) else dict(raw)
            need = int(cfg.get("purchase_min_exchanges", cfg.get("purchase_min_deposits", need)))
            if "purchase_min_invited" in cfg:
                invited_need = int(cfg.get("purchase_min_invited") or 0)
        except (TypeError, ValueError):
            logger.warning("vpn_billing settings unreadable; using default gate")
    return have, need, invited, invited_need, trusted

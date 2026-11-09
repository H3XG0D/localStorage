"""FocusLucky admin commands in reports group."""

from __future__ import annotations

import logging

import html

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.financial_guards import is_reports_group_chat
from services.raffle_db import (
    activate_campaign,
    close_campaign,
    get_active_campaign,
    get_campaign_by_id,
    get_campaign_stats,
    pay_balance_winners,
    start_show,
)
from services.raffle_constants import (
    format_place_label,
    format_prize_rub,
)

logger = logging.getLogger("raffle_admin")


def _admin_ok(update: Update) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    if not is_reports_group_chat(update.effective_chat.id):
        return False
    return update.effective_user.id in TELEGRAM_ADMIN_IDS


async def raffle_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    args = context.args or []
    campaign = None
    if args and args[0].isdigit():
        campaign = await get_campaign_by_id(int(args[0]))
    else:
        campaign = await get_active_campaign()
        if not campaign:
            from services.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM raffle_campaigns ORDER BY id DESC LIMIT 1"
                )
                campaign = dict(row) if row else None

    if not campaign:
        await update.message.reply_text("Нет кампаний FocusLucky.")
        return

    stats = await get_campaign_stats(campaign["id"])
    c = stats["campaign"]
    lines = [
        f"🍀 <b>FocusLucky</b> #{c['id']} · {html.escape(str(c.get('slug') or ''))}",
        f"Status: <b>{c['status']}</b>",
        f"Участников: <b>{stats['participants']}</b>",
        f"Билетов в пуле: <b>{stats['pool_total']}</b>",
        f"next_ticket_no: <b>{stats['next_ticket_no']}</b>",
        f"Выдано / void: {c.get('total_tickets_issued')} / {c.get('total_tickets_void')}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def raffle_close_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    campaign = await get_active_campaign()
    if not campaign:
        await update.message.reply_text("Нет активной кампании.")
        return
    ok = await close_campaign(campaign["id"])
    if ok:
        await update.message.reply_text(
            f"✅ Кампания #{campaign['id']} закрыта для начисления билетов."
        )
    else:
        await update.message.reply_text("Не удалось закрыть кампанию.")


async def raffle_draw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    args = context.args or []
    campaign_id = None
    if args and args[0].isdigit():
        campaign_id = int(args[0])
    else:
        camp = await get_active_campaign()
        if not camp:
            from services.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id FROM raffle_campaigns
                    WHERE status = 'closed'
                    ORDER BY ends_at DESC LIMIT 1
                    """
                )
                if row:
                    campaign_id = int(row["id"])
        else:
            campaign_id = camp["id"]

    if not campaign_id:
        await update.message.reply_text("Укажите id: /raffle_draw 1")
        return

    if campaign_id:
        camp = await get_campaign_by_id(campaign_id)
        if camp and camp["status"] == "active":
            await close_campaign(campaign_id)

    try:
        result = await start_show(campaign_id)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception:
        await update.message.reply_text("❌ Ошибка запуска шоу")
        return

    await update.message.reply_text(
        f"🎬 <b>FocusLucky шоу запущено</b> #{campaign_id}\n"
        "Места крутятся сами с 1-го. Смотреть: /casino/play/raffle",
        parse_mode="HTML",
    )
    _ = result


async def raffle_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text("Использование: /raffle_pay <campaign_id>")
        return
    campaign_id = int(args[0])
    try:
        paid = await pay_balance_winners(campaign_id)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
        return
    if not paid:
        await update.message.reply_text("Нет pending balance-призов для выплаты.")
        return
    lines = [f"✅ Начислено на баланс: {len(paid)} победителей"]
    for w in paid:
        lines.append(
            f"  {format_place_label(int(w['place']))} · user {w['user_id']} · "
            f"{format_prize_rub(w['prize_rub'])}"
        )
    await update.message.reply_text("\n".join(lines))


async def raffle_activate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text("Использование: /raffle_activate <campaign_id>")
        return
    ok = await activate_campaign(int(args[0]))
    if ok:
        await update.message.reply_text(f"✅ Кампания #{args[0]} активирована.")
    else:
        await update.message.reply_text("Не удалось активировать (status draft/closed?).")

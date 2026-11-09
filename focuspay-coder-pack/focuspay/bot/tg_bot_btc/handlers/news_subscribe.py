"""Команды подписки на новости и адресной рассылки (admin-only send)."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.news_privacy import pseudo_user, security_log
from services.news_subscriptions import (
    ALLOWED_CATEGORIES,
    get_subscription,
    opt_in,
    opt_out,
)

logger = logging.getLogger("news_subscribe_handlers")


def _is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in set(int(x) for x in TELEGRAM_ADMIN_IDS)


async def news_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ /news_on [category...] — opt-in """
    if not update.effective_user or not update.message:
        return
    cats = [a.lower() for a in (context.args or []) if a]
    bad = [c for c in cats if c not in ALLOWED_CATEGORIES]
    if bad:
        await update.message.reply_text(
            "Неизвестные категории: "
            + ", ".join(bad)
            + f"\nДоступно: {', '.join(sorted(ALLOWED_CATEGORIES))}"
        )
        return
    row = await opt_in(
        int(update.effective_user.id),
        categories=cats or ["general"],
        source="bot_command",
    )
    await update.message.reply_text(
        "✅ Подписка на новости включена.\n"
        f"Категории: {', '.join(row.get('categories') or ['general'])}\n"
        "Отписка: /news_off"
    )


async def news_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    await opt_out(int(update.effective_user.id), source="bot_command")
    await update.message.reply_text("Подписка на новости отключена (/news_on — снова).")


async def news_prefs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    row = await get_subscription(int(update.effective_user.id))
    if not row:
        await update.message.reply_text("Вы не подписаны. /news_on")
        return
    await update.message.reply_text(
        f"opted_in={row.get('opted_in')}\n"
        f"categories={row.get('categories')}\n"
        f"consent={row.get('consent_version')} @ {row.get('consented_at')}\n"
        f"source={row.get('consent_source')}"
    )


async def news_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: /news_send category|idempotency_key|HTML text

    Пример:
      /news_send general|promo-2026-08-12|<b>Курс обновили</b>
    """
    if not update.effective_user or not update.message:
        return
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Только админ.")
        return

    raw = (update.message.text or "").split(maxsplit=1)
    if len(raw) < 2 or "|" not in raw[1]:
        await update.message.reply_text(
            "Формат:\n"
            "<code>/news_send category|idempotency_key|HTML</code>\n"
            f"Категории: {', '.join(sorted(ALLOWED_CATEGORIES))}",
            parse_mode="HTML",
        )
        return

    parts = raw[1].split("|", 2)
    if len(parts) < 3:
        await update.message.reply_text("Нужны 3 поля через | : category|key|html")
        return
    category, idem, body = parts[0].strip(), parts[1].strip(), parts[2].strip()

    from services import news_broadcast as nb

    try:
        job = await nb.create_job(
            actor_id=int(update.effective_user.id),
            body_html=body,
            category=category,
            title=body.split("\n", 1)[0][:120],
            idempotency_key=idem or None,
        )
    except PermissionError as e:
        await update.message.reply_text(f"⛔ {e}")
        return
    except ValueError as e:
        await update.message.reply_text(f"Ошибка: {e}")
        return

    await update.message.reply_text(
        f"Очередь job#{job['id']} status={job['status']}. Запускаю…"
    )
    try:
        result = await nb.run_job(context.bot, int(job["id"]))
    except PermissionError as e:
        await update.message.reply_text(f"⛔ {e}")
        return
    except Exception as e:
        logger.exception("news_send failed")
        await update.message.reply_text(f"Сбой: {type(e).__name__}")
        return

    security_log.info(
        "news_send_done job=%s actor=%s sent=%s",
        job["id"],
        pseudo_user(update.effective_user.id),
        result.get("sent"),
    )
    await update.message.reply_text(
        f"✅ Готово job#{job['id']}\n"
        f"sent={result.get('sent')} failed={result.get('failed')} "
        f"skipped={result.get('skipped')} total={result.get('total')}"
    )

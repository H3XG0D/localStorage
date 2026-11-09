"""Команда /ops_bind и deep-link ?start=opsbind_TOKEN — привязка оператора."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from handlers.telegram_errors import answer_callback_safe
from services.antispam import rate_limit_ok
from services.menu import main_menu_keyboard
from services.ops_bind import (
    OPS_BIND_PAYLOAD_KEY,
    bind_operator_telegram_by_token,
    extract_ops_bind_token,
    ops_profile_url,
)

logger = logging.getLogger(__name__)

OPS_BIND_CB = "ops:profile"


def _profile_keyboard() -> InlineKeyboardMarkup:
    url = ops_profile_url()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Открыть /ops/profile", url=url)]]
    )


def _usage_text() -> str:
    url = ops_profile_url()
    return (
        "Использование: <code>/ops_bind КОД</code>\n\n"
        "Код выдаётся в профиле оператора "
        f'(<a href="{url}">/ops/profile</a>), действует 2 часа.\n'
        "Нужна активная сессия панели. Если ссылка истекла — получите новую там же."
    )


async def _reply_bind_message(update: Update, text: str, *, with_menu: bool = True) -> None:
    user = update.effective_user
    markup = _profile_keyboard()
    menu = None
    if with_menu and user:
        menu = await main_menu_keyboard(user.id, user.username)
    target = update.effective_message
    if not target:
        return
    await target.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    if menu:
        await target.reply_text("Меню бота:", reply_markup=menu)


async def complete_ops_bind(
    update: Update, token: str, *, allow_bare: bool = False
) -> bool:
    """True — payload был ops-bind (успех или отказ с сообщением)."""
    code = extract_ops_bind_token(token, allow_bare=allow_bare)
    if not code:
        return False
    user = update.effective_user
    if not user:
        return True
    url = ops_profile_url()
    try:
        row = await bind_operator_telegram_by_token(code, user.id)
    except Exception:
        logger.exception("ops_bind failed telegram_user_id=%s", user.id)
        await _reply_bind_message(
            update,
            "Не удалось привязать Telegram из‑за ошибки сервера. "
            f'Откройте <a href="{url}">/ops/profile</a> и попробуйте новую ссылку.',
        )
        return True
    if not row:
        await _reply_bind_message(
            update,
            "Не удалось привязать Telegram.\n\n"
            "Код неверный, уже использован или истекла сессия/ссылка (2 часа). "
            f'Войдите в панель и откройте <a href="{url}">/ops/profile</a>, '
            "чтобы получить новую ссылку.",
        )
        return True
    name = row.get("display_name") or row.get("username") or "оператор"
    uname = row.get("username") or "—"
    await _reply_bind_message(
        update,
        f"✅ Telegram привязан к оператору <b>{name}</b> (<code>{uname}</code>).\n\n"
        f'Профиль панели: <a href="{url}">/ops/profile</a>\n'
        "Дайджест Ops AI включается там же. Без входа в панель страница попросит авторизацию.",
    )
    return True


async def maybe_handle_ops_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    payload = ""
    args = context.args or []
    if args:
        payload = args[0]
    if not payload:
        payload = str(context.user_data.pop(OPS_BIND_PAYLOAD_KEY, "") or "")
    if not payload and update.message and update.message.text:
        payload = update.message.text
    if not extract_ops_bind_token(payload):
        return False
    return await complete_ops_bind(update, payload)


async def ops_bind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            _usage_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=_profile_keyboard(),
            disable_web_page_preview=True,
        )
        return
    handled = await complete_ops_bind(update, " ".join(args), allow_bare=True)
    if not handled:
        await update.message.reply_text(
            _usage_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=_profile_keyboard(),
            disable_web_page_preview=True,
        )


async def ops_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data=ops:profile — явное открытие /ops/profile (не молчаливый отказ)."""
    query = update.callback_query
    if not query:
        return
    if not await rate_limit_ok(update):
        await answer_callback_safe(query)
        return
    url = ops_profile_url()
    await answer_callback_safe(query)
    if query.message:
        await query.message.reply_text(
            f'Профиль оператора: <a href="{url}">/ops/profile</a>\n'
            "Нужна сессия панели. Если вход истёк — авторизуйтесь заново.",
            parse_mode=ParseMode.HTML,
            reply_markup=_profile_keyboard(),
            disable_web_page_preview=True,
        )

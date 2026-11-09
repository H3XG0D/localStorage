"""Player seed-pair commands: show hash, set client seed, rotate (reveals previous seed)."""
from __future__ import annotations

from telebot import types
from telebot.async_telebot import AsyncTeleBot

from focuspay_client import FocusPayClient
from games.card_fairness import fairness_href, verify_url
from games.chat_reaper import try_delete_user_message


def _session_text(session: dict) -> str:
    commit = session.get("commit_hash")
    client_seed = session.get("client_seed")
    nonce = session.get("nonce")
    previous = session.get("previous_server_seed")
    lines = [
        "<b>Честность карт</b>",
        "Ротация раскрывает предыдущий серверный сид. Nonce растёт с каждой новой карточной игрой.",
    ]
    if isinstance(commit, str) and commit:
        lines.append(f"Хеш пары: <code>{commit}</code>")
    if isinstance(client_seed, str) and client_seed:
        lines.append(f"Клиентский сид: <code>{client_seed}</code>")
    if isinstance(nonce, int) or (isinstance(nonce, str) and str(nonce).lstrip("-").isdigit()):
        lines.append(f"Nonce следующей игры: <code>{int(nonce)}</code>")
    if isinstance(previous, str) and previous:
        lines.append(f"Предыдущий сид: <code>{previous}</code>")
    url = verify_url(
        game_type="baccara",
        game_id="",
        commit=commit if isinstance(commit, str) else None,
        client_seed=client_seed if isinstance(client_seed, str) else None,
        nonce=nonce,
    )
    if url:
        lines.append(f'<a href="{fairness_href(url)}">Страница проверки</a>')
    else:
        lines.append("Страница проверки: /casino/fairness")
    lines.append("\n/fairness rotate — новая пара сидов")
    lines.append("/fairness seed имя — свой клиентский сид")
    return "\n".join(lines)


def register_fairness_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    @bot.message_handler(commands=["fairness"])
    async def cmd_fairness(message):
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if not isinstance(user_id, int):
            return
        parts = (message.text or "").split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else ""
        try:
            if action == "rotate":
                session = await client.rotate_fairness_seeds(telegram_id=user_id)
            elif action == "seed":
                seed = parts[2].strip() if len(parts) > 2 else ""
                if not seed:
                    await bot.send_message(message.chat.id, "Укажите сид: /fairness seed мой_сид")
                    return
                session = await client.set_fairness_client_seed(telegram_id=user_id, client_seed=seed)
            else:
                session = await client.fairness_session(telegram_id=user_id)
        except Exception:
            await bot.send_message(message.chat.id, "❌ Не удалось загрузить пару сидов. Попробуйте позже.")
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Ротировать сиды", callback_data="fairness_rotate"))
        await bot.send_message(message.chat.id, _session_text(session), parse_mode="HTML", reply_markup=kb)
        await try_delete_user_message(bot, message)

    @bot.callback_query_handler(func=lambda call: call.data == "fairness_rotate")
    async def cb_rotate(call):
        user_id = getattr(getattr(call, "from_user", None), "id", None)
        if not isinstance(user_id, int):
            return
        try:
            session = await client.rotate_fairness_seeds(telegram_id=user_id)
        except Exception:
            await bot.answer_callback_query(call.id, "Ротация недоступна.", show_alert=True)
            return
        try:
            await bot.edit_message_text(
                _session_text(session),
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
                reply_markup=call.message.reply_markup,
            )
        except Exception:
            await bot.send_message(call.message.chat.id, _session_text(session), parse_mode="HTML")
        await bot.answer_callback_query(call.id, "Предыдущий сид раскрыт")

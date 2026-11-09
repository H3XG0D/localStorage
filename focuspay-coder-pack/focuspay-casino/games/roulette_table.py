"""European roulette on the shared live table from Telegram."""
from __future__ import annotations

import contextlib
import logging
from typing import Any

import httpx
from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import casino_game_policy, validate_game_stake
from focuspay_client import FocusPayClient
from games.chat_guard import ActiveGameChatGuard
from games.chat_reaper import TTL_SERVICE, reply_ephemeral, try_delete_user_message
from games.roulette_card import upsert as upsert_roulette_card
from games.roulette_cmd import (
    USAGE_MESSAGE,
    ParsedRouletteCommand,
    RouletteCommandError,
    cell_odds,
    cell_title,
    parse_roulette_command,
)
from games.board_style import seconds_until, timer_line as style_timer_line
from games.site_links import add_open_url_button, append_watch_line, https_only, roulette_play_url

logger = logging.getLogger(__name__)

CHEATSHEET = (
    "🎡 <b>Рулетка 0–36</b> — общий стол\n\n"
    f"{USAGE_MESSAGE}"
)
STAKE_ACCEPTED_TITLE = "🎡 <b>Ставка принята</b>"


def _api_detail(exc: Exception, fallback: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        with contextlib.suppress(Exception):
            detail = exc.response.json().get("detail")
            if detail:
                return str(detail)
    return fallback


def roulette_table_url() -> str | None:
    return roulette_play_url()


def https_table_url() -> str | None:
    """Telegram Web App buttons reject http:// — only attach HTTPS."""
    return https_only(roulette_table_url())


def _table_keyboard() -> types.InlineKeyboardMarkup | None:
    """URL button only. web_app inline buttons are private-chat-only; the live
    card is posted in the game group, where Telegram returns BUTTON_TYPE_INVALID
    and every edit (timer, second player) is dropped.
    """
    keyboard = types.InlineKeyboardMarkup()
    add_open_url_button(keyboard, roulette_table_url(), "Открыть стол")
    if not getattr(keyboard, "keyboard", None):
        return None
    return keyboard


def seconds_until_spin(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot:
        return None
    return seconds_until(snapshot.get("closes_at"))


def timer_line(snapshot: dict[str, Any] | None) -> str:
    return style_timer_line(
        snapshot,
        spinning_statuses=("locked", "spinning", "settled"),
        spinning_text="Колесо крутится, ставки закрыты.",
        collect_default=25,
    )


def confirm_text(parsed: ParsedRouletteCommand, snapshot: dict[str, Any] | None) -> str:
    lines = [STAKE_ACCEPTED_TITLE]
    for key in parsed.cells:
        lines.append(
            f"• {cell_title(key)} — {parsed.amount_rub} ₽, {cell_odds(key)}"
        )
    lines.append(f"На каждую: {parsed.amount_rub} ₽")
    if parsed.chip_count > 1:
        lines.append(f"Фишек: {parsed.chip_count}")
    lines.append(f"Списание: {parsed.debit_rub} ₽")
    extra = timer_line(snapshot)
    if extra:
        lines.append(extra)
    return append_watch_line("\n".join(lines), roulette_table_url())


async def reply_html(bot: Any, message: Any, text: str) -> None:
    """Send HTML. Staging miniapp is http:// — Web App markup must not kill the text."""
    markup = _table_keyboard()
    try:
        await reply_ephemeral(
            bot, message, text, TTL_SERVICE, parse_mode="HTML", reply_markup=markup
        )
        return
    except Exception as exc:
        logger.warning("roulette Telegram reply with keyboard failed: %s", exc)
    await reply_ephemeral(bot, message, text, TTL_SERVICE, parse_mode="HTML")


async def _snapshot(client: FocusPayClient, telegram_id: int) -> dict[str, Any]:
    try:
        return await client.get_roulette_table(telegram_id=telegram_id)
    except Exception:
        logger.exception("roulette table snapshot failed telegram_id=%s", telegram_id)
        return {}


async def handle_roulette_command(
    bot: Any, client: FocusPayClient, message: Any, *, guard: ActiveGameChatGuard
) -> None:
    if not await guard.require_message(bot, message):
        return
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    user_id = getattr(user, "id", None)
    chat_id = getattr(chat, "id", None)
    if not isinstance(user_id, int) or not isinstance(chat_id, int) or chat_id == 0:
        return
    raw = str(getattr(message, "text", "") or "")
    try:
        parsed = parse_roulette_command(raw)
    except RouletteCommandError as exc:
        await reply_html(bot, message, str(exc))
        await try_delete_user_message(bot, message)
        return
    snapshot = await _snapshot(client, user_id)
    if parsed is None:
        text = f"{CHEATSHEET}\n\n{timer_line(snapshot)}".rstrip()
        text = append_watch_line(text, roulette_table_url())
        await reply_html(bot, message, text)
        await try_delete_user_message(bot, message)
        return
    try:
        policy = casino_game_policy(await client.get_casino_settings(), game_key="roulette")
        validate_game_stake(policy=policy, stake_rub=parsed.amount_rub)
    except ValueError as exc:
        labels = {
            "game_disabled": "❌ Рулетка временно отключена.",
            "stake_below_minimum": "❌ Ставка меньше разрешённого минимума.",
            "stake_above_maximum": "❌ Ставка превышает разрешённый максимум.",
        }
        await reply_html(bot, message, labels.get(str(exc), "❌ Неверная сумма ставки."))
        await try_delete_user_message(bot, message)
        return
    chips = [{"bet": key, "amount_rub": format(parsed.amount_rub, "f")} for key in parsed.cells]
    try:
        placed = await client.place_roulette_table_bet(
            telegram_id=user_id,
            notify_chat_id=chat_id,
            chips=chips,
        )
    except Exception as exc:
        await reply_html(
            bot, message, f"❌ {_api_detail(exc, 'Не удалось поставить. Попробуйте позже.')}"
        )
        await try_delete_user_message(bot, message)
        return
    snap = placed if isinstance(placed, dict) else snapshot
    try:
        await upsert_roulette_card(bot, client, chat_id, snap, telegram_id=user_id)
    except Exception:
        logger.exception("roulette confirm reply failed after bet telegram_id=%s", user_id)
        with contextlib.suppress(Exception):
            await reply_html(bot, message, confirm_text(parsed, snap))
    await try_delete_user_message(bot, message)


def register_roulette_table_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    guard = ActiveGameChatGuard(client)

    @bot.message_handler(commands=["roulette", "рулетка"])
    async def cmd_roulette(message):
        try:
            await handle_roulette_command(bot, client, message, guard=guard)
        except Exception:
            logger.exception("roulette command failed")
            with contextlib.suppress(Exception):
                await bot.reply_to(message, "❌ Не удалось поставить. Попробуйте позже.")

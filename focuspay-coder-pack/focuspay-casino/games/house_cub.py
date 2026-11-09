"""House cub in a private chat: the player throws a live Telegram die, then the casino does."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal
from typing import Any

import httpx
from telebot.async_telebot import AsyncTeleBot

from games.dice_timing import wait_dice_landed
from finance import casino_game_policy, validate_game_stake
from focuspay_client import FocusPayClient

logger = logging.getLogger(__name__)

DICE_EMOJI = "🎲"
THROW_PROMPT = (
    "Кинь 🎲 сюда. Казино кинет свой. Больше число выигрывает. Ничья — снова."
)
TIE_PROMPT = "Ничья — кидай ещё раз."
BUSY_PROMPT = "⏳ Казино ещё кидает. Подожди свой куб, потом кидай снова."
WRONG_EMOJI_PROMPT = "❌ Для игры против казино нужен бросок 🎲."

_house_cub_locks: dict[int, asyncio.Lock] = {}
_house_cub_busy: set[int] = set()


def _house_cub_lock(telegram_id: int) -> asyncio.Lock:
    return _house_cub_locks.setdefault(telegram_id, asyncio.Lock())


def _api_detail(exc: Exception, fallback: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        with contextlib.suppress(Exception):
            detail = exc.response.json().get("detail")
            if detail:
                return str(detail)
    return fallback


def _format_money(value: object) -> str:
    return f"{Decimal(str(value or '0')):.2f}"


def _result_text(result: dict[str, Any], *, available_rub: object | None = None) -> str:
    player_value = result.get("player_value")
    house_value = result.get("house_value")
    payout = _format_money(result.get("payout_rub"))
    won = (result.get("outcome") or {}).get("kind") == "win"
    if won:
        text = (
            f"Ты {player_value}, казино {house_value} — выигрыш. Выплата {payout} ₽"
        )
    else:
        text = (
            f"Ты {player_value}, казино {house_value} — казино выиграло. Выплата {payout} ₽"
        )
    if available_rub is not None and str(available_rub) != "":
        text += f"\nБаланс: {_format_money(available_rub)} ₽"
    return text


async def start_house_cub(bot: AsyncTeleBot, client: FocusPayClient, message: Any) -> None:
    """Hold the stake from /cub in a private chat and ask the player to throw."""
    if getattr(getattr(message, "chat", None), "type", None) != "private":
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) != 2:
        await bot.reply_to(message, "Использование: <code>/cub [ставка]</code>", parse_mode="HTML")
        return
    try:
        policy = casino_game_policy(await client.get_casino_settings(), game_key="cub")
        bet = validate_game_stake(policy=policy, stake_rub=args[1])
        opened = await client.open_cub(telegram_id=message.from_user.id, stake_rub=bet)
    except ValueError as exc:
        labels = {
            "game_disabled": "❌ Игра против казино временно отключена.",
            "stake_below_minimum": "❌ Ставка меньше разрешённого минимума.",
            "stake_above_maximum": "❌ Ставка превышает разрешённый максимум.",
        }
        await bot.reply_to(message, labels.get(str(exc), "❌ Неверная сумма ставки."))
        return
    except Exception as exc:
        await bot.reply_to(message, f"❌ {_api_detail(exc, 'Не удалось начать игру. Попробуйте позже.')}")
        return
    stake = opened.get("stake_rub") or f"{bet:.2f}"
    prefix = "Ставка уже держится. " if opened.get("already_open") else ""
    await bot.reply_to(
        message,
        f"🎲 <b>Кубик против FocusCasino</b>\n\n"
        f"💰 Ставка: {stake} ₽\n\n"
        f"{prefix}{THROW_PROMPT}",
        parse_mode="HTML",
    )


async def on_house_cub_stake_button(bot: AsyncTeleBot, client: FocusPayClient, call: Any) -> None:
    """Legacy «Поставить» button: open a dice round instead of HMAC play."""
    parts = str(getattr(call, "data", "") or "").split(":")
    if len(parts) == 3:
        raw_bet = parts[2]
    elif len(parts) == 2:
        raw_bet = parts[1]
    else:
        await bot.answer_callback_query(call.id, "❌ Некорректная игра.", show_alert=True)
        return
    try:
        opened = await client.open_cub(telegram_id=call.from_user.id, stake_rub=raw_bet)
    except httpx.HTTPStatusError as exc:
        detail = _api_detail(exc, "Игра недоступна.")
        await bot.answer_callback_query(call.id, f"❌ {detail}"[:200], show_alert=True)
        with contextlib.suppress(Exception):
            await bot.reply_to(call.message, f"❌ {detail}")
        return
    except Exception:
        await bot.answer_callback_query(call.id, "❌ Игра недоступна.", show_alert=True)
        return
    await bot.answer_callback_query(call.id)
    with contextlib.suppress(Exception):
        await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    stake = opened.get("stake_rub") or raw_bet
    await bot.reply_to(
        call.message,
        f"🎲 <b>Кубик против FocusCasino</b>\n\n💰 Ставка: {stake} ₽\n\n{THROW_PROMPT}",
        parse_mode="HTML",
    )


async def try_handle_house_cub_dice(bot: AsyncTeleBot, client: FocusPayClient, message: Any) -> bool:
    """If this DM has an open house cub, accept 🎲, throw the house die, and settle.

    Returns True when the message was consumed as house cub (including errors).
    """
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) != "private":
        return False
    actor = getattr(message, "from_user", None)
    actor_id = getattr(actor, "id", None)
    if getattr(actor, "is_bot", False):
        return True
    if not isinstance(actor_id, int) or actor_id <= 0:
        return False
    dice = getattr(message, "dice", None)
    dice_emoji = getattr(dice, "emoji", None)
    player_value = getattr(dice, "value", None)
    try:
        pending_payload = await client.get_pending_cub(telegram_id=actor_id)
    except Exception:
        logger.exception("Unable to load pending house cub telegram_id=%s", actor_id)
        return False
    pending = pending_payload.get("pending") if isinstance(pending_payload, dict) else None
    if not isinstance(pending, dict) or not pending.get("game_id"):
        return False
    if dice_emoji != DICE_EMOJI or not isinstance(player_value, int):
        await bot.reply_to(message, WRONG_EMOJI_PROMPT)
        return True

    game_id = str(pending["game_id"])
    async with _house_cub_lock(actor_id):
        if actor_id in _house_cub_busy:
            await bot.reply_to(message, BUSY_PROMPT)
            return True
        _house_cub_busy.add(actor_id)
        try:
            await wait_dice_landed()
            house_message = await bot.send_dice(chat_id=chat.id, emoji=DICE_EMOJI)
            house_dice = getattr(house_message, "dice", None)
            house_value = getattr(house_dice, "value", None)
            if getattr(house_dice, "emoji", None) != DICE_EMOJI or not isinstance(house_value, int):
                await bot.reply_to(message, "❌ Казино не смогло кинуть куб. Кинь 🎲 ещё раз.")
                return True
            await wait_dice_landed()
            result = await client.resolve_cub(
                game_id=game_id,
                telegram_id=actor_id,
                player_value=player_value,
                house_value=house_value,
            )
            if result.get("tie"):
                await bot.reply_to(message, TIE_PROMPT)
            else:
                available_rub = None
                with contextlib.suppress(Exception):
                    available_rub = await client.get_balance(actor_id)
                await bot.reply_to(message, _result_text(result, available_rub=available_rub))
        except Exception as exc:
            logger.exception("House cub resolve failed game_id=%s telegram_id=%s", game_id, actor_id)
            await bot.reply_to(message, f"❌ {_api_detail(exc, 'Не удалось завершить игру. Попробуйте кинуть ещё раз.')}")
        finally:
            _house_cub_busy.discard(actor_id)
        return True


def register_house_cub_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    """Register the legacy stake button. /cub itself stays in the PvP router."""

    @bot.callback_query_handler(func=lambda c: str(getattr(c, "data", "")).startswith("house_cub:"))
    async def play_house_cub(call):
        await on_house_cub_stake_button(bot, client, call)

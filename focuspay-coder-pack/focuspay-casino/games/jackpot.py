"""Shared CSGETGO-style jackpot from Telegram: status card and stake."""
from __future__ import annotations

import contextlib
import html
import logging
import re
from decimal import Decimal
from typing import Any

import httpx
from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import casino_game_policy, money, validate_game_stake
from focuspay_client import FocusPayClient
from games.board_style import PHASE_LABELS, render_board, seconds_until, timer_line as style_timer_line
from games.chat_guard import (
    ActiveGameChatGuard,
    callback_chat,
    chat_id_from,
    telegram_user_id,
)
from games.chat_reaper import TTL_SERVICE, reply_ephemeral, try_delete_user_message
from games.jackpot_card import upsert as upsert_jackpot_card
from games.site_links import add_watch_button, append_watch_line, https_only, jackpot_play_url
from games.stake_buttons import stake_keyboard

logger = logging.getLogger(__name__)

STAKE_CALLBACK = "jpbet:"
STAKE_ACCEPTED_TITLE = "🎡 <b>Ставка принята</b>"
USAGE_MESSAGE = (
    "Поставить: <code>/jackpot 100</code> или <code>/jackpot 50р</code>. "
    "Повтор — докид в тот же раунд. Выйти нельзя."
)
_AMOUNT = re.compile(
    r"^(?P<body>\d+(?:[.,]\d{1,2})?)(?P<suf>р|₽|руб|rub)?$",
    re.IGNORECASE,
)


class JackpotCommandError(ValueError):
    """User-facing parse error. str(exc) is the Telegram reply."""


def command_args(text: str) -> list[str]:
    parts = (text or "").split()
    return parts[1:] if parts else []


def parse_amount_token(token: str) -> Decimal | None:
    raw = token.strip()
    match = _AMOUNT.fullmatch(raw)
    if not match:
        return None
    body = match.group("body").replace(",", ".")
    try:
        amount = money(body)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def parse_jackpot_command(text: str) -> Decimal | None:
    """None = status card. Raises JackpotCommandError otherwise."""
    args = command_args(text)
    if not args:
        return None
    if len(args) != 1:
        raise JackpotCommandError(USAGE_MESSAGE)
    amount = parse_amount_token(args[0])
    if amount is None:
        raise JackpotCommandError(USAGE_MESSAGE)
    return amount


def parse_stake_callback(data: str) -> Decimal | None:
    raw = str(data or "")
    if not raw.startswith(STAKE_CALLBACK):
        return None
    token = raw[len(STAKE_CALLBACK) :]
    if token == "custom" or not token:
        return None
    return parse_amount_token(token)


def _fmt_money(value: object) -> str:
    try:
        amount = money(value)
    except (TypeError, ValueError):
        return "0"
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_pct(value: object) -> str:
    return _fmt_money(value)


def https_play_url() -> str | None:
    return https_only(jackpot_play_url())


def seconds_until_spin(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot:
        return None
    return seconds_until(snapshot.get("closes_at"))


def timer_line(snapshot: dict[str, Any] | None) -> str:
    return style_timer_line(
        snapshot,
        spinning_statuses=("locked",),
        spinning_text="Крутится, ставки закрыты.",
        settled_text="Разыгран.",
        refunded_text="Ставка возвращена (один игрок).",
        collect_default=300,
    )


def player_mention_from_row(player: dict[str, Any]) -> str:
    uid = int(player.get("user_id") or 0)
    name = html.escape(str(player.get("display_name") or uid or "игрок")[:80])
    if uid > 0:
        return f'<a href="tg://user?id={uid}">{name}</a>'
    return name


def status_text(
    snapshot: dict[str, Any] | None,
    *,
    viewer_id: int | None = None,
    phase: str | None = None,
    hide_winner: bool = False,
) -> str:
    snap = snapshot if isinstance(snapshot, dict) else {}
    pot = _fmt_money(snap.get("pot_rub") or 0)
    players = snap.get("players") if isinstance(snap.get("players"), list) else []
    count = int(snap.get("player_count") or len(players) or 0)
    max_players = int(snap.get("max_players") or 30)
    rake = _fmt_money(snap.get("rake_percent") or 0)
    status = str(snap.get("status") or "")
    roster: list[str] = []
    if players:
        ranked = sorted(
            [row for row in players if isinstance(row, dict)],
            key=lambda row: float(row.get("chance_pct") or 0),
            reverse=True,
        )
        show = ranked[:3] if phase == "finalists" else ranked
        for row in show:
            amount = _fmt_money(row.get("amount_rub") or 0)
            chance = _fmt_pct(row.get("chance_pct") or 0)
            roster.append(f"• {player_mention_from_row(row)} — {amount} ₽ ({chance}%)")
        if phase == "finalists" and len(ranked) > 3:
            roster.append("• …")
    extra: list[str] = []
    if not hide_winner and status == "settled" and snap.get("winner_id"):
        winner = next(
            (row for row in players if isinstance(row, dict) and int(row.get("user_id") or 0) == int(snap["winner_id"])),
            None,
        )
        payout = _fmt_money(snap.get("payout_rub") or 0)
        if winner:
            extra.append(f"Победитель: {player_mention_from_row(winner)} · {payout} ₽")
        else:
            extra.append(f"Выплата: {payout} ₽")
    mine_amount = snap.get("my_amount_rub") or 0
    try:
        mine_value = money(mine_amount)
    except (TypeError, ValueError):
        mine_value = Decimal("0")
    if mine_value > 0:
        extra.append(f"Вы: {_fmt_money(mine_value)} ₽ ({_fmt_pct(snap.get('my_chance_pct') or 0)}%)")
    elif viewer_id:
        mine_row = next(
            (row for row in players if isinstance(row, dict) and int(row.get("user_id") or 0) == int(viewer_id)),
            None,
        )
        if mine_row:
            extra.append(
                f"Вы: {_fmt_money(mine_row.get('amount_rub'))} ₽ ({_fmt_pct(mine_row.get('chance_pct'))}%)"
            )
    extra.append(USAGE_MESSAGE)
    now = PHASE_LABELS.get(phase or "", "")
    if not now:
        if status == "locked":
            now = PHASE_LABELS["reel"]
        elif status == "settled" and not hide_winner:
            now = PHASE_LABELS["settled"]
        elif status == "refunded":
            now = PHASE_LABELS["refunded"]
        elif seconds_until(snap.get("closes_at")) is None:
            now = PHASE_LABELS["waiting_first"]
        else:
            now = PHASE_LABELS["collect"]
    nxt = "Повтор — докид в тот же раунд" if status in {"", "open"} else ""
    timer = "" if hide_winner and status in {"locked", "settled"} else timer_line(snap)
    text = render_board(
        header="🎡 <b>Джекпот</b>",
        money=f"Банк: <b>{pot} ₽</b>",
        subtitle=f"Игроков: {count} / {max_players}\nРейк: {rake}%",
        roster=roster,
        now=now,
        nxt=nxt,
        timer=timer,
        extra=extra,
    )
    return text


def confirm_text(amount: Decimal, snapshot: dict[str, Any] | None) -> str:
    snap = snapshot if isinstance(snapshot, dict) else {}
    lines = [
        STAKE_ACCEPTED_TITLE,
        f"Списание: {_fmt_money(amount)} ₽",
        f"Ваша доля: {_fmt_money(snap.get('my_amount_rub') or amount)} ₽ ({_fmt_pct(snap.get('my_chance_pct') or 0)}%)",
        f"Банк: {_fmt_money(snap.get('pot_rub') or 0)} ₽",
    ]
    extra = timer_line(snap)
    if extra:
        lines.append(extra)
    return append_watch_line("\n".join(lines), jackpot_play_url())


def _status_keyboard(
    snapshot: dict[str, Any] | None, *, include_watch: bool = False
) -> types.InlineKeyboardMarkup | None:
    snap = snapshot if isinstance(snapshot, dict) else {}
    min_bet = snap.get("min_bet_rub") or getattr(config, "MIN_BET", 10)
    max_bet = snap.get("max_bet_rub") or getattr(config, "MAX_BET", 100000)
    keyboard = stake_keyboard(
        callback_prefix=STAKE_CALLBACK,
        min_bet=min_bet,
        max_bet=max_bet,
        private=False,
    )
    if include_watch:
        add_watch_button(keyboard, jackpot_play_url())
    has_buttons = bool(keyboard.keyboard)
    if not has_buttons:
        return None
    return keyboard


async def reply_html(
    bot: Any,
    message: Any,
    text: str,
    *,
    snapshot: dict[str, Any] | None = None,
    include_watch: bool = False,
) -> None:
    markup = _status_keyboard(snapshot, include_watch=include_watch)
    try:
        await reply_ephemeral(
            bot, message, text, TTL_SERVICE, parse_mode="HTML", reply_markup=markup
        )
        return
    except Exception as exc:
        logger.warning("jackpot Telegram reply with keyboard failed: %s", exc)
    await reply_ephemeral(bot, message, text, TTL_SERVICE, parse_mode="HTML")


def _api_detail(exc: Exception, fallback: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        with contextlib.suppress(Exception):
            detail = exc.response.json().get("detail")
            if detail:
                return str(detail)
    return fallback


async def _snapshot(client: FocusPayClient, telegram_id: int) -> dict[str, Any]:
    try:
        return await client.get_jackpot(telegram_id=telegram_id)
    except Exception:
        logger.exception("jackpot snapshot failed telegram_id=%s", telegram_id)
        return {}


async def _place(
    bot: Any,
    client: FocusPayClient,
    *,
    user: Any,
    chat: Any,
    reply_target: Any,
    amount: Decimal,
    guard: ActiveGameChatGuard,
) -> None:
    user_id = telegram_user_id(user)
    chat_id = chat_id_from(chat)
    if user_id is None or chat_id is None or chat_id == 0:
        return
    try:
        policy = casino_game_policy(await client.get_casino_settings(), game_key="jackpot")
        validate_game_stake(policy=policy, stake_rub=amount)
    except ValueError as exc:
        labels = {
            "game_disabled": "❌ Джекпот временно выключен.",
            "stake_below_minimum": "❌ Ставка меньше разрешённого минимума.",
            "stake_above_maximum": "❌ Ставка превышает разрешённый максимум.",
        }
        await reply_html(bot, reply_target, labels.get(str(exc), "❌ Неверная сумма ставки."))
        return
    try:
        placed = await client.place_jackpot_bet(
            telegram_id=user_id,
            notify_chat_id=chat_id,
            amount_rub=amount,
        )
    except Exception as exc:
        await reply_html(
            bot, reply_target, f"❌ {_api_detail(exc, 'Не удалось поставить. Попробуйте позже.')}"
        )
        return
    snap = placed if isinstance(placed, dict) else {}
    try:
        await upsert_jackpot_card(bot, client, chat_id, snap, telegram_id=user_id)
    except Exception:
        logger.exception("jackpot confirm reply failed after bet telegram_id=%s", user_id)
        with contextlib.suppress(Exception):
            await reply_html(bot, reply_target, confirm_text(amount, snap), snapshot=snap, include_watch=True)


async def handle_jackpot_command(
    bot: Any, client: FocusPayClient, message: Any, *, guard: ActiveGameChatGuard
) -> None:
    if not await guard.require_message(bot, message):
        return
    user = getattr(message, "from_user", None)
    chat = getattr(message, "chat", None)
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        return
    raw = str(getattr(message, "text", "") or "")
    try:
        parsed = parse_jackpot_command(raw)
    except JackpotCommandError as exc:
        await reply_html(bot, message, str(exc))
        await try_delete_user_message(bot, message)
        return
    if parsed is None:
        snapshot = await _snapshot(client, user_id)
        await reply_html(bot, message, status_text(snapshot, viewer_id=user_id), snapshot=snapshot)
        await try_delete_user_message(bot, message)
        return
    await _place(bot, client, user=user, chat=chat, reply_target=message, amount=parsed, guard=guard)
    await try_delete_user_message(bot, message)


async def handle_jackpot_callback(
    bot: Any, client: FocusPayClient, call: Any, *, guard: ActiveGameChatGuard
) -> None:
    if not await guard.require_callback(bot, call):
        return
    amount = parse_stake_callback(str(getattr(call, "data", "") or ""))
    if amount is None:
        with contextlib.suppress(Exception):
            await bot.answer_callback_query(call.id)
        return
    message = getattr(call, "message", None)
    user = getattr(call, "from_user", None)
    chat = callback_chat(call)
    with contextlib.suppress(Exception):
        await bot.answer_callback_query(call.id)
    if message is None or chat is None:
        return
    await _place(bot, client, user=user, chat=chat, reply_target=message, amount=amount, guard=guard)


def register_jackpot_handlers(bot: AsyncTeleBot, client: FocusPayClient) -> None:
    guard = ActiveGameChatGuard(client)

    @bot.message_handler(commands=["jackpot", "джекпот"])
    async def cmd_jackpot(message):
        try:
            await handle_jackpot_command(bot, client, message, guard=guard)
        except Exception:
            logger.exception("jackpot command failed")
            with contextlib.suppress(Exception):
                await bot.reply_to(message, "❌ Не удалось поставить. Попробуйте позже.")

    @bot.callback_query_handler(func=lambda c: str(getattr(c, "data", "")).startswith(STAKE_CALLBACK))
    async def cb_jackpot_stake(call):
        try:
            await handle_jackpot_callback(bot, client, call, guard=guard)
        except Exception:
            logger.exception("jackpot stake callback failed")
            with contextlib.suppress(Exception):
                await bot.answer_callback_query(call.id, "Не удалось поставить.", show_alert=True)

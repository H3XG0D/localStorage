"""Durable Baccara PvP game.

RAM contains Telegram UI cache only; all game and balance transitions are owned by
the game-level lifecycle API.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Tuple

from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from finance import casino_game_policy, settlement_payout_rub, validate_game_stake
from focuspay_client import FocusPayClient
from games.card_fairness import apply_fairness_fields, result_fairness_text, waiting_fairness_text
from games.chat_guard import ActiveGameChatGuard
from games.stake_buttons import command_stake_arg, is_private_chat, stake_keyboard
from games.site_links import add_watch_button, append_watch_line, duel_url, watch_keyboard
from games.table_wizard import start_wizard_for_command

active_games = {}
game_counter = 0
game_counter_lock = asyncio.Lock()
_game_locks = {}
MAX_ACTIVE_PER_USER = 3
logger = logging.getLogger(__name__)
WAIT_TIMEOUT_HOURS = 24
MOVE_TIMEOUT_HOURS = 2


def get_game_lock(game_id: int) -> asyncio.Lock:
    return _game_locks.setdefault(game_id, asyncio.Lock())


def _drop_cache(gid: int) -> None:
    active_games.pop(gid, None)
    _game_locks.pop(gid, None)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Decimal): return format(value, "f")
    if isinstance(value, dict): return {k: _json_value(v) for k, v in value.items() if k != "state_version"}
    if isinstance(value, list): return [_json_value(v) for v in value]
    return value


def _apply_response(game: dict, response: dict) -> dict:
    durable = response.get("game", response)
    version = durable.get("state_version", response.get("state_version"))
    if version is None: raise RuntimeError("lifecycle response has no state_version")
    game["state_version"] = version
    game["financial_state"] = durable.get("financial_state", game.get("financial_state"))
    game["durable_status"] = durable.get("status", game.get("durable_status"))
    return durable


async def _persist(client: FocusPayClient, game: dict) -> dict:
    return _apply_response(game, await client.persist_game_state(
        game_id=game["settlement_game_id"],
        expected_state_version=game["state_version"],
        game_state=_json_value(game),
    ))


_TERMINAL_STATUSES = {
    "settled", "finished", "released", "cancelled", "canceled", "expired", "closed", "completed",
}


def _terminal_response(response: dict) -> bool:
    durable = response.get("game", response)
    return str(durable.get("status", "")).lower() in _TERMINAL_STATUSES


async def _settle_committed_outcome(client: FocusPayClient, game: dict) -> dict:
    settlement = await client.settle_committed_outcome(game_id=game["settlement_game_id"])
    _apply_response(game, settlement)
    if not _terminal_response(settlement):
        raise RuntimeError("committed outcome settlement is not terminal")
    return settlement


async def _commit_and_settle(
    client: FocusPayClient,
    game: dict,
    *,
    kind: str,
    reason: str,
    outcome: dict | None = None,
) -> dict:
    """Commit every outcome before the backend performs terminal accounting."""
    _apply_response(game, await client.commit_game_outcome(
        game_id=game["settlement_game_id"],
        winner_id=None,
        expected_state_version=game["state_version"],
        outcome={"kind": kind, "reason": reason, **(outcome or {})},
    ))
    return await _settle_committed_outcome(client, game)


def _commit_line(game: dict) -> str:
    return waiting_fairness_text(game)


def _seed_line(game: dict, seed: str | None) -> str:
    return result_fairness_text(game_type="baccara", game=game, seed=seed)


async def _deal_to_hand(client: FocusPayClient, game: dict, telegram_id: int, hand_size: int) -> list:
    result = await client.deal_cards(
        game_id=game["settlement_game_id"],
        telegram_id=telegram_id,
        hand_size=hand_size,
    )
    cards = result.get("cards")
    if not isinstance(cards, list) or len(cards) != hand_size:
        raise RuntimeError("card deal response is invalid")
    if not all(isinstance(card, str) and card for card in cards):
        raise RuntimeError("card deal response is invalid")
    apply_fairness_fields(game, result)
    return cards


async def _reveal_seed(client: FocusPayClient, game: dict, telegram_id: int) -> str | None:
    try:
        revealed = await client.reveal_cards(
            game_id=game["settlement_game_id"],
            telegram_id=telegram_id,
        )
    except Exception:
        return None
    apply_fairness_fields(game, revealed)
    seed = revealed.get("rng_seed")
    return seed if isinstance(seed, str) and seed else None


def bak_card_value(card: str) -> int:
    rank = card[:-1]
    return 0 if rank in ("10", "J", "Q", "K") else 1 if rank == "A" else int(rank)


def bak_hand_score(cards: list) -> int: return sum(bak_card_value(c) for c in cards) % 10
def bak_fmt_cards(cards: list) -> str: return " ".join(cards) if cards else "—"
def bak_render_menu_text() -> str: return "🃏 <b>Baccara</b>\n\nКарточная игра 1 на 1. Выигрывает тот, чья рука ближе к 9 очкам."


def bak_render_menu_kb(user_id: int, page: int = 0):
    kb = types.InlineKeyboardMarkup()
    waiting = sorted((gid, g) for gid, g in active_games.items() if g["status"] == "waiting")
    page_items = waiting[max(page, 0) * 5:max(page, 0) * 5 + 5]
    for gid, g in page_items:
        marker = "🟢 " if g["creator_id"] == user_id else ""
        kb.add(types.InlineKeyboardButton(f"{marker}Игра #{gid} | 1/2 | {g['bet']:.2f} {config.CURRENCY_SYMBOL}", callback_data=f"bak_view_{gid}"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить", callback_data="bak_menu"))
    kb.add(types.InlineKeyboardButton("➕ Создать игру", callback_data="bak_create"))
    return kb


async def _send_result(bot, game: dict, gid: int, text: str) -> None:
    for target in (game["creator_id"], game["opponent_id"]):
        try: await bot.send_message(target, text, parse_mode="HTML")
        except Exception: pass


async def bak_finalize(bot, client: FocusPayClient, gid: int):
    """Commit a winner before settlement; release draws only after backend confirmation."""
    async with get_game_lock(gid):
        game = active_games.get(gid)
        if not game or game["status"] not in {"playing", "finalizing"}: return
        game["status"] = "finalizing"
        try: await _persist(client, game)
        except Exception: return
        cs, os_ = bak_hand_score(game["cards_creator"]), bak_hand_score(game["cards_opponent"])
        creator = f"<a href='tg://user?id={game['creator_id']}'>{game['creator_name']}</a>"
        opponent = f"<a href='tg://user?id={game['opponent_id']}'>{game['opponent_name']}</a>"
        prefix = f"📊 <b>Результаты Baccara #{gid}</b>\n\n🃏 <b>Раздача:</b>\n{creator}: <code>{bak_fmt_cards(game['cards_creator'])}</code> [{cs}]\n{opponent}: <code>{bak_fmt_cards(game['cards_opponent'])}</code> [{os_}]\n\n"
        try:
            if cs == os_:
                game["status"] = "draw_releasing"
                await _persist(client, game)
                await _commit_and_settle(
                    client,
                    game,
                    kind="draw",
                    reason="draw",
                    outcome={
                        "creator_score": cs,
                        "opponent_score": os_,
                        "creator_cards": game["cards_creator"],
                        "opponent_cards": game["cards_opponent"],
                        "decisions": {
                            "creator": game["decision_creator"],
                            "opponent": game["decision_opponent"],
                        },
                    },
                )
                text = prefix + "🤝 Ничья! Ставки возвращены."
            else:
                winner_id, winner_link = (game["creator_id"], creator) if cs > os_ else (game["opponent_id"], opponent)
                outcome = {"kind": "winner", "winner_id": winner_id, "creator_score": cs, "opponent_score": os_, "creator_cards": game["cards_creator"], "opponent_cards": game["cards_opponent"], "decisions": {"creator": game["decision_creator"], "opponent": game["decision_opponent"]}}
                _apply_response(game, await client.commit_game_outcome(
                    game_id=game["settlement_game_id"],
                    winner_id=winner_id,
                    expected_state_version=game["state_version"],
                    outcome=outcome,
                ))
                settlement = await _settle_committed_outcome(client, game)
                payout = settlement_payout_rub(settlement)
                amount = f"<b>{payout:.2f} {config.CURRENCY_SYMBOL}</b>"
                text = prefix + f"🏆 Победитель: {winner_link}\n💰 Выигрыш: {amount}"
            text += _seed_line(game, await _reveal_seed(client, game, game["creator_id"]))
        except Exception as exc:
            game["status"] = "finalization_failed"
            try: await _persist(client, game)
            except Exception: pass
            await _send_result(bot, game, gid, f"⚠️ <b>Baccara #{gid}</b> завершена, но расчёт требует проверки.\nИдентификатор: <code>{game['settlement_game_id']}</code>")
            return
        _drop_cache(gid)
    await _send_result(bot, game, gid, text)


async def _finish_if_join_settled(bot, client: FocusPayClient, game: dict, gid: int, join_response: dict, durable: dict) -> bool:
    """Site tables settle on join. Do not send hit/stand — the creator has no Telegram DM."""
    if not _terminal_response(join_response):
        return False
    outcome = durable.get("outcome") if isinstance(durable.get("outcome"), dict) else {}
    game["cards_creator"] = list(outcome.get("creator_cards") or [])
    game["cards_opponent"] = list(outcome.get("opponent_cards") or [])
    try:
        settlement = await _settle_committed_outcome(client, game)
        amount = f"<b>{settlement_payout_rub(settlement):.2f} {config.CURRENCY_SYMBOL}</b>"
    except Exception:
        amount = None
    try:
        cs = int(outcome["creator_score"])
        os_ = int(outcome["opponent_score"])
    except (KeyError, TypeError, ValueError):
        cs, os_ = bak_hand_score(game["cards_creator"]), bak_hand_score(game["cards_opponent"])
    creator = f"<a href='tg://user?id={game['creator_id']}'>{game['creator_name']}</a>"
    opponent = f"<a href='tg://user?id={game['opponent_id']}'>{game['opponent_name']}</a>"
    prefix = (
        f"📊 <b>Результаты Baccara #{gid}</b>\n\n🃏 <b>Раздача:</b>\n"
        f"{creator}: <code>{bak_fmt_cards(game['cards_creator'])}</code> [{cs}]\n"
        f"{opponent}: <code>{bak_fmt_cards(game['cards_opponent'])}</code> [{os_}]\n\n"
    )
    if str(outcome.get("kind") or "") == "draw" or cs == os_:
        text = prefix + "🤝 Ничья! Ставки возвращены."
    else:
        winner_id = outcome.get("winner_id")
        winner_link = creator if winner_id == game["creator_id"] else opponent
        text = prefix + f"🏆 Победитель: {winner_link}"
        if amount:
            text += f"\n💰 Выигрыш: {amount}"
    text += _seed_line(game, await _reveal_seed(client, game, game["creator_id"]))
    _drop_cache(gid)
    await _send_result(bot, game, gid, text)
    return True


def register_baccara_handlers(bot: AsyncTeleBot, client: FocusPayClient):
    guard = ActiveGameChatGuard(client)
    pending_bets: set[tuple[int, int]] = set()

    def pending_bet_key(message) -> tuple[int, int] | None:
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        user_id = getattr(getattr(message, "from_user", None), "id", None)
        if isinstance(chat_id, int) and isinstance(user_id, int):
            return chat_id, user_id
        return None

    async def _load_policy():
        return casino_game_policy(
            await client.get_casino_settings(),
            game_key="baccara",
            local_min_bet_rub=config.BACCARA_MIN_BET,
        )

    async def create_waiting_game(*, chat_id: int, user, bet) -> None:
        user_id = user.id
        if sum(g["creator_id"] == user_id and g["status"] == "waiting" for g in active_games.values()) >= MAX_ACTIVE_PER_USER:
            await bot.send_message(chat_id, f"❌ Достигнут лимит активных игр ({MAX_ACTIVE_PER_USER}).")
            return
        global game_counter
        async with game_counter_lock:
            game_counter += 1
            gid = game_counter
        game = {
            "game_id": gid, "settlement_game_id": f"baccara-{uuid.uuid4()}", "creator_id": user_id,
            "creator_name": user.first_name or user.username or str(user_id), "opponent_id": None,
            "opponent_name": None, "bet": bet, "deck_creator": [], "deck_opponent": [],
            "cards_creator": [], "cards_opponent": [], "decision_creator": None, "decision_opponent": None,
            "msg_id_creator": None, "msg_id_opponent": None, "chat_id_creator": chat_id, "chat_id_opponent": None,
            "status": "waiting", "created_at": datetime.utcnow(), "started_at": None, "rng_commit": None,
        }
        try:
            prepared = await client.prepare_cards(
                game_id=game["settlement_game_id"], game_type="baccara", telegram_id=user_id,
            )
            apply_fairness_fields(game, prepared)
            if not isinstance(game.get("rng_commit"), str) or not game.get("rng_commit"):
                raise RuntimeError("card commit is missing")
            _apply_response(game, await client.create_or_resume_game(
                game_id=game["settlement_game_id"], game_type="baccara", creator_id=user_id, stake_rub=bet,
            ))
            await _persist(client, game)
        except Exception:
            try:
                if "state_version" in game:
                    await _commit_and_settle(
                        client, game, kind="cancel", reason="create_state_persist_failed",
                        outcome={"creator_id": user_id},
                    )
            except Exception:
                pass
            await bot.send_message(chat_id, "❌ Действие временно недоступно. Попробуйте ещё раз позже.")
            return
        active_games[gid] = game
        pending_bets.discard((chat_id, user_id))
        url = duel_url(game["settlement_game_id"])
        await bot.send_message(
            chat_id,
            append_watch_line(
                f"✅ Игра Baccara #{gid} создана\nСтавка: <b>{bet:.2f} {config.CURRENCY_SYMBOL}</b>{_commit_line(game)}\n\nОжидайте второго игрока.",
                url,
            ),
            parse_mode="HTML",
            reply_markup=watch_keyboard(url),
        )

    async def prompt_stake(chat, user) -> None:
        try:
            policy = await _load_policy()
            balance = await client.get_balance(telegram_id=user.id)
            if not policy.enabled:
                raise ValueError("game_disabled")
        except Exception:
            await bot.send_message(chat.id, "❌ Ошибка получения настроек или баланса.")
            return
        private = is_private_chat(chat, user)
        keyboard = stake_keyboard(
            callback_prefix="bak_stake:", min_bet=policy.min_bet_rub, max_bet=policy.max_bet_rub, private=private,
        )
        hint = "Выберите ставку кнопкой." if not private else "Выберите ставку или введите свою сумму."
        await bot.send_message(
            chat.id,
            f"🃏 <b>Создание игры Baccara</b>\n\nМин. ставка: <b>{policy.min_bet_rub:.2f} {config.CURRENCY_SYMBOL}</b>\nМакс. ставка: <b>{policy.max_bet_rub:.2f} {config.CURRENCY_SYMBOL}</b>\nВаш баланс: <b>{balance:.2f} {config.CURRENCY_SYMBOL}</b>\n\n{hint}",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    @bot.message_handler(commands=["baccara"])
    async def cmd_baccara(message):
        await start_wizard_for_command(bot, client, message, "baccara")

    @bot.callback_query_handler(func=lambda c: c.data == "bak_menu")
    async def cb_menu(call):
        if not await guard.require_callback(bot, call):
            return
        try: await bot.edit_message_text(bak_render_menu_text(), chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=bak_render_menu_kb(call.from_user.id))
        except Exception: pass
        await bot.answer_callback_query(call.id, "🔄 Обновлено")

    @bot.callback_query_handler(func=lambda c: c.data == "bak_create")
    async def cb_create(call):
        if not await guard.require_callback(bot, call):
            return
        await start_wizard_for_command(bot, client, call.message, "baccara", user=call.from_user)
        await bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("bak_stake:"))
    async def cb_stake(call):
        if not await guard.require_callback(bot, call):
            return
        raw = str(call.data).split(":", 1)[1]
        if raw == "custom":
            if not is_private_chat(call.message.chat, call.from_user):
                await bot.answer_callback_query(call.id, "Свою сумму можно ввести только в личке с ботом.", show_alert=True)
                return
            pending_bets.add((call.message.chat.id, call.from_user.id))
            await bot.send_message(call.message.chat.id, "✏️ Отправьте сумму ставки одним сообщением.")
            await bot.answer_callback_query(call.id)
            return
        try:
            policy = await _load_policy()
            bet = validate_game_stake(policy=policy, stake_rub=raw)
        except Exception:
            await bot.answer_callback_query(call.id, "❌ Ставка недоступна.", show_alert=True)
            return
        await bot.answer_callback_query(call.id)
        await create_waiting_game(chat_id=call.message.chat.id, user=call.from_user, bet=bet)

    @bot.message_handler(
        func=lambda message: is_private_chat(getattr(message, "chat", None), getattr(message, "from_user", None))
        and pending_bet_key(message) in pending_bets,
        content_types=["text"],
    )
    async def process_bet(message):
        key = pending_bet_key(message)
        if key is None:
            return
        if not await guard.require_message(bot, message):
            return
        try:
            policy = await _load_policy()
            bet = validate_game_stake(policy=policy, stake_rub=str(getattr(message, "text", "")).strip().replace(",", "."))
        except Exception:
            await bot.send_message(message.chat.id, "❌ Неверная ставка или сумма вне допустимых лимитов.")
            return
        await create_waiting_game(chat_id=message.chat.id, user=message.from_user, bet=bet)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("bak_view_"))
    async def cb_view(call):
        if not await guard.require_callback(bot, call):
            return
        try: gid = int(call.data.removeprefix("bak_view_"))
        except ValueError: return
        game = active_games.get(gid)
        if not game or game["status"] != "waiting":
            await bot.answer_callback_query(call.id, "❌ Игра недоступна.", show_alert=True); return
        link = f"<a href='tg://user?id={game['creator_id']}'>{game['creator_name']}</a>"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🗑 Удалить игру" if call.from_user.id == game["creator_id"] else "🎮 Подключиться", callback_data=f"bak_delself_{gid}" if call.from_user.id == game["creator_id"] else f"bak_join_{gid}"))
        kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="bak_menu"))
        try: await bot.edit_message_text(f"🃏 <b>Baccara #{gid}</b>\n\n💰 Ставка: <b>{game['bet']:.2f} {config.CURRENCY_SYMBOL}</b>{_commit_line(game)}\n\n👥 Игроки\n1 — {link}\n2 — Ожидание", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML", reply_markup=kb)
        except Exception: pass
        await bot.answer_callback_query(call.id)

    async def next_gid():
        global game_counter
        async with game_counter_lock:
            game_counter += 1
            return game_counter

    def bump(gid: int) -> None:
        global game_counter
        if gid > game_counter:
            game_counter = gid

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and (c.data.startswith("bak_join_") or c.data.startswith("bak_wjoin_")))
    async def cb_join(call):
        if not await guard.require_callback(bot, call):
            return
        data = str(call.data)
        gid = None
        if data.startswith("bak_wjoin_"):
            from games.card_invite import adopt_waiting_card_game
            durable_id = data.removeprefix("bak_wjoin_")
            gid = await adopt_waiting_card_game(
                client,
                game_id=durable_id,
                game_type="baccara",
                chat_id=getattr(getattr(call.message, "chat", None), "id", None),
                cache=active_games,
                persist=_persist,
                next_gid=next_gid,
                bump_counter=bump,
            )
        else:
            try:
                gid = int(data.removeprefix("bak_join_"))
            except ValueError:
                gid = None
        if gid is None:
            await bot.answer_callback_query(call.id, "❌ Игра недоступна.", show_alert=True)
            return
        async with get_game_lock(gid):
            game = active_games.get(gid)
            if not game or game["status"] != "waiting" or call.from_user.id == game["creator_id"]:
                await bot.answer_callback_query(call.id, "❌ Игра недоступна.", show_alert=True); return
            game.update(status="joining", joining_opponent_id=call.from_user.id)
            join_completed = False
            try:
                await _persist(client, game)
                join_response = await client.join_and_hold_game(
                    game_id=game["settlement_game_id"], opponent_id=call.from_user.id
                )
                durable = _apply_response(game, join_response)
                join_completed = True
                game.update(
                    opponent_id=call.from_user.id,
                    opponent_name=call.from_user.first_name or call.from_user.username or str(call.from_user.id),
                    chat_id_opponent=call.message.chat.id,
                    started_at=datetime.utcnow(),
                    joining_opponent_id=None,
                )
                if await _finish_if_join_settled(bot, client, game, gid, join_response, durable):
                    await bot.answer_callback_query(call.id, "✅ Раунд сыгран!")
                    return
                game["status"] = "playing"
                game["cards_creator"] = await _deal_to_hand(client, game, game["creator_id"], 2)
                game["cards_opponent"] = await _deal_to_hand(client, game, call.from_user.id, 2)
                await _persist(client, game)
            except Exception as exc:
                if not join_completed:
                    game["status"] = "waiting"
                    game.pop("joining_opponent_id", None)
                else:
                    game["status"] = "recovery_pending"
                await bot.answer_callback_query(call.id, "❌ Действие временно недоступно. Попробуйте ещё раз позже.", show_alert=True); return
            for side, uid in (("creator", game["creator_id"]), ("opponent", game["opponent_id"])):
                sent = await bak_send_hand(bot, uid, gid, game[f"cards_{side}"], game)
                game[f"chat_id_{side}"] = sent[0] if sent else game[f"chat_id_{side}"]
                game[f"msg_id_{side}"] = sent[1] if sent else None
            await _persist(client, game)
        await bot.answer_callback_query(call.id, "✅ Вы в игре!")

    async def bak_send_hand(bot_, user_id: int, gid: int, cards: list, game: dict) -> Optional[Tuple[int, int]]:
        kb = types.InlineKeyboardMarkup(); kb.row(types.InlineKeyboardButton("🎴 Взять карту", callback_data=f"bak_hit_{gid}"), types.InlineKeyboardButton("✋ Оставить", callback_data=f"bak_stand_{gid}"))
        add_watch_button(kb, duel_url(game.get("settlement_game_id")))
        try: return (lambda m: (m.chat.id, m.message_id))(await bot_.send_message(user_id, append_watch_line(f"🃏 <b>Baccara #{gid}</b>\n\nВаши карты: <code>{bak_fmt_cards(cards)}</code>\nВсего очков: <b>{bak_hand_score(cards)}</b>\n\nВзять ещё одну карту или оставить вскрытые?{_commit_line(game)}", duel_url(game.get("settlement_game_id"))), parse_mode="HTML", reply_markup=kb))
        except Exception: return None

    @bot.callback_query_handler(func=lambda c: c.data.startswith("bak_hit_") or c.data.startswith("bak_stand_"))
    async def cb_action(call):
        hit = call.data.startswith("bak_hit_")
        try: gid = int(call.data.removeprefix("bak_hit_" if hit else "bak_stand_"))
        except ValueError: return
        both_done = False
        async with get_game_lock(gid):
            game = active_games.get(gid)
            if not game or game["status"] != "playing": await bot.answer_callback_query(call.id, "❌ Игра завершена.", show_alert=True); return
            side = "creator" if call.from_user.id == game["creator_id"] else "opponent" if call.from_user.id == game["opponent_id"] else None
            if not side or game[f"decision_{side}"] is not None: await bot.answer_callback_query(call.id, "❌ Ход недоступен.", show_alert=True); return
            previous_cards = list(game[f"cards_{side}"])
            try:
                if hit:
                    game[f"cards_{side}"] = await _deal_to_hand(client, game, call.from_user.id, len(previous_cards) + 1)
                game[f"decision_{side}"] = "hit" if hit else "stand"
                await _persist(client, game)
            except Exception:
                game[f"cards_{side}"] = previous_cards
                game[f"decision_{side}"] = None
                await bot.answer_callback_query(call.id, "❌ Не удалось сохранить ход.", show_alert=True); return
            cards = game[f"cards_{side}"]
            try: await bot.edit_message_text(f"🃏 <b>Baccara #{gid}</b>\n\nВаши карты: <code>{bak_fmt_cards(cards)}</code>\nВсего очков: <b>{bak_hand_score(cards)}</b>\n\nОжидайте результатов...", chat_id=game[f"chat_id_{side}"], message_id=game[f"msg_id_{side}"], parse_mode="HTML", reply_markup=None)
            except Exception: pass
            both_done = game["decision_creator"] is not None and game["decision_opponent"] is not None
        await bot.answer_callback_query(call.id, "✅ Ход принят")
        if both_done: asyncio.create_task(bak_finalize(bot, client, gid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("bak_delself_"))
    async def cb_delete(call):
        if not await guard.require_callback(bot, call):
            return
        try: gid = int(call.data.removeprefix("bak_delself_"))
        except ValueError: return
        async with get_game_lock(gid):
            game = active_games.get(gid)
            if not game or game["status"] != "waiting" or call.from_user.id != game["creator_id"]:
                await bot.answer_callback_query(call.id, "❌ Игра недоступна.", show_alert=True); return
            if (datetime.utcnow() - game["created_at"]).total_seconds() < 180:
                await bot.answer_callback_query(call.id, "⏱ Удалить игру можно через 3 минуты.", show_alert=True); return
            game["status"] = "cancelling"
            try:
                await _persist(client, game)
                await _commit_and_settle(
                    client,
                    game,
                    kind="cancel",
                    reason="creator_cancelled",
                    outcome={"creator_id": game["creator_id"]},
                )
            except Exception as exc:
                await bot.answer_callback_query(call.id, "❌ Действие временно недоступно. Попробуйте ещё раз позже.", show_alert=True); return
            bet = game["bet"]; _drop_cache(gid)
        await bot.answer_callback_query(call.id, f"✅ Игра #{gid} удалена. {bet:.2f} {config.CURRENCY_SYMBOL} возвращено на баланс.", show_alert=True)


async def process_baccara_timeouts(bot: AsyncTeleBot, client: FocusPayClient, *, now: datetime | None = None) -> None:
    current = now or datetime.utcnow()
    for gid, snapshot in list(active_games.items()):
        expired_waiting = snapshot["status"] == "waiting" and (current - snapshot["created_at"]).total_seconds() > WAIT_TIMEOUT_HOURS * 3600
        expired_move = snapshot["status"] == "playing" and snapshot.get("started_at") and (current - snapshot["started_at"]).total_seconds() > MOVE_TIMEOUT_HOURS * 3600
        if not expired_waiting and not expired_move: continue
        finalize = False
        async with get_game_lock(gid):
            game = active_games.get(gid)
            if not game: continue
            if expired_waiting:
                game["status"] = "timed_out"
                try:
                    await _persist(client, game)
                    await _commit_and_settle(
                        client,
                        game,
                        kind="timeout",
                        reason="waiting_timeout",
                        outcome={"phase": "waiting"},
                    )
                except Exception: continue
                _drop_cache(gid); await bot.send_message(game["creator_id"], f"⌛ Игра Baccara #{gid} отменена. Ставка возвращена на баланс.")
                continue
            creator_done, opponent_done = game["decision_creator"] is not None, game["decision_opponent"] is not None
            if not creator_done and not opponent_done:
                game["status"] = "timed_out"
                try:
                    await _persist(client, game)
                    await _commit_and_settle(
                        client,
                        game,
                        kind="timeout",
                        reason="no_moves_timeout",
                        outcome={"phase": "playing", "decisions": {"creator": None, "opponent": None}},
                    )
                except Exception: continue
                _drop_cache(gid)
                for uid in (game["creator_id"], game["opponent_id"]): await bot.send_message(uid, f"⌛ Никто не сделал ход в Baccara #{gid}, ставки возвращены.")
            else:
                if not creator_done: game["decision_creator"] = "timeout"
                if not opponent_done: game["decision_opponent"] = "timeout"
                try: await _persist(client, game)
                except Exception: continue
                finalize = True
        if finalize: await bak_finalize(bot, client, gid)


async def baccara_cleaner(bot: AsyncTeleBot, client: FocusPayClient):
    while True:
        try:
            await asyncio.sleep(60); await process_baccara_timeouts(bot, client)
        except Exception as exc: print(f"[baccara_cleaner] Ошибка: {exc}")

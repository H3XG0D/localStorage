"""Основной файл казино-бота."""
import asyncio
import contextlib
import inspect
import logging
import math
from io import BytesIO
from typing import Mapping

import httpx

from telebot import types
from telebot.async_telebot import AsyncTeleBot

import config
from casino_menu import (
    main_menu_keyboard,
    miniapp_web_app_url,
    MENU_CREATE_GAME,
    MENU_FIND_GAME,
    MENU_MY_GAMES,
    MENU_PROFILE,
    MENU_BALANCE,
    MENU_DEPOSIT,
)
from focuspay_client import get_focuspay_client, close_focuspay_client
from web_login import maybe_send_site_login
from recovery import default_worker_id, recovery_outbox_loop, run_recovery_pass
from wagering import (
    deposit_wagering_for_amount,
    deposit_wagering_rules,
    wagering_hint,
)
from games.chat_reaper import (
    TTL_HELP,
    TTL_SERVICE,
    reaper_loop,
    send_ephemeral,
    try_delete_user_message,
)
from games.pvp import (
    hydrate_active_pvp_games,
    pvp_invitation_loop,
    register_pvp_handlers,
)
from games.card_invite import hydrate_waiting_card_games
from games.live_table_hydrate import hydrate_live_table_cards
from games.table_wizard import start_wizard
from games.v2_tables import register_v2_table_handlers, send_v2_lobby, send_v2_my_tables
from games.v2_runtime import register_v2_runtime_handlers, drain_ready_watchers
from games.drama import drain_drama
from games import baccara as baccara_mod
from games import blackjack as blackjack_mod
from games.baccara import register_baccara_handlers, baccara_cleaner
from games.blackjack import register_blackjack_handlers, blackjack_cleaner
from games.fairness import register_fairness_handlers
from games.help import render_help
from games.roulette_table import register_roulette_table_handlers
from games.jackpot import register_jackpot_handlers

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = AsyncTeleBot(config.BOT_TOKEN)


# ============================================================================
# HANDLERS
# ============================================================================


def _staging_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Инлайн-хаб под карточкой: те же действия, что и в reply-меню."""
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("🎮 Создать игру", callback_data="menu:creategame"),
        types.InlineKeyboardButton("🎯 Активные игры", callback_data="menu:lobby"),
    )
    keyboard.add(
        types.InlineKeyboardButton("🎲 Мои игры", callback_data="menu:mygames"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="menu:profile"),
    )
    keyboard.add(
        types.InlineKeyboardButton("💰 Баланс", callback_data="menu:balance"),
        types.InlineKeyboardButton("💳 Пополнить", callback_data="menu:deposit"),
    )
    keyboard.add(
        types.InlineKeyboardButton("🏧 Вывод", callback_data="menu:withdraw"),
        types.InlineKeyboardButton("🔄 Обновить", callback_data="menu:refresh"),
    )
    url = miniapp_web_app_url()
    if url:
        keyboard.add(types.InlineKeyboardButton("🎰 На сайте", web_app=types.WebAppInfo(url=url)))
    return keyboard


def _profile_keyboard() -> types.InlineKeyboardMarkup:
    """Инлайн-хаб под карточкой профиля — одинаковый во всех окружениях."""
    return _staging_menu_keyboard()


def _is_private(message) -> bool:
    return getattr(getattr(message, "chat", None), "type", "") == "private"


def _profile_money(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _profile_text(profile: dict) -> str:
    wagering = profile.get("wagering") if isinstance(profile.get("wagering"), dict) else {}
    week = profile.get("current_week") if isinstance(profile.get("current_week"), dict) else {}
    prior = profile.get("prior_cashback") if isinstance(profile.get("prior_cashback"), dict) else None
    currency = config.CURRENCY_SYMBOL
    text = (
        "🎰 <b>Профиль казино</b>\n\n"
        f"💰 Доступно: <b>{_profile_money(profile.get('available_rub'))} {currency}</b>\n"
        f"🔒 Нужно поставить: {_profile_money(wagering.get('remaining_rub'))} {currency}\n"
    )
    remaining_house = wagering.get("remaining_house_take_rub")
    try:
        remaining_house_value = float(remaining_house) if remaining_house is not None else 0.0
    except (TypeError, ValueError):
        remaining_house_value = 0.0
    if remaining_house_value > 0:
        rate = wagering.get("commission_rate_percent")
        rate_bit = f" при комиссии {_profile_money(rate)}%" if rate not in (None, "") else ""
        text += (
            f"Казино должно получить ещё {_profile_money(remaining_house)} {currency} "
            f"комиссии с ваших ставок{rate_bit}.\n"
        )
    text += (
        "\n"
        "📅 <b>Текущая неделя</b>\n"
        f"Ставки: {_profile_money(week.get('wager_rub'))} {currency}\n"
        f"Проиграно: {_profile_money(week.get('loss_rub'))} {currency}\n"
        f"Кешбэк: {week.get('tier', week.get('cashback_percent', '0.00'))}%\n"
        f"Ожидаемый кешбэк: {_profile_money(week.get('estimated_cashback_rub'))} {currency}"
    )
    progress = week.get("progress") if isinstance(week.get("progress"), dict) else {}
    if progress.get("next_threshold_rub") is not None:
        text += (
            f"\nДо следующего уровня: {_profile_money(progress.get('remaining_wager_rub', progress['next_threshold_rub']))} {currency} "
            f"({progress.get('next_cashback_percent', '—')}%)"
        )
    if prior:
        text += (
            "\n\n🧾 <b>Предыдущий кешбэк</b>\n"
            f"За неделю с {prior.get('week_start', '—')}: "
            f"{_profile_money(prior.get('cashback_rub'))} {currency} "
            f"({prior.get('cashback_percent', '0.00')}%, {prior.get('status', '—')})"
        )
    return text


async def _load_profile(telegram_id: int) -> str:
    client = await get_focuspay_client()
    return _profile_text(await client.get_profile(telegram_id))


async def _load_profile_data(telegram_id: int) -> dict:
    client = await get_focuspay_client()
    return await client.get_profile(telegram_id)


def _profile_card_player(profile: Mapping[str, object], fallback_user: object) -> dict:
    identity = profile.get("identity") if isinstance(profile.get("identity"), Mapping) else {}
    week = profile.get("current_week") if isinstance(profile.get("current_week"), Mapping) else {}
    progress = week.get("progress") if isinstance(week.get("progress"), Mapping) else {}
    tier = week.get("tier", week.get("cashback_percent", 0))
    next_percent = progress.get("next_cashback_percent")
    clan = profile.get("clan") if isinstance(profile.get("clan"), Mapping) else None
    name = identity.get("first_name") or getattr(fallback_user, "first_name", "") or "Игрок"
    tag = clan.get("tag") if isinstance(clan, Mapping) else None
    if tag:
        name = f"[{tag}] {name}"
    return {
        "name": name,
        "username": identity.get("username") or getattr(fallback_user, "username", ""),
        "balance_rub": profile.get("available_rub", 0),
        "weekly_bet_turnover_rub": week.get("wager_rub", 0),
        "weekly_eligible_loss_rub": week.get("loss_rub", 0),
        "cashback_level": f"{tier}%",
        "cashback_percent": tier,
        "next_cashback_level": f"{next_percent}%" if next_percent is not None else "максимального уровня",
        "expected_cashback_rub": week.get("estimated_cashback_rub", 0),
        "rollover_remaining_rub": (profile.get("wagering") or {}).get("remaining_rub", 0) if isinstance(profile.get("wagering"), Mapping) else 0,
        "progress_to_next_level": _profile_progress_percent(week),
    }


def _profile_progress_percent(week: Mapping[str, object]) -> float:
    progress = week.get("progress") if isinstance(week.get("progress"), Mapping) else {}
    threshold = progress.get("next_threshold_rub")
    wager = progress.get("wager_rub", week.get("wager_rub"))
    try:
        return max(0.0, min(100.0, float(wager) / float(threshold) * 100))
    except (TypeError, ValueError, ZeroDivisionError):
        return 100.0 if threshold is None else 0.0


async def _render_profile_card(telegram_id: int, profile: dict, fallback_user: object) -> BytesIO:
    from casino_profile_card import render_profile_card

    avatar = None
    try:
        client = await get_focuspay_client()
        avatar = await client.get_profile_avatar(telegram_id)
    except Exception:
        logger.info("Casino profile avatar unavailable for user %s", telegram_id)
    image = render_profile_card(_profile_card_player(profile, fallback_user), avatar_bytes=avatar)
    photo = BytesIO(image)
    photo.name = "focuscasino-profile.png"
    return photo


async def _send_profile_card(chat_id: int, telegram_id: int, fallback_user: object, reply_markup) -> None:
    profile = await _load_profile_data(telegram_id)
    try:
        photo = await _render_profile_card(telegram_id, profile, fallback_user)
        await bot.send_photo(
            chat_id,
            photo,
            caption=CASINO_CARD_CAPTION,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception("Unable to render casino card for %s", telegram_id)
        await bot.send_message(
            chat_id,
            _profile_text(profile),
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


def _start_fallback_text(username: str) -> str:
    return (
        f"🎰 <b>Добро пожаловать в FocusCasino, @{username}!</b>\n\n"
        "Профиль, баланс и кешбэк доступны в личном кабинете."
    )


CASINO_CARD_CAPTION = "🎰 <b>FocusCasino</b>\nВаша статистика на текущую неделю."


async def _send_casino_card(chat_id: int, telegram_id: int, fallback_user: object, reply_markup) -> bool:
    """Единственный баннер бота: карточка профиля игрока.

    И `/start`, и «👤 Профиль» показывают одну и ту же карточку, чтобы в личке
    не было двух разных баннеров. При недоступности рендерера отдаём текст.
    """
    try:
        profile = await _load_profile_data(telegram_id)
    except Exception:
        logger.exception("Unable to load casino profile for %s", telegram_id)
        return False

    try:
        photo = await _render_profile_card(telegram_id, profile, fallback_user)
        await bot.send_photo(
            chat_id,
            photo,
            caption=CASINO_CARD_CAPTION,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception("Unable to render casino card for %s", telegram_id)
        return False
    return True


@bot.message_handler(commands=["start"])
async def start_handler(message):
    """Обработчик команды /start."""
    username = message.from_user.username or "игрок"

    if _is_private(message):
        from games.v2_runtime import extract_blackjack_start_table_id, open_blackjack_dm_table

        client = None
        try:
            client = await get_focuspay_client()
            await client.v2_recovery_or_outbox(
                "/notifications/resume",
                telegram_id=message.from_user.id,
                limit=10,
            )
        except Exception:
            # Opening the bot must still work during a backend outage.  The
            # durable worker will retry notifications once resume succeeds.
            logger.warning(
                "Unable to resume blocked notifications for %s",
                message.from_user.id,
                exc_info=True,
            )

        table_id = extract_blackjack_start_table_id(getattr(message, "text", None))
        if table_id:
            try:
                client = client or await get_focuspay_client()
                await open_blackjack_dm_table(
                    bot,
                    client,
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    table_id=table_id,
                )
            except Exception:
                logger.exception("BJ deep-link open failed table=%s user=%s", table_id, message.from_user.id)
                await bot.send_message(message.chat.id, "Не удалось открыть стол. Попробуйте из «Мои игры».")
            return

        await maybe_send_site_login(bot, message)
        # Карточка несёт reply-меню: постоянные кнопки ставятся сразу, без второго сообщения.
        if await _send_casino_card(
            message.chat.id,
            message.from_user.id,
            message.from_user,
            main_menu_keyboard(),
        ):
            return

        await bot.send_message(
            message.chat.id,
            _start_fallback_text(username),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await send_ephemeral(
            bot,
            message.chat.id,
            "🎰 <b>FocusCasino</b>\n\n"
            "Создание игр, баланс и вывод — в личном чате с ботом.\n"
            "Нажмите «Написать боту» и откройте меню.",
            TTL_SERVICE,
            parse_mode="HTML",
        )
        await try_delete_user_message(bot, message)


@bot.message_handler(commands=["profile"])
async def profile_handler(message):
    """Показать сводный профиль казино только в личке."""
    if getattr(getattr(message, "chat", None), "type", "") != "private":
        await bot.send_message(message.chat.id, "Профиль доступен только в личке с ботом.")
        return
    try:
        await _send_profile_card(
            message.chat.id,
            message.from_user.id,
            message.from_user,
            _profile_keyboard(),
        )
    except Exception:
        logger.exception("Error getting profile for %s", message.from_user.id)
        await bot.send_message(message.chat.id, "❌ Ошибка при получении профиля. Попробуйте позже.")


@bot.callback_query_handler(func=lambda c: c.data == "profile:refresh")
async def profile_refresh_cb(call):
    """Обновить профиль в исходном сообщении только в личке."""
    chat = getattr(getattr(call, "message", None), "chat", None)
    if getattr(chat, "type", "") != "private":
        await bot.answer_callback_query(call.id, "Профиль доступен только в личке", show_alert=True)
        return
    try:
        profile = await _load_profile_data(call.from_user.id)
        photo = await _render_profile_card(call.from_user.id, profile, call.from_user)
        await bot.edit_message_media(
            types.InputMediaPhoto(photo),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_profile_keyboard(),
        )
        await bot.answer_callback_query(call.id, "Профиль обновлён")
    except Exception:
        logger.exception("Error refreshing profile for %s", call.from_user.id)
        await bot.answer_callback_query(call.id, "Не удалось обновить профиль", show_alert=True)


@bot.callback_query_handler(func=lambda c: str(getattr(c, "data", "")).startswith("menu:"))
async def staging_menu_callback(call):
    """Навигация инлайн-хаба под карточкой (личный чат)."""
    if not _is_private(getattr(call, "message", None)):
        await bot.answer_callback_query(call.id, "Откройте личный чат с ботом", show_alert=True)
        return

    action = call.data.removeprefix("menu:")
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    try:
        if action == "profile":
            await _send_profile_card(
                chat_id,
                user_id,
                call.from_user,
                _staging_menu_keyboard(),
            )
        elif action == "balance":
            client = await get_focuspay_client()
            balance = await client.get_balance(telegram_id=user_id)
            hint = await _wagering_hint(client, user_id)
            await bot.send_message(
                chat_id,
                f"💰 Ваш баланс: <b>{balance:.2f} {config.CURRENCY_SYMBOL}</b>{hint}",
                parse_mode="HTML",
                reply_markup=_staging_menu_keyboard(),
            )
        elif action == "deposit":
            await _send_deposit_entry(chat_id)
        elif action == "creategame":
            await start_wizard(bot, await get_focuspay_client(), call.message, user=call.from_user)
        elif action in {"lobby", "games"}:
            await send_v2_lobby(bot, await get_focuspay_client(), chat_id, user_id)
        elif action == "mygames":
            await send_v2_my_tables(bot, await get_focuspay_client(), chat_id, user_id)
        elif action == "withdraw":
            await bot.send_message(
                chat_id,
                _withdraw_text(),
                parse_mode="HTML",
                reply_markup=_staging_menu_keyboard(),
            )
        elif action == "refresh":
            await _send_casino_card(chat_id, user_id, call.from_user, _staging_menu_keyboard())
        else:
            await bot.answer_callback_query(call.id, "Неизвестное действие", show_alert=True)
            return
        await bot.answer_callback_query(call.id)
    except Exception:
        logger.exception("Staging menu action failed action=%s user=%s", action, user_id)
        await bot.answer_callback_query(call.id, "Не удалось выполнить действие", show_alert=True)


@bot.message_handler(commands=["balance"])
async def balance_handler(message):
    """Показать баланс игрока только в личке — в группе сумму не светим."""
    if not _is_private(message):
        await send_ephemeral(
            bot,
            message.chat.id,
            "Баланс доступен только в личке с ботом.",
            TTL_SERVICE,
        )
        await try_delete_user_message(bot, message)
        return
    user_id = message.from_user.id
    
    try:
        client = await get_focuspay_client()
        balance = await client.get_balance(telegram_id=user_id)
        hint = await _wagering_hint(client, user_id)

        await bot.send_message(
            message.chat.id,
            f"💰 Ваш баланс: {balance:.2f} {config.CURRENCY_SYMBOL}{hint}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("Error getting balance for %s", user_id)
        await bot.send_message(
            message.chat.id,
            "❌ Ошибка при получении баланса. Попробуйте позже."
        )


@bot.message_handler(commands=["help"])
async def help_handler(message):
    """Оглавление и темы /help roulette, /help cub, …"""
    try:
        client = await get_focuspay_client()
        settings = await client.get_casino_settings()
    except Exception:
        logger.exception("help: casino settings unavailable")
        settings = {}
    help_text = render_help(settings, getattr(message, "text", "") or "")
    await send_ephemeral(bot, message.chat.id, help_text, TTL_HELP, parse_mode="HTML")
    await try_delete_user_message(bot, message)


def _format_deposit_requisites(deal: dict) -> str | None:
    """Собрать блок реквизитов из bill заявки (как в боте обмена)."""
    payment = deal.get("payment") if isinstance(deal.get("payment"), dict) else {}
    bill = deal.get("bill") if isinstance(deal.get("bill"), dict) else {}
    if not bill and isinstance(payment, dict):
        bill = payment.get("bill") if isinstance(payment.get("bill"), dict) else {}
    if not bill:
        return None
    bank = str(bill.get("bank") or "—")
    reciver = str(bill.get("reciver") or "—")
    fio = str(bill.get("fio") or "—")
    return (
        "💳 <b>Реквизиты для пополнения:</b>\n"
        f"Банк: {bank}\n"
        f"Получатель: <code>{reciver}</code>\n"
        f"ФИО: {fio}"
    )


# Ожидающие выбора способа оплаты: user_id -> целевая сумма кредита (₽).
_pending_deposit_credit: dict[int, float] = {}


def _deposit_charged(credit_rub: float) -> float:
    """Сумма к оплате по реквизитам с учётом наценки (как спред обменника)."""
    return round(credit_rub * (1.0 + config.DEPOSIT_COMMISSION_PERCENT / 100.0), 2)


async def _wagering_hint(client, telegram_id: int) -> str:
    """Получить актуальный остаток отыгрыша для пользовательского сообщения."""
    try:
        data = await client.get_wagering(telegram_id)
    except Exception:
        logger.debug("Wagering progress unavailable for %s", telegram_id, exc_info=True)
        return ""
    return wagering_hint(data, currency_symbol=config.CURRENCY_SYMBOL)


def _withdraw_text() -> str:
    """Вывод идёт через основной бот FocusPay: у казино нет своего payout-API."""
    return (
        "🏧 <b>Вывод средств</b>\n\n"
        "Баланс казино и баланс FocusPay — единый кошелёк, поэтому вывод оформляется "
        "в основном боте FocusPay, раздел «Вывод».\n\n"
        "Перед выводом нужно закрыть отыгрыш: казино должно получить свой плюс комиссией "
        "с ваших ставок. Сколько ещё поставить — в «💰 Баланс» и в профиле. "
        "Пока отыгрыш не закрыт, средства доступны только для игр."
    )


def _deposit_method_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        *[
            types.InlineKeyboardButton(name, callback_data=f"dep:pay:{token}")
            for token, name in config.DEPOSIT_METHODS.items()
        ]
    )
    kb.add(types.InlineKeyboardButton("✖️ Отмена", callback_data="dep:cancel"))
    return kb


# Пресеты пополнения; фильтруем по лимитам, чтобы не предлагать недопустимую сумму.
DEPOSIT_PRESETS_RUB = (500, 1000, 2000, 5000, 10000, 25000)


def _deposit_presets() -> tuple[int, ...]:
    return tuple(
        amount
        for amount in DEPOSIT_PRESETS_RUB
        if config.DEPOSIT_MIN_RUB <= amount <= config.DEPOSIT_MAX_RUB
    )


def _deposits_enabled() -> bool:
    return bool(getattr(config, "DEPOSITS_ENABLED", False))


DEPOSIT_SOON_TEXT = (
    "💳 <b>Пополнение</b>\n\n"
    "Пополнение скоро. Сейчас на баланс попадают призы FocusLucky, кешбэк и рефералка. "
    "Вывести уже можно."
)


def _clear_deposit_draft(user_id: int) -> None:
    _pending_deposit_credit.pop(user_id, None)
    _awaiting_deposit_amount.pop(user_id, None)


async def _send_deposit_entry(chat_id: int) -> None:
    if not _deposits_enabled():
        await bot.send_message(chat_id, DEPOSIT_SOON_TEXT, parse_mode="HTML")
        return
    await bot.send_message(
        chat_id,
        _deposit_prompt_text(),
        parse_mode="HTML",
        reply_markup=_deposit_amount_keyboard(),
    )


async def _reject_disabled_deposit(call) -> bool:
    """True if self-serve deposits are off and the callback should stop."""
    if _deposits_enabled():
        return False
    _clear_deposit_draft(call.from_user.id)
    await bot.answer_callback_query(call.id, "Пополнение скоро", show_alert=True)
    return True


def _deposit_prompt_text() -> str:
    rules = deposit_wagering_rules(
        wagering_percent=config.WAGERING_PERCENT,
        commission_percent=config.COMMISSION_RATE_WAGERING_ACTIVE,
        currency_symbol=config.CURRENCY_SYMBOL,
    )
    return (
        "💳 <b>Пополнение баланса</b>\n\n"
        f"Лимиты: {config.DEPOSIT_MIN_RUB:.0f}–{config.DEPOSIT_MAX_RUB:.0f} {config.CURRENCY_SYMBOL}.\n"
        "Зачисляем ровно сумму пополнения, без комиссии.\n"
        f"{rules}\n\n"
        "Выберите сумму или введите свою."
    )


def _deposit_amount_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        *[
            types.InlineKeyboardButton(
                f"{amount:,}".replace(",", " ") + f" {config.CURRENCY_SYMBOL}",
                callback_data=f"depamt:{amount}",
            )
            for amount in _deposit_presets()
        ]
    )
    kb.add(types.InlineKeyboardButton("✏️ Своя сумма", callback_data="depamt:custom"))
    kb.add(types.InlineKeyboardButton("✖️ Отмена", callback_data="dep:cancel"))
    return kb


# Кто вводит свою сумму пополнения текстом: user_id -> True
_awaiting_deposit_amount: dict[int, bool] = {}


async def _offer_deposit_methods(chat_id: int, user_id: int, credit: float) -> None:
    """Общий шаг 2 пополнения: зафиксировать сумму и предложить способ оплаты."""
    if not _deposits_enabled():
        _clear_deposit_draft(user_id)
        await bot.send_message(chat_id, DEPOSIT_SOON_TEXT, parse_mode="HTML")
        return
    credit = round(credit, 2)
    _pending_deposit_credit[user_id] = credit
    charged = _deposit_charged(credit)
    commission_line = ""
    if charged > credit:
        commission_line = (
            f"Комиссия {config.DEPOSIT_COMMISSION_PERCENT:.0f}%: "
            f"{charged - credit:.2f} {config.CURRENCY_SYMBOL}\n"
        )
    await bot.send_message(
        chat_id,
        f"💳 Пополнение на <b>{credit:.2f} {config.CURRENCY_SYMBOL}</b>\n"
        f"{commission_line}"
        f"К оплате: <b>{charged:.2f} {config.CURRENCY_SYMBOL}</b>\n\n"
        "После зачисления средства доступны в играх. Для вывода потребуется отыграть "
        f"<b>{credit * 0.21:.2f} {config.CURRENCY_SYMBOL}</b> (21% суммы пополнения).\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=_deposit_method_keyboard(),
    )


def _validate_deposit_amount(raw: str) -> tuple[float | None, str | None]:
    """Разобрать сумму пополнения. Возвращает (сумма, текст ошибки)."""
    try:
        credit = float(raw.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None, "❌ Сумма должна быть числом, например 1000."
    if not math.isfinite(credit) or credit < config.DEPOSIT_MIN_RUB:
        return None, (
            f"❌ Минимальная сумма пополнения — {config.DEPOSIT_MIN_RUB:.0f} {config.CURRENCY_SYMBOL}."
        )
    if credit > config.DEPOSIT_MAX_RUB:
        return None, (
            f"❌ Максимальная сумма пополнения — {config.DEPOSIT_MAX_RUB:.0f} {config.CURRENCY_SYMBOL}."
        )
    return round(credit, 2), None


@bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("depamt:"))
async def deposit_amount_cb(call):
    """Шаг 1 пополнения кнопками: пресет суммы или переход к ручному вводу."""
    if await _reject_disabled_deposit(call):
        return
    if not _is_private(getattr(call, "message", None)):
        await bot.answer_callback_query(call.id, "Пополнение доступно только в личке", show_alert=True)
        return

    user_id = call.from_user.id
    raw = call.data.split(":", 1)[1]

    if raw == "custom":
        _awaiting_deposit_amount[user_id] = True
        await bot.answer_callback_query(call.id)
        await bot.send_message(
            call.message.chat.id,
            "✏️ Отправьте сумму пополнения одним сообщением, например <code>1500</code>.",
            parse_mode="HTML",
        )
        return

    credit, error = _validate_deposit_amount(raw)
    if error:
        await bot.answer_callback_query(call.id, error[:200], show_alert=True)
        return
    _awaiting_deposit_amount.pop(user_id, None)
    await bot.answer_callback_query(call.id)
    await _offer_deposit_methods(call.message.chat.id, user_id, credit)


@bot.message_handler(commands=["deposit"])
async def deposit_handler(message):
    """Шаг 1: сумма пополнения. Реквизиты выдаём только в личке."""
    if not _deposits_enabled():
        await send_ephemeral(bot, message.chat.id, DEPOSIT_SOON_TEXT, TTL_SERVICE, parse_mode="HTML")
        await try_delete_user_message(bot, message)
        return
    user_id = message.from_user.id
    if getattr(getattr(message, "chat", None), "type", "") != "private":
        await send_ephemeral(
            bot,
            message.chat.id,
            "💳 Пополнение доступно только в личке с ботом. "
            f"Напишите мне в ЛС: @{config.BOT_USERNAME} и откройте «💳 Пополнить».",
            TTL_SERVICE,
        )
        await try_delete_user_message(bot, message)
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await bot.send_message(
            message.chat.id,
            _deposit_prompt_text(),
            parse_mode="HTML",
            reply_markup=_deposit_amount_keyboard(),
        )
        return

    credit, error = _validate_deposit_amount(parts[1])
    if error:
        await bot.send_message(message.chat.id, error)
        return

    _awaiting_deposit_amount.pop(user_id, None)
    await _offer_deposit_methods(message.chat.id, user_id, credit)


@bot.callback_query_handler(func=lambda c: c.data == "dep:cancel")
async def deposit_cancel_cb(call):
    _pending_deposit_credit.pop(call.from_user.id, None)
    with contextlib.suppress(Exception):
        await bot.edit_message_text(
            "Пополнение отменено.", call.message.chat.id, call.message.message_id
        )
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("dep:pay:"))
async def deposit_pay_cb(call):
    """Шаг 2: выбран способ оплаты — создаём заявку и выдаём реквизиты с таймером."""
    if await _reject_disabled_deposit(call):
        return
    user_id = call.from_user.id
    sub_token = call.data.split(":", 2)[2]
    if sub_token not in config.DEPOSIT_METHODS:
        await bot.answer_callback_query(call.id, "Неизвестный способ оплаты.", show_alert=True)
        return
    credit = _pending_deposit_credit.pop(user_id, None)
    if credit is None:
        await bot.answer_callback_query(call.id, "Заявка устарела, начните с /deposit заново.", show_alert=True)
        return

    try:
        client = await get_focuspay_client()
        deal = await client.create_deposit(
            telegram_id=user_id,
            credit_rub=credit,
            callback_url=config.WEBHOOK_URL,
            sub_token=sub_token,
            commission_pct=config.DEPOSIT_COMMISSION_PERCENT,
        )
    except Exception:
        logger.exception("Deposit request failed for %s", user_id)
        await bot.answer_callback_query(
            call.id,
            "❌ Не удалось создать заявку на пополнение. Попробуйте позже или обратитесь в поддержку.",
            show_alert=True,
        )
        return

    await bot.answer_callback_query(call.id)
    with contextlib.suppress(Exception):
        await bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    deal_id = deal.get("deal_id") or deal.get("id")
    charged = _deposit_charged(credit)
    requisites = _format_deposit_requisites(deal)
    method_name = config.DEPOSIT_METHODS[sub_token]
    if charged > credit:
        amount_lines = (
            f"На баланс: <b>{credit:.2f} {config.CURRENCY_SYMBOL}</b>\n"
            f"К оплате ({method_name}): <b>{charged:.2f} {config.CURRENCY_SYMBOL}</b>\n"
        )
    else:
        amount_lines = (
            f"К оплате ({method_name}): <b>{charged:.2f} {config.CURRENCY_SYMBOL}</b>\n"
        )
    header = (
        f"✅ Заявка на пополнение #{deal_id} создана.\n"
        f"{amount_lines}"
        f"⏳ Оплатите в течение {config.DEPOSIT_WINDOW_MINUTES} минут — иначе реквизиты сгорят.\n\n"
    )
    cancel_kb = None
    if deal_id is not None:
        cancel_kb = types.InlineKeyboardMarkup()
        cancel_kb.add(
            types.InlineKeyboardButton(
                "❌ Отменить заявку", callback_data=f"dep:cxl:{deal_id}"
            )
        )
    if requisites:
        await bot.send_message(
            call.message.chat.id,
            header + requisites + "\n\n"
            "Переводите <b>точную сумму</b> к оплате. После зачисления баланс "
            "обновится автоматически. Вопросы — @focuspay_support.",
            parse_mode="HTML",
            reply_markup=cancel_kb,
        )
    else:
        await bot.send_message(
            call.message.chat.id,
            header + "Реквизиты формируются, оператор FocusGame пришлёт их отдельно. "
            "Если долго нет ответа — напишите @focuspay_support.",
            parse_mode="HTML",
            reply_markup=cancel_kb,
        )


@bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("dep:cxl:"))
async def deposit_request_cancel_cb(call):
    """Отменить уже созданную заявку на пополнение (пока она не оплачена)."""
    user_id = call.from_user.id
    try:
        deal_id = int(call.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await bot.answer_callback_query(call.id, "Некорректная заявка.", show_alert=True)
        return

    try:
        client = await get_focuspay_client()
        await client.cancel_deposit(deal_id=deal_id, telegram_id=user_id)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 409:
            with contextlib.suppress(Exception):
                await bot.edit_message_reply_markup(
                    call.message.chat.id, call.message.message_id, reply_markup=None
                )
            await bot.answer_callback_query(
                call.id,
                "Эту заявку уже нельзя отменить — платёж получен или зачислен. "
                "Если это ошибка, напишите @focuspay_support.",
                show_alert=True,
            )
            return
        logger.exception("Deposit cancel failed for %s deal=%s", user_id, deal_id)
        await bot.answer_callback_query(
            call.id,
            "❌ Не удалось отменить заявку. Попробуйте позже или напишите @focuspay_support.",
            show_alert=True,
        )
        return
    except Exception:
        logger.exception("Deposit cancel failed for %s deal=%s", user_id, deal_id)
        await bot.answer_callback_query(
            call.id,
            "❌ Не удалось отменить заявку. Попробуйте позже или напишите @focuspay_support.",
            show_alert=True,
        )
        return

    with contextlib.suppress(Exception):
        await bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id, reply_markup=None
        )
    await bot.answer_callback_query(call.id, "✅ Заявка на пополнение отменена.", show_alert=True)


# ============================================================================
# REPLY KEYBOARD BUTTON HANDLERS
# ============================================================================


@bot.message_handler(func=lambda m: m.text == MENU_CREATE_GAME and _is_private(m))
async def menu_create_game_handler(message):
    """Обработчик кнопки '🎮 Создать игру' → единый мастер стола."""
    await start_wizard(bot, await get_focuspay_client(), message)


@bot.message_handler(func=lambda m: m.text == MENU_FIND_GAME and _is_private(m))
async def menu_find_game_handler(message):
    """Кнопка «Активные игры» показывает durable V2-лобби."""
    try:
        await send_v2_lobby(bot, await get_focuspay_client(), message.chat.id, message.from_user.id)
    except Exception:
        logger.exception("Failed to load V2 lobby for user=%s", message.from_user.id)
        await bot.send_message(message.chat.id, "❌ Не удалось загрузить лобби. Попробуйте позже.")


@bot.message_handler(func=lambda m: m.text == MENU_MY_GAMES and _is_private(m))
async def menu_my_games_handler(message):
    """Кнопка «Мои игры» показывает durable V2-столы пользователя."""
    try:
        await send_v2_my_tables(bot, await get_focuspay_client(), message.chat.id, message.from_user.id)
    except Exception:
        logger.exception("Failed to load V2 tables for user=%s", message.from_user.id)
        await bot.send_message(message.chat.id, "❌ Не удалось загрузить ваши игры. Попробуйте позже.")


@bot.message_handler(func=lambda m: m.text == MENU_PROFILE and _is_private(m))
async def menu_profile_handler(message):
    """Обработчик кнопки '👤 Профиль' → отправляет карточку профиля."""
    try:
        await _send_profile_card(
            message.chat.id,
            message.from_user.id,
            message.from_user,
            main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error getting profile for %s", message.from_user.id)
        await bot.send_message(
            message.chat.id,
            "❌ Ошибка при получении профиля. Попробуйте позже.",
            reply_markup=main_menu_keyboard(),
        )


@bot.message_handler(func=lambda m: m.text == MENU_BALANCE and _is_private(m))
async def menu_balance_handler(message):
    """Обработчик кнопки '💰 Баланс' → показывает баланс."""
    user_id = message.from_user.id
    try:
        client = await get_focuspay_client()
        balance = await client.get_balance(telegram_id=user_id)
        hint = await _wagering_hint(client, user_id)
        
        await bot.send_message(
            message.chat.id,
            f"💰 Ваш баланс: <b>{balance:.2f} {config.CURRENCY_SYMBOL}</b>{hint}",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("Error getting balance for %s", user_id)
        await bot.send_message(
            message.chat.id,
            "❌ Ошибка при получении баланса. Попробуйте позже.",
            reply_markup=main_menu_keyboard(),
        )


@bot.message_handler(func=lambda m: m.text == MENU_DEPOSIT and _is_private(m))
async def menu_deposit_handler(message):
    """Кнопка '💳 Пополнить' → выбор суммы кнопками."""
    await _send_deposit_entry(message.chat.id)


# ============================================================================
# DEPOSIT CUSTOM AMOUNT
# ============================================================================

@bot.message_handler(
    func=lambda m: _is_private(m)
    and isinstance(getattr(m, "text", None), str)
    and not m.text.startswith("/")
    and _awaiting_deposit_amount.get(getattr(m.from_user, "id", 0))
)
async def custom_amount_input_handler(message):
    """Ручной ввод суммы пополнения."""
    user_id = message.from_user.id
    if not _deposits_enabled():
        _clear_deposit_draft(user_id)
        await bot.send_message(message.chat.id, DEPOSIT_SOON_TEXT, parse_mode="HTML")
        return
    raw = (message.text or "").strip()
    credit, error = _validate_deposit_amount(raw)
    if error:
        await bot.send_message(message.chat.id, error)
        return
    _awaiting_deposit_amount.pop(user_id, None)
    await _offer_deposit_methods(message.chat.id, user_id, credit)


# ============================================================================
# ADMIN COMMANDS
# ============================================================================

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом."""
    return user_id in config.ADMIN_IDS


@bot.message_handler(commands=["admin"])
async def admin_handler(message):
    """Админ-панель."""
    if not is_admin(message.from_user.id):
        return
    
    await bot.send_message(
        message.chat.id,
        "🔧 <b>Админ-панель</b>\n\n"
        "Используйте веб-интерфейс для управления казино:\n"
        "https://focuspay.org/x8/casino",
        parse_mode="HTML"
    )


@bot.message_handler(commands=["bindgamechat"])
async def bind_game_chat_handler(message):
    """Request administrative approval for this group as the PVP game chat."""
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    if not chat or getattr(chat, "type", None) not in {"group", "supergroup"}:
        await bot.send_message(message.chat.id, "Эта команда доступна только в группе.")
        return
    if not user or not is_admin(user.id):
        return

    text_parts = (getattr(message, "text", "") or "").split(maxsplit=1)
    if len(text_parts) != 2:
        await bot.send_message(chat.id, "Использование: /bindgamechat https://t.me/ссылка_на_чат")
        return
    telegram_url = text_parts[1].strip()

    try:
        bot_identity = await bot.get_me()
        membership = await bot.get_chat_member(chat.id, bot_identity.id)
        if getattr(membership, "status", None) not in {"administrator", "creator", "owner"}:
            await bot.send_message(chat.id, "Боту нужны права администратора в этой группе.")
            return

        client = await get_focuspay_client()
        await client.create_pending_game_chat_binding(
            chat_id=chat.id,
            chat_type=chat.type,
            chat_title=getattr(chat, "title", None),
            telegram_url=telegram_url,
            requested_by_telegram_id=user.id,
        )
        await bot.send_message(
            chat.id,
            "Запрос на привязку игрового чата отправлен. Подтвердите его в админ-панели FocusPay.",
        )
    except Exception:
        logger.exception("Failed to request game chat binding for chat %s", chat.id)
        await bot.send_message(chat.id, "Не удалось отправить запрос на привязку. Попробуйте позже.")


# ============================================================================
# ERROR HANDLER
# ============================================================================

def _is_unknown_command(message) -> bool:
    """Match only private slash-commands so ordinary group chatter is left alone."""
    if not _is_private(message):
        return False
    text = getattr(message, "text", None)
    return isinstance(text, str) and text.startswith("/")


async def catch_all(message):
    """Обработчик неизвестных команд."""
    await send_ephemeral(
        bot,
        message.chat.id,
        "❓ Неизвестная команда. Используйте /help для списка команд.",
        TTL_SERVICE,
    )
    await try_delete_user_message(bot, message)


# ============================================================================
# MAIN
# ============================================================================

def _required_setting_number(settings: dict, key: str) -> float:
    if key not in settings:
        raise ValueError(f"Casino settings response is missing {key}")
    try:
        value = float(settings[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Casino setting {key} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"Casino setting {key} must be finite")
    return value


async def load_casino_settings(client) -> dict:
    """Load and validate required remote settings before accepting traffic."""
    settings = await client.get_casino_settings()
    if not isinstance(settings, dict):
        raise ValueError("Casino settings response must be an object")

    commission_rate = _required_setting_number(settings, "commission_rate_wagering_active")
    commission_complete = _required_setting_number(settings, "commission_rate_wagering_complete")
    wagering_percent = _required_setting_number(settings, "wagering_percent")
    min_bet = _required_setting_number(settings, "min_bet_rub")
    max_bet = _required_setting_number(settings, "max_bet_rub")
    if not 0 <= commission_rate <= 100:
        raise ValueError("Casino commission_rate_wagering_active must be between 0 and 100")
    if not 0 <= commission_complete <= 100:
        raise ValueError("Casino commission_rate_wagering_complete must be between 0 and 100")
    if not 0 <= wagering_percent <= 100:
        raise ValueError("Casino wagering_percent must be between 0 and 100")
    if min_bet <= 0 or max_bet < min_bet:
        raise ValueError("Casino bet limits are invalid")

    config.COMMISSION_RATE = commission_rate
    config.COMMISSION_RATE_WAGERING_ACTIVE = commission_rate
    config.COMMISSION_RATE_WAGERING_COMPLETE = commission_complete
    config.WAGERING_PERCENT = wagering_percent
    config.MIN_BET = min_bet
    config.MAX_BET = max_bet
    logger.info("Casino settings loaded: %s", settings.keys())
    return settings


async def configure_telegram_command_menu(enabled_games: object) -> None:
    """Replace stale Telegram commands with the games enabled by backend policy."""
    enabled = enabled_games if isinstance(enabled_games, dict) else {}
    commands = [types.BotCommand("newgame", "Создать игровой стол")]
    if enabled.get("pvp_dice"):
        commands.extend((
            types.BotCommand("cub", "Кубики — один бросок"),
            types.BotCommand("2cub", "Кубики — два броска"),
        ))
    if enabled.get("baccara"):
        commands.append(types.BotCommand("baccara", "Создать стол баккары"))
    if enabled.get("blackjack"):
        commands.append(types.BotCommand("blackjack", "Создать стол блэкджека"))
    if enabled.get("roulette"):
        commands.append(types.BotCommand("roulette", "Открыть рулетку"))
    if enabled.get("jackpot"):
        commands.append(types.BotCommand("jackpot", "Открыть Jackpot"))
    if enabled.get("fixed_room"):
        commands.append(types.BotCommand("rooms", "Открыть игровые комнаты"))
    commands.append(types.BotCommand("allgames", "Все активные игры"))
    scopes = (
        None,
        types.BotCommandScopeAllPrivateChats(),
        types.BotCommandScopeAllGroupChats(),
        types.BotCommandScopeAllChatAdministrators(),
    )
    for scope in scopes:
        try:
            if scope is None:
                await bot.set_my_commands(commands)
            else:
                await bot.set_my_commands(commands, scope=scope)
        except Exception:
            logger.exception("Unable to configure Telegram slash menu for scope %s", scope)


async def main():
    """Start only after settings and a bounded durable recovery pass succeed."""
    logger.info("Starting FocusCasino bot...")
    logger.info("Bot username: @%s", config.BOT_USERNAME)

    # Raffle has no trusted atomic settlement contract. Keep it disabled even
    # if a legacy environment value attempts to enable it.
    config.RAFFLE_ENABLED = False

    worker_id = default_worker_id()
    try:
        client = await get_focuspay_client()
        casino_settings = await load_casino_settings(client)
        await run_recovery_pass(client, worker_id=worker_id)
        await hydrate_active_pvp_games(client)
        await hydrate_waiting_card_games(
            client,
            modules={"baccara": baccara_mod, "blackjack": blackjack_mod},
        )
    except Exception:
        logger.exception("Casino startup aborted: settings or recovery unavailable")
        await close_focuspay_client()
        raise

    try:
        restored = await hydrate_live_table_cards(bot, client)
        if restored:
            logger.info("Hydrated %s live table card(s)", restored)
    except Exception:
        logger.exception("Live table card hydrate failed")

    background_tasks: list[asyncio.Task] = []
    try:
        # All game entry points query this binding at action time. Register the
        # handlers even without a current binding so a later approval takes
        # effect without a bot restart; the shared guard remains fail-closed.
        register_pvp_handlers(bot, client)
        register_v2_table_handlers(bot, client)
        register_v2_runtime_handlers(bot, client)
        logger.info("PVP, V2 table, and wizard handlers registered with active-chat guard")

        # Зарегистрировать обработчики игр
        register_baccara_handlers(bot, client)
        logger.info("Baccara game handlers registered")

        register_blackjack_handlers(bot, client)
        logger.info("Blackjack game handlers registered")

        register_roulette_table_handlers(bot, client)
        logger.info("Roulette table handlers registered")

        register_jackpot_handlers(bot, client)
        logger.info("Jackpot handlers registered")

        from games.rooms import register_rooms_handlers

        register_rooms_handlers(bot, client)
        logger.info("Fixed-room handlers registered")

        register_fairness_handlers(bot, client)
        logger.info("Fairness handlers registered")

        # catch_all must be registered LAST: pyTelegramBotAPI matches handlers in
        # registration order, so registering it here (after all game handlers)
        # keeps it from swallowing /cub, /2cub, /baccara, /blackjack, /jackpot, /rooms, etc.
        bot.register_message_handler(catch_all, func=_is_unknown_command)
        logger.info("Fallback unknown-command handler registered last")

        # Raffle deliberately stays disabled until it has an atomic durable flow,
        # regardless of legacy configuration.
        logger.warning("Raffle is disabled: atomic raffle settlement is not implemented")

        # Запустить фоновые очистители и durable recovery/outbox worker.
        background_tasks.extend(
            [
                asyncio.create_task(baccara_cleaner(bot, client)),
                asyncio.create_task(blackjack_cleaner(bot, client)),
                asyncio.create_task(recovery_outbox_loop(bot, client, worker_id=worker_id)),
                asyncio.create_task(pvp_invitation_loop(bot, client, worker_id=worker_id)),
                asyncio.create_task(reaper_loop(bot)),
            ]
        )
        logger.info("Background cleaners and recovery worker started")

        from telegram_reliability import install_telegram_guards
        install_telegram_guards(bot, client)

        await configure_telegram_command_menu(casino_settings.get("enabled_games"))
        logger.info("Telegram slash command menu configured")

        # Запустить polling
        await bot.infinity_polling()
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            if inspect.isawaitable(task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await drain_ready_watchers()
        await drain_drama()
        await close_focuspay_client()


if __name__ == "__main__":
    asyncio.run(main())

"""Хаб «Профиль» (карточка + inline) и «О нас»."""

from __future__ import annotations

import asyncio
import io
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from handlers.telegram_errors import answer_callback_safe
from services.antispam import rate_limit_ok
from handlers.telegram_utils import url_button
from services.config_rates import community_chat_url, reviews_channel_url
from services.partner_db import get_partner_by_telegram
from services.profile_card import browser_available, render_profile_card
from services.support_urls import support_chat_url
from services.tg_emoji import e
from services.user_unified_balance import get_unified_balance_stats

logger = logging.getLogger(__name__)

# Кэш аватарок и готовых file_id карточек
_avatar_cache: dict[int, bytes | None] = {}
_card_file_id: dict[str, str] = {}

HUB_CB_PREFIX = "hub:"
PROFILE_CB_DATA = "hub:profile"
PROFILE_FAIL_TEXT = (
    "Не удалось открыть профиль. Нажмите «Профиль» ещё раз или /start."
)


def _fmt_rub(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ")


async def _user_tickets(user_id: int) -> int:
    try:
        from services.db import get_pool
        from services.raffle_db import get_campaign_for_user, get_participant

        campaign = await get_campaign_for_user(user_id)
        if not campaign:
            return 0
        pool = await get_pool()
        async with pool.acquire() as conn:
            p = await get_participant(int(campaign["id"]), user_id, conn)
        return int(p["tickets_total"]) if p else 0
    except Exception:
        logger.exception("tickets fetch failed for %s", user_id)
        return 0


async def _fetch_avatar(bot, user_id: int | None) -> bytes | None:
    if not user_id:
        return None
    if user_id in _avatar_cache:
        return _avatar_cache[user_id]
    data: bytes | None = None
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count and photos.photos:
            from services.receipts_storage import download_telegram_file_bytes

            file_id = photos.photos[0][-1].file_id
            data = await download_telegram_file_bytes(bot, file_id, read_timeout=20.0)
    except Exception as ex:
        logger.info("avatar fetch failed for %s: %s", user_id, ex)
    _avatar_cache[user_id] = data
    return data


def _card_signature(u: dict, has_avatar: bool) -> str:
    return "|".join(
        str(x)
        for x in (
            has_avatar,
            u.get("name"),
            u.get("user_id"),
            u.get("balance"),
            u.get("cashback_percent"),
            u.get("tickets"),
            u.get("deals_done"),
        )
    )


async def _build_card_user(tg_user) -> dict:
    stats = await get_unified_balance_stats(tg_user.id)
    tickets = await _user_tickets(tg_user.id)
    name = (
        tg_user.full_name
        or tg_user.first_name
        or tg_user.username
        or "Пользователь"
    )
    return {
        "name": name,
        "user_id": tg_user.id,
        "balance": float(stats.get("balance_rub") or 0),
        "cashback": float(stats.get("exchange_cashback_rub") or 0),
        "referral": float(stats.get("referral_rub") or 0),
        "cashback_percent": stats.get("percent", 5),
        "tickets": tickets,
        "deals_done": int(stats.get("completed_exchanges") or 0),
        "available_rub": float(stats.get("available_rub") or 0),
    }


def _profile_caption(u: dict) -> str:
    from services.ux_copy import txt_profile_caption

    return txt_profile_caption(u)


def _about_text() -> str:
    return (
        f"{e('info')} <b>О FocusPay</b>\n\n"
        f"Надёжный криптообменник. Быстрый и безопасный обмен "
        f"<b>BTC, USDT, LTC, TRX</b> в рубли и обратно.\n\n"
        f"{e('support')} Поддержка: чат на сайте или @focus_operator\n"
        f"{e('chat')} Общий чат и {e('announce')} отзывы — кнопки ниже.\n"
        f"{e('internet')} Сайт: focuspay.org"
    )


async def _profile_keyboard(user_id: int, username: str | None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("💸 Вывести", callback_data="uref:withdraw"),
            InlineKeyboardButton("🔽 Списать при обмене", callback_data="cashback:toggle"),
        ],
        [
            InlineKeyboardButton("👥 Реф. программа", callback_data="hub:ref"),
            InlineKeyboardButton("🍀 FocusLucky", callback_data="hub:lucky"),
        ],
        [
            InlineKeyboardButton("🎁 Промокод", callback_data="hub:promo"),
            InlineKeyboardButton("🏷 Скидки", callback_data="hub:discounts"),
        ],
        [
            InlineKeyboardButton("📚 История", callback_data="hub:history"),
            InlineKeyboardButton("💳 Баланс", callback_data="hub:balance"),
        ],
        [InlineKeyboardButton("🔄 Обновить профиль", callback_data=PROFILE_CB_DATA)],
    ]
    partner = await get_partner_by_telegram(user_id, username)
    if partner:
        rows.append(
            [InlineKeyboardButton("📊 Партнёрский кабинет", callback_data="hub:partner")]
        )
    return InlineKeyboardMarkup(rows)


def _about_keyboard() -> InlineKeyboardMarkup:
    from services import config_rates

    site = (getattr(config_rates, "PUBLIC_SITE_URL", None) or "https://focuspay.org").rstrip(
        "/"
    )
    row_support = [
        btn
        for btn in (
            url_button("💬 Поддержка", support_chat_url()),
            url_button("👥 Чат", community_chat_url()),
        )
        if btn
    ]
    row_site = [
        btn
        for btn in (
            url_button("📢 Отзывы", reviews_channel_url()),
            url_button("🌐 Сайт", site),
        )
        if btn
    ]
    rows = []
    if row_support:
        rows.append(row_support)
    if row_site:
        rows.append(row_site)
    rows.append([InlineKeyboardButton("💰 Курсы", callback_data="hub:rates")])
    return InlineKeyboardMarkup(rows)


async def _send_text_profile(message, u: dict, markup: InlineKeyboardMarkup) -> None:
    """Фолбэк без картинки, если Chromium недоступен."""
    await message.reply_text(
        _profile_caption(u),
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def _deliver_profile(message, context: ContextTypes.DEFAULT_TYPE, user) -> None:
    from services.user_referral_attribution import seal_referral_gate

    await seal_referral_gate(user.id)
    u = await _build_card_user(user)
    markup = await _profile_keyboard(user.id, user.username)
    caption = _profile_caption(u)

    if not browser_available():
        await _send_text_profile(message, u, markup)
        return

    avatar = await _fetch_avatar(context.bot, user.id)
    sig = _card_signature(u, avatar is not None)
    cached = _card_file_id.get(sig)

    try:
        if cached:
            photo = cached
        else:
            chat_id = message.chat.id if message and message.chat else user.id
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
            png = await asyncio.wait_for(
                asyncio.to_thread(render_profile_card, u, avatar),
                timeout=35,
            )
            photo = InputFile(io.BytesIO(png), filename="profile.png")

        sent = await message.reply_photo(
            photo=photo,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        if sent.photo and not cached:
            _card_file_id[sig] = sent.photo[-1].file_id
    except Exception:
        logger.exception("profile card render/send failed for %s", user.id)
        await _send_text_profile(message, u, markup)


async def profile_hub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    user = update.effective_user
    if not user:
        return

    try:
        if update.effective_chat:
            await context.bot.send_chat_action(
                update.effective_chat.id, ChatAction.TYPING
            )
        await _deliver_profile(update.message, context, user)
    except Exception:
        logger.exception("profile hub failed for %s", user.id)
        try:
            from services.menu import main_menu_keyboard

            await update.message.reply_text(
                PROFILE_FAIL_TEXT,
                reply_markup=await main_menu_keyboard(user.id, user.username),
            )
        except Exception:
            logger.exception("profile hub fallback reply failed for %s", user.id)


async def about_hub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not await rate_limit_ok(update):
        return
    await update.message.reply_text(
        _about_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=_about_keyboard(),
        disable_web_page_preview=True,
    )


async def hub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline-разделы из профиля / «О нас»."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith(HUB_CB_PREFIX):
        return
    # Сначала закрываем spinner — иначе Telegram крутит загрузку до таймаута.
    await answer_callback_safe(query)
    if not await rate_limit_ok(update):
        return

    action = query.data[len(HUB_CB_PREFIX) :]
    msg = query.message
    user = query.from_user
    try:
        await _hub_callback_body(update, context, query, action, msg, user)
    except Exception:
        logger.exception("hub_callback failed action=%s user=%s", action, getattr(user, "id", None))
        if msg:
            try:
                await msg.reply_text(PROFILE_FAIL_TEXT)
            except Exception:
                logger.exception("hub_callback error reply failed")


async def _hub_callback_body(update, context, query, action, msg, user):
    if action == "profile":
        if not msg or not user:
            return
        await _deliver_profile(msg, context, user)
        return

    if action == "ref":
        from services.user_referral_db import format_referral_cabinet_message

        text = await format_referral_cabinet_message(user.id, user.username)
        await msg.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💸 Вывести средства", callback_data="uref:withdraw")],
                    [InlineKeyboardButton("📜 История", callback_data="uref:history")],
                ]
            ),
        )
        return

    if action == "lucky":
        from handlers.focus_lucky import focus_lucky_keyboard, _user_kind
        from services.raffle_db import build_focus_lucky_message

        kind = _user_kind(context)
        text = await build_focus_lucky_message(user.id, kind)
        if not text:
            text = (
                "🍀 <b>FocusLucky</b>\n\n"
                "Сейчас нет активного розыгрыша. Следите за новостями!"
            )
        await msg.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=focus_lucky_keyboard(kind)
        )
        return

    if action == "promo":
        from handlers.exchange_flow import clear_exchange_session
        from telegram import ReplyKeyboardMarkup

        clear_exchange_session(context)
        context.user_data.pop("uref_wd", None)
        context.user_data["promo_enter"] = True
        kb = ReplyKeyboardMarkup([["🚫 Отмена"]], resize_keyboard=True)
        from services.ux_copy import txt_promo_enter

        await msg.reply_text(
            txt_promo_enter(),
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
        return

    if action == "discounts":
        from services.exchange_discount_db import get_user_discounts_overview
        from services.menu import main_menu_keyboard

        overview = await get_user_discounts_overview(user.id)
        active = overview.get("active") or []
        history = overview.get("history") or []
        lines = ["🏷 <b>Мои скидки на обмен</b>\n"]
        if active:
            lines.append("<b>Активные:</b>")
            for d in active:
                amt = d["amount_rub"]
                code = d.get("promo_code") or "—"
                min_order = float(d.get("min_order_rub") or 0)
                cond = (
                    f" · от {min_order:,.0f} ₽".replace(",", " ") if min_order > 0 else ""
                )
                if d.get("issued_by_operator_id"):
                    source = " · выдана оператором"
                else:
                    source = f" · код <code>{code}</code>"
                lines.append(
                    f"• <b>{amt:,.0f} ₽</b>{source}{cond} · до первого обмена".replace(
                        ",", " "
                    )
                )
        else:
            lines.append("Активных скидок нет.")
        if history:
            lines.append("\n<b>Использованные:</b>")
            for d in history[:10]:
                amt = d["amount_rub"]
                code = d.get("promo_code") or "—"
                oid = d.get("order_id")
                used = (d.get("used_at") or d.get("created_at") or "")[:10]
                if d.get("status") == "released":
                    lines.append(
                        f"• {amt:,.0f} ₽ · код {code} · отменена".replace(",", " ")
                    )
                elif oid:
                    lines.append(
                        f"• {amt:,.0f} ₽ · заявка <code>{oid}</code> · {used}".replace(
                            ",", " "
                        )
                    )
                else:
                    lines.append(
                        f"• {amt:,.0f} ₽ · код {code}".replace(",", " ")
                    )
        lines.append(
            "\n<i>Скидка применяется при покупке крипты — после ввода суммы.</i>"
        )
        await msg.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=await main_menu_keyboard(user.id, user.username),
        )
        return

    if action == "history":
        # Переиспользуем логику exchange_history через временный Update-like вызов
        from handlers.exchange_flow import exchange_history

        class _MsgProxy:
            """Прокси: handlers ждут update.message."""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            @property
            def text(self):
                return "📚 История операций"

            async def reply_text(self, *args, **kwargs):
                return await self._real.reply_text(*args, **kwargs)

        class _Upd:
            def __init__(self, q):
                self.callback_query = q
                self.message = _MsgProxy(q.message)
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat if q.message else None
                self.update_id = 0

        await exchange_history(_Upd(query), context)
        return

    if action == "balance":
        from services.marketing_messages import cashback_progress_line
        from services.user_balance_db import format_full_balance_message
        from services.user_referral_attribution import seal_referral_gate

        await seal_referral_gate(user.id)
        text = await format_full_balance_message(user.id)
        cb_line = await cashback_progress_line(user.id)
        if cb_line:
            text = f"{text}\n\n{cb_line}"
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("💸 Вывести средства", callback_data="uref:withdraw")],
                [
                    InlineKeyboardButton(
                        "🔄 Списать при следующем обмене",
                        callback_data="cashback:toggle",
                    )
                ],
            ]
        )
        await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if action == "partner":
        from services import config_rates
        from services.partner_db import (
            format_partner_cabinet_text,
            get_partner_stats,
        )
        from services.referral_links import web_ref_link

        row = await get_partner_by_telegram(user.id, user.username)
        if not row:
            await msg.reply_text(
                "Партнёрский кабинет недоступен. Получите код на сайте и: /partner_bind КОД"
            )
            return
        stats = await get_partner_stats(row["campaign_id"], row["campaign_code"], dict(row))
        ref = row["ref_token"] or row["campaign_code"]
        web_link = web_ref_link(ref, config_rates.PUBLIC_SITE_URL)
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📜 История", callback_data="uref:history")],
                [InlineKeyboardButton("🌐 Открыть ссылку сайта", url=web_link)],
            ]
        )
        await msg.reply_text(
            format_partner_cabinet_text(row, stats),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=kb,
        )
        return

    if action == "rates":
        from handlers.exchange_flow import exchange_rate

        class _MsgProxy:
            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            @property
            def text(self):
                return "💰 Курсы"

            async def reply_text(self, *args, **kwargs):
                return await self._real.reply_text(*args, **kwargs)

        class _Upd:
            def __init__(self, q):
                self.callback_query = q
                self.message = _MsgProxy(q.message)
                self.effective_user = q.from_user
                self.effective_chat = q.message.chat if q.message else None
                self.update_id = 0

        await exchange_rate(_Upd(query), context)
        return

    logger.warning("unknown hub action=%r", action)


async def cmd_getemoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ-утилита: следующий кастомный эмодзи → emoji_id."""
    from services import config_rates

    user = update.effective_user
    if not user or user.id not in getattr(config_rates, "TELEGRAM_ADMIN_IDS", []):
        return
    context.user_data["await_getemoji"] = True
    await update.message.reply_text(
        "Пришлите сообщение с премиум-эмодзи — верну emoji_id для tg_emoji.py"
    )


async def catch_custom_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_getemoji"):
        return
    if not update.message:
        return
    from services import config_rates

    user = update.effective_user
    if not user or user.id not in getattr(config_rates, "TELEGRAM_ADMIN_IDS", []):
        return

    entities = list(update.message.entities or []) + list(
        update.message.caption_entities or []
    )
    found = []
    for ent in entities:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            found.append(ent.custom_emoji_id)
    context.user_data.pop("await_getemoji", None)
    if not found:
        await update.message.reply_text("Кастомный эмодзи не найден в сообщении.")
        return
    lines = ["Найдено:"]
    for eid_val in found:
        lines.append(
            f'<code>("{eid_val}", "🪙")</code>\n'
            f'<tg-emoji emoji-id="{eid_val}">🪙</tg-emoji>'
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

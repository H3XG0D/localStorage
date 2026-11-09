"""Leave a VPN review in this bot. Operators still moderate it in the exchange queue.

Text first, then ten minutes for a screenshot of the app. One review per 7 days.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import api, config, ui

log = logging.getLogger("focusvpn-tg.reviews")

MIN_LEN = 20
PHOTO_WAIT_SEC = 600
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}


def amounts(review: dict | None) -> tuple[int, int]:
    review = review or {}
    return int(review.get("text_rub") or 25), int(review.get("photo_rub") or 50)


def plural_days(n: int) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def wait_label(next_at) -> str:
    if not next_at:
        return "позже"
    try:
        dt = datetime.fromisoformat(str(next_at).replace("Z", "+00:00"))
    except ValueError:
        return "позже"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (dt - datetime.now(timezone.utc)).total_seconds()
    days = max(1, int(-(-secs // 86400)))
    return f"через {plural_days(days)}"


def home_line(st: dict) -> str | None:
    review = st.get("review") or {}
    if not review:
        return None
    text_rub, photo_rub = amounts(review)
    if review.get("pending"):
        return f"{ui.emoji('review')} Отзыв на проверке. Когда оператор решит, сюда придёт сообщение."
    if review.get("eligible"):
        return (
            f"{ui.emoji('review')} Можно оставить отзыв и получить бонус: "
            f"{text_rub} ₽ за текст, {photo_rub} ₽ со скрином."
        )
    if review.get("reason") == "cooldown":
        return f"{ui.emoji('review')} Отзыв снова можно оставить {wait_label(review.get('next_at'))}."
    return None


def start_prompt(text_rub: int, photo_rub: int) -> str:
    body = (
        "Расскажите, как вам VPN.\n\n"
        f"<blockquote><b>+{text_rub} ₽</b> · текстовый отзыв\n"
        f"<b>+{photo_rub} ₽</b> · текст и скрин приложения</blockquote>\n\n"
        f"<b>Как получить бонус</b>\n"
        f"Отправьте одним сообщением от {MIN_LEN} символов. "
        "Скрин приложения — что VPN подключён — можно прислать следом в течение 10 минут.\n\n"
        "<i>Отзыв уйдёт на проверку оператору. Бонус начисляется на баланс FocusPay. "
        "Оставить можно раз в неделю.</i>"
    )
    return ui.screen("Ваше мнение важно", body, "review")


def text_accepted_prompt(text_rub: int, photo_rub: int) -> str:
    body = (
        f"<blockquote>Текст принят.\n"
        f"Чтобы получить <b>{photo_rub} ₽</b>, пришлите скрин FocusVPN в течение 10 минут.\n"
        f"Без фото — «Отправить без фото» (<b>{text_rub} ₽</b>) или просто подождите.</blockquote>"
    )
    return ui.screen("Готово", body, "check")


def pending_prompt(text_rub: int, photo_rub: int) -> str:
    body = (
        "<blockquote><b>Отзыв отправлен на проверку.</b>\n"
        "После одобрения он появится в канале отзывов.\n"
        f"Бонус на баланс FocusPay: <b>{text_rub} ₽</b> за текст "
        f"или <b>{photo_rub} ₽</b>, если был скрин.</blockquote>"
    )
    return ui.screen("Готово", body, "check")


def hub_text(st: dict) -> str:
    """Reviews tab: VPN reviews are written here, exchange reviews stay in FocusPay."""
    review = st.get("review") or {}
    text_rub, photo_rub = amounts(review or None)
    if review.get("pending") or review.get("reason") == "pending":
        state = "Отзыв на проверке. Когда оператор решит, сюда придёт сообщение."
    elif review.get("eligible"):
        state = (
            f"Можно написать отзыв и получить бонус: "
            f"{text_rub} ₽ за текст, {photo_rub} ₽ со скрином приложения."
        )
    elif review.get("reason") == "cooldown":
        state = f"Следующий отзыв {wait_label(review.get('next_at'))}."
    else:
        state = "Отзыв можно оставить при живой подписке или пробном периоде."
    body = (
        f"<blockquote>{state}</blockquote>\n\n"
        f"<b>+{text_rub} ₽</b> · текстовый отзыв\n"
        f"<b>+{photo_rub} ₽</b> · текст и скрин приложения\n\n"
        "<i>Раз в неделю. Бонус начисляется на баланс FocusPay после проверки. "
        "Отзыв об обмене пишется в боте FocusPay.</i>"
    )
    return ui.screen("Отзывы", body, "review")


def hub_keyboard(st: dict) -> InlineKeyboardMarkup:
    review = st.get("review") or {}
    rows = []
    if review.get("eligible"):
        _, photo_rub = amounts(review)
        rows.append([ui.button(f"Написать отзыв · до {photo_rub} ₽", "review:start", "review", "success")])
    url = (config.REVIEWS_CHANNEL_URL or "").strip()
    if url:
        rows.append([ui.button("Канал отзывов", url=url, icon="star", style=None)])
    rows.append(ui.back_row())
    return InlineKeyboardMarkup(rows)


def reminder_text(rem: dict) -> str:
    text_rub, photo_rub = amounts(rem)
    body = (
        "<blockquote>Можно оставить отзыв о FocusVPN.\n"
        f"Напишите, как вам VPN, и получите бонус на баланс FocusPay: "
        f"<b>{text_rub} ₽</b> за текст, <b>{photo_rub} ₽</b> за текст и скрин приложения.\n\n"
        "Отзыв проверяет оператор. Оставить можно раз в неделю.</blockquote>"
    )
    return ui.screen("Ваше мнение важно", body, "review")


def reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[ui.button("Оставить отзыв", "review:start", "review", "success")]])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[ui.button("Отмена", "review:cancel", style=None)]])


def photo_keyboard(text_rub: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [ui.button(f"Отправить без фото ({text_rub} ₽)", "review:skip_photo")],
            [ui.button("Отмена", "review:cancel", style=None)],
        ]
    )


def _author(user) -> str:
    if getattr(user, "username", None):
        return f"@{user.username}"
    name = (getattr(user, "first_name", None) or "").strip()
    return name or f"id{user.id}"


def abandon(ud: dict | None) -> None:
    """Drop a half-written review when the user opens the menu again."""
    if ud:
        _clear(ud)


def _clear(ud: dict) -> None:
    task = ud.pop("review_finalize_task", None)
    if task and not task.done() and task is not asyncio.current_task():
        task.cancel()
    for key in (
        "awaiting_review",
        "review_step",
        "review_draft_text",
        "review_text_rub",
        "review_photo_rub",
        "review_author",
        "review_finalize_generation",
    ):
        ud.pop(key, None)


def _is_image(message) -> bool:
    if getattr(message, "photo", None):
        return True
    doc = getattr(message, "document", None)
    if not doc:
        return False
    mime = (doc.mime_type or "").lower()
    if mime in _IMAGE_MIME or mime.startswith("image/"):
        return True
    name = (doc.file_name or "").lower()
    return name.endswith(_IMAGE_EXT)


async def _download(message) -> tuple[str, bytes, str] | None:
    if getattr(message, "photo", None):
        tg_file = await message.photo[-1].get_file()
        name, mime = "shot.jpg", "image/jpeg"
    else:
        doc = message.document
        tg_file = await doc.get_file()
        name = doc.file_name or "shot.jpg"
        mime = doc.mime_type or "image/jpeg"
    data = bytes(await tg_file.download_as_bytearray())
    if not data:
        return None
    return name, data, mime


def _start_timer(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int) -> None:
    ud = context.user_data
    old = ud.get("review_finalize_task")
    if old and not old.done():
        old.cancel()
    generation = int(ud.get("review_finalize_generation") or 0) + 1
    ud["review_finalize_generation"] = generation
    ud["review_finalize_task"] = asyncio.create_task(
        _auto_send(context.application, user_id=user_id, chat_id=chat_id, generation=generation)
    )


async def _auto_send(application, *, user_id: int, chat_id: int, generation: int) -> None:
    try:
        await asyncio.sleep(PHOTO_WAIT_SEC)
    except asyncio.CancelledError:
        return
    ud = application.user_data[user_id]
    if ud.get("review_finalize_generation") != generation:
        return
    if ud.get("review_step") != "awaiting_photo" or not ud.get("review_draft_text"):
        return
    await _submit(application.bot, ud, user_id, chat_id, photo=None)


async def _submit(bot, ud: dict, user_id: int, chat_id: int, photo) -> None:
    if ud.get("review_submitting"):
        return
    ud["review_submitting"] = True
    text = ud.get("review_draft_text") or ""
    author = ud.get("review_author") or f"id{user_id}"
    text_rub = int(ud.get("review_text_rub") or 25)
    photo_rub = int(ud.get("review_photo_rub") or 50)
    _clear(ud)
    try:
        try:
            await api.fp_submit_review(user_id, text, author, photo)
        except api.APIError as e:
            message = (e.detail or {}).get("message") or "Не удалось отправить отзыв. Попробуйте позже."
            await bot.send_message(chat_id, str(message))
            return
        await ui.send_html(
            bot,
            chat_id,
            pending_prompt(text_rub, photo_rub),
            InlineKeyboardMarkup([ui.back_row()]),
        )
    finally:
        ud.pop("review_submitting", None)


def _block_reason(review: dict) -> str:
    if review.get("pending") or review.get("reason") == "pending":
        return "Отзыв уже на проверке."
    if review.get("reason") == "cooldown":
        return f"Отзыв снова можно оставить {wait_label(review.get('next_at'))}."
    return "Отзыв можно оставить при живой подписке."


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user if query else None
    if not query or not user:
        return
    data = query.data or ""
    if data == "review:cancel":
        await query.answer()
        _clear(context.user_data)
        await ui.edit_query(
            query,
            ui.screen("Готово", "<blockquote>Отзыв отменён.</blockquote>", "info"),
            InlineKeyboardMarkup([ui.back_row()]),
        )
        return
    if data == "review:skip_photo":
        ud = context.user_data
        if ud.get("review_step") != "awaiting_photo" or not ud.get("review_draft_text"):
            await query.answer("Сначала напишите текст отзыва.", show_alert=True)
            return
        await query.answer()
        chat_id = query.message.chat_id if query.message else user.id
        await _submit(context.bot, ud, user.id, chat_id, photo=None)
        return
    if data != "review:start":
        return
    try:
        st = await api.fp_status(user.id)
    except api.APIError:
        await query.answer("Сервис временно недоступен. Попробуйте через минуту.", show_alert=True)
        return
    review = st.get("review") or {}
    if not review.get("eligible"):
        await query.answer(_block_reason(review), show_alert=True)
        return
    if context.user_data.get("review_step") == "awaiting_photo" and context.user_data.get("review_draft_text"):
        await query.answer("Текст уже принят. Пришлите скрин или нажмите «Отправить без фото».", show_alert=True)
        return
    await query.answer()
    text_rub, photo_rub = amounts(review)
    context.user_data["awaiting_review"] = True
    context.user_data["review_step"] = "awaiting_text"
    context.user_data["review_text_rub"] = text_rub
    context.user_data["review_photo_rub"] = photo_rub
    context.user_data["review_author"] = _author(user)
    await ui.edit_query(query, start_prompt(text_rub, photo_rub), cancel_keyboard())


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user or not context.user_data.get("awaiting_review"):
        return
    ud = context.user_data
    text_rub = int(ud.get("review_text_rub") or 25)
    photo_rub = int(ud.get("review_photo_rub") or 50)
    step = ud.get("review_step")

    if _is_image(message) and step == "awaiting_photo" and ud.get("review_draft_text"):
        photo = await _download(message)
        if photo is None:
            await ui.reply_html(
                message,
                ui.screen(
                    "Не получилось",
                    "<blockquote>Не удалось прочитать скрин. Пришлите ещё раз или отправьте без фото.</blockquote>",
                    "review",
                ),
            )
            return
        await _submit(context.bot, ud, user.id, message.chat_id, photo)
        return

    if _is_image(message):
        await ui.reply_html(
            message,
            ui.screen(
                "Не получилось",
                "<blockquote>Сначала напишите текст отзыва, скрин — следом.</blockquote>",
                "review",
            ),
        )
        return

    raw = (message.text or message.caption or "").strip()
    if not raw:
        return
    if len(raw) < MIN_LEN:
        await ui.reply_html(
            message,
            ui.screen(
                "Не получилось",
                f"<blockquote>Отзыв слишком короткий. Напишите хотя бы {MIN_LEN} символов.</blockquote>",
                "review",
            ),
        )
        return
    ud["review_draft_text"] = raw[:2000]
    ud["review_step"] = "awaiting_photo"
    ud["review_author"] = _author(user)
    _start_timer(context, user.id, message.chat_id)
    await ui.reply_html(message, text_accepted_prompt(text_rub, photo_rub), photo_keyboard(text_rub))

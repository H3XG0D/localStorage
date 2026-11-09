"""Оставить отзыв: модерация, бонус 50/100 ₽."""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.antispam import rate_limit_ok
from services.review_bonus import (
    ReviewBonusError,
    clear_review_session,
    create_pending_submission,
    pop_pending_review_order,
    resolve_review_order_id,
    submission_tier,
    validate_review_text,
)
from services.review_invite_content import (
    REVIEW_PHOTO_WINDOW_SECONDS,
    review_pending_user_message,
    review_photo_received_prompt,
    review_start_prompt,
    review_text_accepted_prompt,
)
from services.review_moderation import send_moderation_request
from services.user_errors import user_facing_message

logger = logging.getLogger("review_bonus")

REVIEW_FINALIZE_SECONDS = REVIEW_PHOTO_WINDOW_SECONDS

_IMAGE_DOC_MIMES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
        "image/gif",
    }
)
_IMAGE_DOC_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif")


def _is_review_image_message(message) -> bool:
    if not message:
        return False
    if getattr(message, "photo", None):
        return True
    doc = getattr(message, "document", None)
    if not doc:
        return False
    mime = (doc.mime_type or "").lower()
    if mime in _IMAGE_DOC_MIMES or mime.startswith("image/"):
        return True
    name = (doc.file_name or "").lower()
    return name.endswith(_IMAGE_DOC_EXTENSIONS)


def _review_image_file_id(message) -> str | None:
    photos = getattr(message, "photo", None) if message is not None else None
    if photos:
        return photos[-1].file_id
    doc = getattr(message, "document", None) if message is not None else None
    if doc and _is_review_image_message(message):
        return doc.file_id
    return None


def _cancel_finalize_in_ud(ud: dict) -> None:
    task = ud.pop("review_finalize_task", None)
    if task and not task.done():
        task.cancel()


def _cancel_finalize_task(context: ContextTypes.DEFAULT_TYPE) -> None:
    _cancel_finalize_in_ud(context.user_data)


def _clear_review_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    _cancel_finalize_task(context)
    clear_review_session(context)


def _store_photo_refs(context: ContextTypes.DEFAULT_TYPE, message) -> None:
    context.user_data["review_photo_chat_id"] = message.chat_id
    context.user_data["review_photo_message_id"] = message.message_id
    file_id = _review_image_file_id(message)
    if file_id:
        context.user_data["review_photo_file_id"] = file_id


def _stored_photo_message(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("review_photo_chat_id")
    message_id = context.user_data.get("review_photo_message_id")
    if chat_id is None or message_id is None:
        return None

    class _PhotoRef:
        pass

    ref = _PhotoRef()
    ref.chat_id = int(chat_id)
    ref.message_id = int(message_id)
    return ref


def _start_finalize_timer(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    chat_id: int,
) -> None:
    _cancel_finalize_task(context)
    generation = int(context.user_data.get("review_finalize_generation") or 0) + 1
    context.user_data["review_finalize_generation"] = generation
    context.user_data["review_finalize_task"] = asyncio.create_task(
        _auto_finalize_text_only(
            context.application,
            user_id=user_id,
            chat_id=chat_id,
            generation=generation,
        )
    )


async def _auto_finalize_text_only(
    application,
    *,
    user_id: int,
    chat_id: int,
    generation: int,
) -> None:
    try:
        await asyncio.sleep(REVIEW_FINALIZE_SECONDS)
    except asyncio.CancelledError:
        return

    ud = application.user_data[user_id]
    if not ud.get("awaiting_review"):
        return
    if ud.get("review_step") != "awaiting_photo":
        return
    if ud.get("review_finalize_generation") != generation:
        return
    if not ud.get("review_draft_text"):
        return

    class _User:
        id = user_id

    await _finalize_submission(
        application.bot,
        context_user_data=ud,
        user=_User(),
        reply_chat_id=chat_id,
        photo_message=None,
    )


def _review_collect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data="review:cancel")]]
    )


def _review_awaiting_photo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📤 Отправить без фото (50 ₽)",
                    callback_data="review:skip_photo",
                )
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="review:cancel")],
        ]
    )


async def review_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    if not await rate_limit_ok(update):
        return
    user = query.from_user
    if not user:
        return

    # Повторный «Оставить отзыв» раньше сбрасывал черновик и таймер —
    # отзыв так и не уходил на модерацию (операторы ничего не видели).
    if context.user_data.get("awaiting_review"):
        step = context.user_data.get("review_step")
        if step == "awaiting_photo" and context.user_data.get("review_draft_text"):
            await query.answer(
                "Текст уже принят. Пришлите скрин или нажмите «Отправить без фото».",
                show_alert=True,
            )
            await query.message.reply_text(
                review_text_accepted_prompt(finalize_seconds=REVIEW_FINALIZE_SECONDS),
                parse_mode="HTML",
                reply_markup=_review_awaiting_photo_keyboard(),
            )
            return
        await query.answer()
        await query.message.reply_text(
            review_start_prompt(),
            parse_mode="HTML",
            reply_markup=_review_collect_keyboard(),
        )
        return

    await query.answer()
    hinted = pop_pending_review_order(user.id)
    try:
        order_id = await resolve_review_order_id(user.id, hinted)
    except ReviewBonusError as e:
        await query.message.reply_text(user_facing_message(e), parse_mode="HTML")
        return

    context.user_data["awaiting_review"] = True
    context.user_data["review_step"] = "collect"
    context.user_data["review_order_id"] = order_id

    await query.message.reply_text(
        review_start_prompt(),
        parse_mode="HTML",
        reply_markup=_review_collect_keyboard(),
    )


async def review_skip_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сразу отправить отзыв текстом, не дожидаясь 10 минут / скрина."""
    query = update.callback_query
    if not query:
        return
    if not await rate_limit_ok(update):
        return
    user = query.from_user
    if not user:
        return

    if (
        not context.user_data.get("awaiting_review")
        or context.user_data.get("review_step") != "awaiting_photo"
        or not context.user_data.get("review_draft_text")
    ):
        await query.answer("Сначала напишите текст отзыва.", show_alert=True)
        return

    await query.answer()
    _cancel_finalize_task(context)
    await _finalize_submission(
        context.bot,
        context_user_data=context.user_data,
        user=user,
        reply_chat_id=query.message.chat_id,
        photo_message=None,
    )


async def review_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    _clear_review_session(context)
    await query.message.reply_text("Отменено.")


async def review_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not context.user_data.get("awaiting_review"):
        return
    _clear_review_session(context)
    await update.message.reply_text("Отменено.")


async def review_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not context.user_data.get("awaiting_review"):
        return
    if not await rate_limit_ok(update):
        return

    step = context.user_data.get("review_step", "collect")
    user = update.effective_user
    text = (update.message.text or "").strip()

    if step == "awaiting_photo":
        if text:
            await update.message.reply_text(
                review_text_accepted_prompt(finalize_seconds=REVIEW_FINALIZE_SECONDS),
                parse_mode="HTML",
                reply_markup=_review_awaiting_photo_keyboard(),
            )
            return
        if _is_review_image_message(update.message):
            _cancel_finalize_task(context)
            await _finalize_submission(
                context.bot,
                context_user_data=context.user_data,
                user=user,
                reply_chat_id=update.message.chat_id,
                photo_message=update.message,
            )
            return
        if update.message.document or update.message.video:
            await update.message.reply_text(
                "Пришлите скриншот как <b>фото</b> или изображение (JPG/PNG), не PDF/видео.",
                parse_mode="HTML",
            )
        return

    if step != "collect" or not text:
        if step == "collect" and _is_review_image_message(update.message):
            _store_photo_refs(context, update.message)
            await update.message.reply_text(
                review_photo_received_prompt(),
                parse_mode="HTML",
            )
        elif step == "collect" and (update.message.document or update.message.video):
            await update.message.reply_text(
                "Скрин начисления пришлите как <b>фото</b> или картинку (JPG/PNG).",
                parse_mode="HTML",
            )
        return

    try:
        draft = validate_review_text(text)
    except ReviewBonusError as e:
        await update.message.reply_text(user_facing_message(e), parse_mode="HTML")
        return

    context.user_data["review_draft_text"] = draft
    context.user_data["review_text_chat_id"] = update.message.chat_id
    context.user_data["review_text_message_id"] = update.message.message_id

    stored_photo = _stored_photo_message(context)
    if stored_photo:
        await _finalize_submission(
            context.bot,
            context_user_data=context.user_data,
            user=user,
            reply_chat_id=update.message.chat_id,
            photo_message=stored_photo,
        )
        return

    context.user_data["review_step"] = "awaiting_photo"
    _start_finalize_timer(
        context,
        user_id=user.id,
        chat_id=update.message.chat_id,
    )
    await update.message.reply_text(
        review_text_accepted_prompt(finalize_seconds=REVIEW_FINALIZE_SECONDS),
        parse_mode="HTML",
        reply_markup=_review_awaiting_photo_keyboard(),
    )


async def review_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not context.user_data.get("awaiting_review"):
        return
    if not await rate_limit_ok(update):
        return
    if update.message.media_group_id:
        await update.message.reply_text("Пришлите одно фото, не альбом.")
        return
    if not _is_review_image_message(update.message):
        return

    step = context.user_data.get("review_step", "collect")
    user = update.effective_user
    caption = (update.message.caption or "").strip()

    if step == "awaiting_photo":
        _cancel_finalize_task(context)
        await _finalize_submission(
            context.bot,
            context_user_data=context.user_data,
            user=user,
            reply_chat_id=update.message.chat_id,
            photo_message=update.message,
        )
        return

    if step != "collect":
        return

    if caption:
        try:
            draft = validate_review_text(caption)
        except ReviewBonusError as e:
            await update.message.reply_text(user_facing_message(e), parse_mode="HTML")
            return
        context.user_data["review_draft_text"] = draft
        context.user_data["review_text_chat_id"] = update.message.chat_id
        context.user_data["review_text_message_id"] = update.message.message_id
        await _finalize_submission(
            context.bot,
            context_user_data=context.user_data,
            user=user,
            reply_chat_id=update.message.chat_id,
            photo_message=update.message,
        )
        return

    _store_photo_refs(context, update.message)
    await update.message.reply_text(
        review_photo_received_prompt(),
        parse_mode="HTML",
    )


async def _finalize_submission(
    bot,
    *,
    context_user_data: dict,
    user,
    reply_chat_id: int,
    photo_message,
):
    draft = context_user_data.get("review_draft_text")
    text_chat = context_user_data.get("review_text_chat_id")
    text_mid = context_user_data.get("review_text_message_id")
    if not draft or text_chat is None or text_mid is None:
        await bot.send_message(
            chat_id=reply_chat_id,
            text="Сначала напишите текст отзыва.",
            parse_mode="HTML",
        )
        return

    photo_chat = photo_mid = None
    photo_file_id = None
    if photo_message is not None:
        photo_chat = getattr(photo_message, "chat_id", None)
        photo_mid = getattr(photo_message, "message_id", None)
        photo_file_id = _review_image_file_id(photo_message) or context_user_data.get(
            "review_photo_file_id"
        )
    elif context_user_data.get("review_photo_message_id"):
        photo_chat = context_user_data.get("review_photo_chat_id")
        photo_mid = context_user_data.get("review_photo_message_id")
        photo_file_id = context_user_data.get("review_photo_file_id")

    has_photo = photo_mid is not None
    tier = submission_tier(has_photo=has_photo)
    hinted = context_user_data.pop("review_order_id", None)
    _cancel_finalize_in_ud(context_user_data)
    clear_review_session(context_user_data)

    try:
        order_id = await resolve_review_order_id(user.id, hinted)
    except ReviewBonusError as e:
        await bot.send_message(
            chat_id=reply_chat_id,
            text=user_facing_message(e),
            parse_mode="HTML",
        )
        return

    try:
        sub_id = await create_pending_submission(
            user_id=user.id,
            review_text=draft,
            user=user,
            order_id=order_id,
            source_text_chat_id=int(text_chat),
            source_text_message_id=int(text_mid),
            tier=tier,
            source_photo_chat_id=int(photo_chat) if photo_chat is not None else None,
            source_photo_message_id=int(photo_mid) if photo_mid is not None else None,
            source_photo_file_id=photo_file_id,
        )
    except ReviewBonusError as e:
        await bot.send_message(
            chat_id=reply_chat_id,
            text=user_facing_message(e),
            parse_mode="HTML",
        )
        return
    except Exception:
        logger.exception("create_pending_submission failed")
        await bot.send_message(
            chat_id=reply_chat_id,
            text="❌ Не удалось отправить отзыв. Попробуйте позже.",
            parse_mode="HTML",
        )
        return

    try:
        await send_moderation_request(bot, sub_id)
    except Exception:
        logger.warning("moderation notify failed sub_id=%s", sub_id, exc_info=True)

    await bot.send_message(
        chat_id=reply_chat_id,
        text=review_pending_user_message(),
        parse_mode="HTML",
    )

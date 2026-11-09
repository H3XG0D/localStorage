"""Тексты и клавиатура приглашения к отзыву (без зависимости от python-telegram-bot)."""
from __future__ import annotations

from services import config_rates, runtime_settings

MIN_REVIEW_LEN = 20

# Сколько ждать скрин начисления после текста отзыва (сек).
REVIEW_PHOTO_WINDOW_SECONDS = 600


def review_bonus_amounts() -> tuple[int, int]:
    return (
        int(runtime_settings.review_bonus_text_rub()),
        int(runtime_settings.review_bonus_photo_rub()),
    )


def review_invite_text() -> str:
    t50, t100 = review_bonus_amounts()
    return (
        f"📢 <b>Оставьте отзыв о сервисе</b>\n\n"
        f"1. Напишите отзыв <b>текстом</b> (от {MIN_REVIEW_LEN} символов).\n"
        f"2. По желанию — <b>фото</b>: скриншот, <b>куда пришли деньги</b> "
        f"(начисление на кошелёк).\n\n"
        f"После проверки админом опубликуем в канале; на сайте — только текст отзыва.\n"
        f"🎁 Бонус: <b>{t50} ₽</b> за текст, <b>{t100} ₽</b> за текст + скрин начисления "
        f"(не чаще 1 раза в день).\n\n"
        "ℹ️ Приглашение приходит <b>после успешной покупки</b> (авто или ручной) — "
        "когда крипта уже отправлена."
    )


def review_start_prompt() -> str:
    t50, t100 = review_bonus_amounts()
    return (
        f"✍️ Напишите отзыв <b>одним сообщением</b> (от {MIN_REVIEW_LEN} символов).\n\n"
        f"🎁 <b>{t50} ₽</b> за текст, <b>{t100} ₽</b> — если следом пришлёте "
        f"<b>скрин, куда пришли деньги</b>.\n"
        f"Отзыв уйдёт на проверку <b>автоматически</b>.\n\n"
        "Или /cancel — отмена."
    )


def review_finalize_window_label(seconds: int) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        n = seconds // 60
        if n % 10 == 1 and n % 100 != 11:
            return f"{n} минуту"
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
            return f"{n} минуты"
        return f"{n} минут"
    return f"{seconds} сек"


def review_text_accepted_prompt(
    *, finalize_seconds: int = REVIEW_PHOTO_WINDOW_SECONDS
) -> str:
    t50, t100 = review_bonus_amounts()
    window = review_finalize_window_label(finalize_seconds)
    return (
        f"✅ Текст принят.\n\n"
        f"📷 Чтобы претендовать на <b>{t100} ₽</b>, пришлите <b>скрин начисления</b> "
        f"в течение {window}.\n"
        f"Без фото — нажмите «Отправить без фото» или подождите "
        f"(отправим на проверку, <b>{t50} ₽</b>)."
    )


def review_photo_received_prompt() -> str:
    _, t100 = review_bonus_amounts()
    return (
        f"📷 Скрин получен. Теперь напишите текст отзыва "
        f"(от {MIN_REVIEW_LEN} символов). С фото — бонус до <b>{t100} ₽</b>."
    )


def review_pending_user_message() -> str:
    t50, t100 = review_bonus_amounts()
    return (
        "✅ <b>Отзыв отправлен на проверку.</b>\n\n"
        "После одобрения админом он появится в канале. На сайте — только текст отзыва.\n"
        f"🎁 Бонус: <b>{t50} ₽</b> (текст) или <b>{t100} ₽</b> (если был скрин начисления)."
    )


def review_invite_reply_markup_dict(*, include_start: bool = True) -> dict:
    rows: list[list[dict]] = []
    if include_start:
        rows.append([{"text": "✍️ Оставить отзыв", "callback_data": "review:start"}])
    return {
        "inline_keyboard": rows + [
            [
                {
                    "text": "📢 Канал отзывов",
                    "url": config_rates.reviews_channel_url(),
                }
            ],
        ],
    }

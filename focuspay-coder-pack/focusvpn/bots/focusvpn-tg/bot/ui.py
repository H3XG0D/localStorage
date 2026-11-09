"""Telegram screen chrome: premium emoji, colored buttons, and a Unicode fallback.

IDs are the same TgAndroidIcons / NewsEmoji set as the botvpn demo. Custom emoji
need a Premium bot owner or a Fragment username. If Telegram rejects them, the
process switches to ordinary emoji until restart.
"""

from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.constants import ParseMode
from telegram.error import BadRequest

from bot import config

log = logging.getLogger("focusvpn-tg.ui")

# Verified catalog: https://t.me/addemoji/TgAndroidIcons and /NewsEmoji.
EMOJI = {
    "globe": ("5879585266426973039", "🌐"),
    "check": ("5825794181183836432", "✅"),
    "wallet": ("5769403330761593044", "👛"),
    "card": ("5927169041595634481", "💳"),
    "device": ("5987917196469213507", "📱"),
    "key": ("6005570495603282482", "🔑"),
    "download": ("5899757765743615694", "⬇️"),
    "info": ("5879785854284599288", "ℹ️"),
    "review": ("5879841310902324730", "✏️"),
    "back": ("5875082500023258804", "↩️"),
    "refresh": ("5877410604225924969", "🔄"),
    "star": ("5438496463044752972", "⭐"),
}

LINK_OFF = LinkPreviewOptions(is_disabled=True)
_EMOJI_TAG = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>')

premium = config.PREMIUM_EMOJI


def emoji(key: str) -> str:
    eid, fallback = EMOJI[key]
    if premium:
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'
    return fallback


def button(
    text: str,
    data: str | None = None,
    icon: str | None = None,
    style: str | None = "primary",
    *,
    url: str | None = None,
) -> InlineKeyboardButton:
    """Colored inline button. With premium off, the icon is a Unicode prefix."""
    eid, fallback = EMOJI[icon] if icon else (None, "")
    label = text if premium or not icon else f"{fallback} {text}"
    kwargs: dict = {"text": label}
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = data
    if premium and eid:
        kwargs["icon_custom_emoji_id"] = eid
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def back_row(target: str = "home", label: str | None = None) -> list[InlineKeyboardButton]:
    if label is None:
        label = "В меню" if target == "home" else "Назад"
    return [button(label, target, "back", style=None)]


def screen(title: str, body: str = "", icon: str = "globe") -> str:
    text = f"{emoji(icon)} <b>{title}</b>"
    if body:
        text += f"\n\n{body}"
    return text


def plain_text(text: str) -> str:
    return _EMOJI_TAG.sub(r"\1", text)


def plain_markup(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    fallbacks = {eid: fallback for eid, fallback in EMOJI.values()}
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for item in row:
            label = item.text or ""
            eid = item.icon_custom_emoji_id
            if eid in fallbacks and not label.startswith(fallbacks[eid]):
                label = f"{fallbacks[eid]} {label}"
            kwargs: dict = {"text": label}
            if item.url:
                kwargs["url"] = item.url
            elif item.callback_data:
                kwargs["callback_data"] = item.callback_data
            if item.style:
                kwargs["style"] = item.style
            new_row.append(InlineKeyboardButton(**kwargs))
        rows.append(new_row)
    return InlineKeyboardMarkup(rows)


def _emoji_rejected(reason: str) -> bool:
    return any(word in reason for word in ("emoji", "premium", "entitycustomemoji"))


async def deliver(sender, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Send once. On a premium-emoji refusal, retry this message in Unicode and stay there."""
    global premium
    try:
        await sender(text, markup)
    except BadRequest as exc:
        reason = (exc.message or "").lower()
        if "message is not modified" in reason:
            return
        if premium and _emoji_rejected(reason):
            premium = False
            log.warning("Premium emoji unavailable; switched to Unicode.")
            await sender(plain_text(text), plain_markup(markup))
            return
        raise


async def reply_html(message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    async def sender(body: str, keyboard: InlineKeyboardMarkup | None) -> None:
        await message.reply_text(
            body, parse_mode=ParseMode.HTML, reply_markup=keyboard, link_preview_options=LINK_OFF
        )

    await deliver(sender, text, markup)


async def edit_query(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    async def sender(body: str, keyboard: InlineKeyboardMarkup | None) -> None:
        await query.edit_message_text(
            body, parse_mode=ParseMode.HTML, reply_markup=keyboard, link_preview_options=LINK_OFF
        )

    await deliver(sender, text, markup)


async def send_html(bot, chat_id: int, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    async def sender(body: str, keyboard: InlineKeyboardMarkup | None) -> None:
        await bot.send_message(
            chat_id, body, parse_mode=ParseMode.HTML, reply_markup=keyboard, link_preview_options=LINK_OFF
        )

    await deliver(sender, text, markup)

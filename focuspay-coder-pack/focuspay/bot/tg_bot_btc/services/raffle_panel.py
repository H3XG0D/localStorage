"""FocusLucky admin panel (/raffle) in reports group."""

from __future__ import annotations

import logging

import html
import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.config_rates import TELEGRAM_ADMIN_IDS
from services.financial_guards import is_reports_group_chat
from services.raffle_constants import (
    format_prizes_block,
    get_default_how_to_text,
    get_default_info_text,
    resolve_how_to_text,
    resolve_info_text,
)
from services.raffle_db import (
    _parse_prize_places,
    activate_campaign,
    close_campaign,
    count_participants,
    format_draw_countdown_line,
    format_participant_admin_line,
    get_campaign_for_admin,
    get_campaign_stats,
    get_participant_admin_detail,
    list_participants_page,
    pay_balance_winners,
    start_show,
    set_accrual_blocked,
    start_new_campaign_without_draw,
    update_campaign_text,
)

logger = logging.getLogger("raffle_panel")

PARTICIPANTS_PAGE_SIZE = 12


def _admin_ok(update: Update) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    if not is_reports_group_chat(update.effective_chat.id):
        return False
    return update.effective_user.id in TELEGRAM_ADMIN_IDS


def _tab_keyboard(active: str, campaign_id: int) -> InlineKeyboardMarkup:
    tabs = [
        ("overview", "Обзор"),
        ("parts:0", "Участники"),
        ("text", "Текст"),
        ("actions", "Действия"),
    ]
    row = []
    for key, label in tabs:
        prefix = "• " if active == key or (
            active.startswith("parts:") and key == "parts:0"
        ) else ""
        row.append(
            InlineKeyboardButton(
                f"{prefix}{label}",
                callback_data=f"raffle:{key}:{campaign_id}",
            )
        )
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("🔍 Найти user_id", callback_data=f"raffle:find:{campaign_id}")],
        ]
    )


def _cancel_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=f"raffle:cancel_edit:{campaign_id}",
                )
            ]
        ]
    )


async def _panel_send_or_edit(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    parse_mode: str = "HTML",
):
    panel_chat_id = context.chat_data.get("raffle_panel_chat_id")
    panel_message_id = context.chat_data.get("raffle_panel_message_id")
    if panel_chat_id and panel_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
    context.chat_data["raffle_panel_chat_id"] = sent.chat_id
    context.chat_data["raffle_panel_message_id"] = sent.message_id


def _preview_block(title: str, body: str, *, max_len: int = 400) -> str:
    preview = body.strip() or "—"
    if len(preview) > max_len:
        preview = preview[: max_len - 1] + "…"
    return f"<b>{title}</b>\n<pre>{html.escape(preview)}</pre>"


async def _resolve_campaign(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    cid = context.chat_data.get("raffle_campaign_id")
    if cid:
        from services.raffle_db import get_campaign_by_id

        camp = await get_campaign_by_id(int(cid))
        if camp:
            return camp
    camp = await get_campaign_for_admin()
    if camp:
        context.chat_data["raffle_campaign_id"] = camp["id"]
    return camp


async def build_overview_text(campaign: dict) -> str:
    stats = await get_campaign_stats(campaign["id"])
    c = stats["campaign"]
    month = html.escape(str(c.get("month_label") or c.get("slug") or ""))
    lines = [
        f"🍀 <b>FocusLucky</b> #{c['id']} · {month}",
        f"Статус: <b>{html.escape(str(c['status']))}</b>",
        f"Участников: <b>{stats['participants']}</b>",
        f"Билетов в пуле: <b>{stats['pool_total']}</b>",
        f"Порог: <b>{int(float(c['rub_per_own_ticket'])):,}</b> ₽ свой / "
        f"<b>{int(float(c['rub_per_referral_ticket'])):,}</b> ₽ реф".replace(",", " "),
    ]
    if c.get("draw_at"):
        countdown = format_draw_countdown_line(c["draw_at"])
        if countdown:
            lines.append(countdown)
    prize_places = _parse_prize_places(c.get("prize_places"))
    lines.extend(["", format_prizes_block(prize_places)])
    return "\n".join(lines)


async def build_participants_text(campaign: dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    campaign_id = int(campaign["id"])
    total = await count_participants(campaign_id)
    stats = await get_campaign_stats(campaign_id)
    pool_total = stats["pool_total"]
    pages = max(1, math.ceil(total / PARTICIPANTS_PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    offset = page * PARTICIPANTS_PAGE_SIZE
    rows = await list_participants_page(
        campaign_id, offset=offset, limit=PARTICIPANTS_PAGE_SIZE
    )

    lines = [
        f"👥 <b>Участники</b> · стр. {page + 1}/{pages} · всего <b>{total}</b>",
        "",
    ]
    if not rows:
        lines.append("Пока никого нет.")
    else:
        for i, row in enumerate(rows, start=offset + 1):
            lines.append(format_participant_admin_line(row, rank=i, pool_total=pool_total))

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "◀️",
                callback_data=f"raffle:parts:{page - 1}:{campaign_id}",
            )
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                "▶️",
                callback_data=f"raffle:parts:{page + 1}:{campaign_id}",
            )
        )

    user_buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        uid = int(row["user_id"])
        label = f"👤 {uid}"
        if row.get("username"):
            label = f"@{row['username']}"
        user_buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"raffle:user:{uid}:{campaign_id}",
                )
            ]
        )

    keyboard_rows = [_tab_keyboard(f"parts:{page}", campaign_id).inline_keyboard[0]]
    if nav:
        keyboard_rows.append(nav)
    keyboard_rows.extend(user_buttons)
    keyboard_rows.append(
        _tab_keyboard(f"parts:{page}", campaign_id).inline_keyboard[1]
    )
    return "\n".join(lines), InlineKeyboardMarkup(keyboard_rows)


def build_text_tab(campaign: dict) -> str:
    info = resolve_info_text(campaign)
    how = resolve_how_to_text(campaign)
    custom_info = " (свой)" if campaign.get("info_text") else " (дефолт)"
    custom_how = " (свой)" if campaign.get("how_to_text") else " (дефолт)"
    return "\n\n".join(
        [
            "📝 <b>Тексты розыгрыша</b>",
            _preview_block(f"Описание внизу экрана{custom_info}", info),
            _preview_block(f"Как получить билеты{custom_how}", how),
        ]
    )


def _text_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    rows = _tab_keyboard("text", campaign_id).inline_keyboard
    return InlineKeyboardMarkup(
        rows
        + [
            [
                InlineKeyboardButton(
                    "✏️ Описание",
                    callback_data=f"raffle:edit_info:{campaign_id}",
                ),
                InlineKeyboardButton(
                    "✏️ Как получить",
                    callback_data=f"raffle:edit_how:{campaign_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "↩️ Сброс описания",
                    callback_data=f"raffle:reset_info:{campaign_id}",
                ),
                InlineKeyboardButton(
                    "↩️ Сброс как получить",
                    callback_data=f"raffle:reset_how:{campaign_id}",
                ),
            ],
        ]
    )


def build_actions_tab(campaign: dict) -> str:
    c = campaign
    return (
        f"⚙️ <b>Действия</b> · кампания #{c['id']}\n\n"
        f"Статус: <b>{html.escape(str(c['status']))}</b>\n\n"
        "Закрыть — стоп начисления билетов.\n"
        "Активировать — снова открыть начисление.\n"
        "Шоу — закрыть набор и крутить места с 1-го.\n"
        "Догнать выплату — старые pending на баланс."
    )


def _actions_keyboard(campaign: dict) -> InlineKeyboardMarkup:
    cid = int(campaign["id"])
    status = str(campaign.get("status") or "")
    rows = list(_tab_keyboard("actions", cid).inline_keyboard)
    action_row: list[InlineKeyboardButton] = []
    if status == "active":
        action_row.append(
            InlineKeyboardButton("⏸ Закрыть", callback_data=f"raffle:close:{cid}")
        )
    if status in ("draft", "closed"):
        action_row.append(
            InlineKeyboardButton("▶️ Активировать", callback_data=f"raffle:activate:{cid}")
        )
    if status in ("active", "closed"):
        action_row.append(
            InlineKeyboardButton("🎬 Запустить шоу", callback_data=f"raffle:draw:{cid}")
        )
    if status == "drawn":
        action_row.append(
            InlineKeyboardButton("💰 Выплата balance", callback_data=f"raffle:pay:{cid}")
        )
    extra = [action_row] if action_row else []
    extra.append(
        [
            InlineKeyboardButton(
                "🆕 Начать новую без розыгрыша",
                callback_data=f"raffle:new_warn:{cid}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows + extra)


def _new_campaign_warning_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚠️ Да, начать новую",
                    callback_data=f"raffle:new_confirm:{campaign_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Отмена",
                    callback_data=f"raffle:new_cancel:{campaign_id}",
                )
            ],
        ]
    )


async def build_user_card(campaign_id: int, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    detail = await get_participant_admin_detail(campaign_id, user_id)
    if not detail:
        return (
            f"❌ Пользователь <code>{user_id}</code> не найден.",
            _tab_keyboard("overview", campaign_id),
        )

    username = detail.get("username")
    uname = f"@{username}" if username else "—"
    blocked = detail.get("accrual_blocked")
    status = "🚫 начисление выключено" if blocked else "✅ начисление включено"
    lines = [
        f"👤 <b>Пользователь</b> <code>{user_id}</code> {uname}",
        f"{status}",
        "",
        f"Билеты: <b>{detail['tickets_total']}</b> "
        f"(свои {detail['tickets_own']} / реф {detail['tickets_referral']})",
        f"Шанс: <b>{detail['win_chance_label']}</b>",
        f"Номера: {detail['ticket_numbers']}",
        "",
        f"Объём свой: {float(detail.get('own_volume_rub') or 0):,.0f} ₽".replace(",", " "),
        f"Объём реф: {float(detail.get('referral_volume_rub') or 0):,.0f} ₽".replace(",", " "),
    ]

    if blocked:
        block_btn = InlineKeyboardButton(
            "✅ Включить начисление",
            callback_data=f"raffle:unblock:{user_id}:{campaign_id}",
        )
    else:
        block_btn = InlineKeyboardButton(
            "🚫 Выключить начисление",
            callback_data=f"raffle:block:{user_id}:{campaign_id}",
        )

    keyboard = InlineKeyboardMarkup(
        [
            [block_btn],
            [
                InlineKeyboardButton(
                    "◀️ К участникам",
                    callback_data=f"raffle:parts:0:{campaign_id}",
                )
            ],
        ]
    )
    return "\n".join(lines), keyboard


async def raffle_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _admin_ok(update):
        return
    context.chat_data.pop("raffle_state", None)
    campaign = await get_campaign_for_admin()
    if not campaign:
        await update.message.reply_text("Нет кампаний FocusLucky.")
        return
    context.chat_data["raffle_campaign_id"] = campaign["id"]
    text = await build_overview_text(campaign)
    await _panel_send_or_edit(
        context,
        update.effective_chat.id,
        text,
        reply_markup=_tab_keyboard("overview", campaign["id"]),
    )


async def raffle_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not _admin_ok(update):
        return
    await query.answer()
    context.chat_data["raffle_panel_chat_id"] = query.message.chat_id
    context.chat_data["raffle_panel_message_id"] = query.message.message_id

    data = query.data or ""
    if not data.startswith("raffle:"):
        return

    parts = data.split(":")
    action = parts[1]
    chat_id = query.message.chat_id
    admin_id = update.effective_user.id if update.effective_user else 0

    campaign = await _resolve_campaign(context)
    if not campaign and action not in ("cancel_edit",):
        await _panel_send_or_edit(context, chat_id, "❌ Кампания не найдена.")
        return

    campaign_id = int(campaign["id"]) if campaign else 0

    if action == "overview":
        text = await build_overview_text(campaign)
        await _panel_send_or_edit(
            context, chat_id, text, reply_markup=_tab_keyboard("overview", campaign_id)
        )
        return

    if action == "parts":
        page = int(parts[2]) if len(parts) > 2 else 0
        if len(parts) > 3:
            campaign_id = int(parts[3])
        text, markup = await build_participants_text(
            await _campaign_by_id(context, campaign_id), page
        )
        await _panel_send_or_edit(context, chat_id, text, reply_markup=markup)
        return

    if action == "text":
        text = build_text_tab(campaign)
        await _panel_send_or_edit(
            context, chat_id, text, reply_markup=_text_keyboard(campaign_id)
        )
        return

    if action == "actions":
        text = build_actions_tab(campaign)
        await _panel_send_or_edit(
            context, chat_id, text, reply_markup=_actions_keyboard(campaign)
        )
        return

    if action == "new_warn":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        stats = await get_campaign_stats(cid)
        await _panel_send_or_edit(
            context,
            chat_id,
            (
                "⚠️ <b>Начать новую кампанию без розыгрыша?</b>\n\n"
                "Победители определены не будут. Выплат не будет.\n"
                "Все билеты текущей кампании обнулятся для новой кампании.\n\n"
                f"Сейчас участников: <b>{stats.get('participants', 0)}</b>\n"
                f"Билетов: <b>{stats.get('pool_total', 0)}</b>\n\n"
                "Это действие требует отдельного подтверждения."
            ),
            reply_markup=_new_campaign_warning_keyboard(cid),
        )
        return

    if action == "new_cancel":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        camp = await _campaign_by_id(context, cid)
        await _panel_send_or_edit(
            context,
            chat_id,
            "Действие отменено.\n\n" + build_actions_tab(camp),
            reply_markup=_actions_keyboard(camp),
        )
        return

    if action == "new_confirm":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        try:
            new_campaign = await start_new_campaign_without_draw(cid)
        except ValueError as exc:
            await _panel_send_or_edit(
                context,
                chat_id,
                f"❌ {html.escape(str(exc))}",
            )
            return
        context.chat_data["raffle_campaign_id"] = int(new_campaign["id"])
        text = (
            "✅ <b>Новая кампания запущена</b>\n\n"
            "Предыдущая закрыта без определения победителей и без выплат.\n"
            "Билеты новой кампании начинаются с нуля.\n\n"
            + await build_overview_text(new_campaign)
        )
        await _panel_send_or_edit(
            context,
            chat_id,
            text,
            reply_markup=_tab_keyboard("overview", int(new_campaign["id"])),
        )
        return

    if action == "find":
        context.chat_data["raffle_state"] = "find_user"
        context.chat_data["raffle_campaign_id"] = campaign_id
        await _panel_send_or_edit(
            context,
            chat_id,
            "Введите <code>user_id</code> Telegram:",
            reply_markup=_cancel_keyboard(campaign_id),
        )
        return

    if action == "edit_info":
        context.chat_data["raffle_state"] = "edit_info"
        context.chat_data["raffle_campaign_id"] = campaign_id
        await _panel_send_or_edit(
            context,
            chat_id,
            "Отправьте новый текст описания (внизу экрана FocusLucky).\n\n"
            f"Текущий дефолт:\n<pre>{html.escape(get_default_info_text())}</pre>",
            reply_markup=_cancel_keyboard(campaign_id),
        )
        return

    if action == "edit_how":
        context.chat_data["raffle_state"] = "edit_how"
        context.chat_data["raffle_campaign_id"] = campaign_id
        await _panel_send_or_edit(
            context,
            chat_id,
            "Отправьте новый текст «Как получить билеты» (HTML).\n\n"
            f"Текущий дефолт:\n<pre>{html.escape(get_default_how_to_text())}</pre>",
            reply_markup=_cancel_keyboard(campaign_id),
        )
        return

    if action == "reset_info":
        await update_campaign_text(campaign_id, clear_info=True)
        camp = await _campaign_by_id(context, campaign_id)
        await _panel_send_or_edit(
            context,
            chat_id,
            build_text_tab(camp),
            reply_markup=_text_keyboard(campaign_id),
        )
        return

    if action == "reset_how":
        await update_campaign_text(campaign_id, clear_how=True)
        camp = await _campaign_by_id(context, campaign_id)
        await _panel_send_or_edit(
            context,
            chat_id,
            build_text_tab(camp),
            reply_markup=_text_keyboard(campaign_id),
        )
        return

    if action == "cancel_edit":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        context.chat_data.pop("raffle_state", None)
        camp = await _campaign_by_id(context, cid)
        text = await build_overview_text(camp)
        await _panel_send_or_edit(
            context, chat_id, text, reply_markup=_tab_keyboard("overview", cid)
        )
        return

    if action == "user":
        uid = int(parts[2])
        cid = int(parts[3]) if len(parts) > 3 else campaign_id
        text, markup = await build_user_card(cid, uid)
        await _panel_send_or_edit(context, chat_id, text, reply_markup=markup)
        return

    if action == "block":
        uid = int(parts[2])
        cid = int(parts[3]) if len(parts) > 3 else campaign_id
        await set_accrual_blocked(cid, uid, True, blocked_by=admin_id)
        text, markup = await build_user_card(cid, uid)
        await _panel_send_or_edit(context, chat_id, text, reply_markup=markup)
        return

    if action == "unblock":
        uid = int(parts[2])
        cid = int(parts[3]) if len(parts) > 3 else campaign_id
        await set_accrual_blocked(cid, uid, False)
        text, markup = await build_user_card(cid, uid)
        await _panel_send_or_edit(context, chat_id, text, reply_markup=markup)
        return

    if action == "close":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        ok = await close_campaign(cid)
        camp = await _campaign_by_id(context, cid)
        msg = "✅ Начисление закрыто." if ok else "❌ Не удалось закрыть."
        await _panel_send_or_edit(
            context,
            chat_id,
            msg + "\n\n" + build_actions_tab(camp),
            reply_markup=_actions_keyboard(camp),
        )
        return

    if action == "activate":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        ok = await activate_campaign(cid)
        camp = await _campaign_by_id(context, cid)
        msg = "✅ Кампания активирована." if ok else "❌ Не удалось активировать."
        await _panel_send_or_edit(
            context,
            chat_id,
            msg + "\n\n" + build_actions_tab(camp),
            reply_markup=_actions_keyboard(camp),
        )
        return

    if action == "draw":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        camp = await _campaign_by_id(context, cid)
        if camp and camp["status"] == "active":
            await close_campaign(cid)
        try:
            result = await start_show(cid)
        except ValueError as e:
            await _panel_send_or_edit(context, chat_id, f"❌ {html.escape(str(e))}")
            return
        except Exception:
            await _panel_send_or_edit(context, chat_id, "❌ Ошибка запуска шоу")
            return
        lines = [
            f"🎬 <b>Шоу запущено</b> #{cid}",
            "Места крутятся сами. Смотреть /casino/play/raffle",
            "",
        ]
        camp = await _campaign_by_id(context, cid)
        await _panel_send_or_edit(
            context,
            chat_id,
            "\n".join(lines) + "\n\n" + build_actions_tab(camp),
            reply_markup=_actions_keyboard(camp),
        )
        return

    if action == "pay":
        cid = int(parts[2]) if len(parts) > 2 else campaign_id
        try:
            paid = await pay_balance_winners(cid)
        except Exception as e:
            await _panel_send_or_edit(context, chat_id, f"❌ {html.escape(str(e))}")
            return
        if not paid:
            await _panel_send_or_edit(context, chat_id, "Нет pending balance-призов.")
            return
        lines = [f"✅ Начислено на баланс: {len(paid)} победителей"]
        from services.raffle_constants import format_place_label, format_prize_rub

        for w in paid:
            lines.append(
                f"  {format_place_label(int(w['place']))} · user {w['user_id']} · "
                f"{format_prize_rub(w['prize_rub'])}"
            )
        camp = await _campaign_by_id(context, cid)
        await _panel_send_or_edit(
            context,
            chat_id,
            "\n".join(lines) + "\n\n" + build_actions_tab(camp),
            reply_markup=_actions_keyboard(camp),
        )
        return


async def _campaign_by_id(context: ContextTypes.DEFAULT_TYPE, campaign_id: int) -> dict:
    from services.raffle_db import get_campaign_by_id

    camp = await get_campaign_by_id(campaign_id)
    if camp:
        context.chat_data["raffle_campaign_id"] = campaign_id
        return camp
    raise ValueError("campaign not found")


async def raffle_panel_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _admin_ok(update):
        return
    msg = update.message
    if not msg or not msg.text or msg.text.strip().startswith("/"):
        return

    state = context.chat_data.get("raffle_state")
    if not state:
        return

    chat_id = update.effective_chat.id
    try:
        await msg.delete()
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)

    text = msg.text.strip()
    campaign_id = int(context.chat_data.get("raffle_campaign_id") or 0)

    if state == "find_user":
        if not text.isdigit():
            await _panel_send_or_edit(
                context, chat_id, "❌ Введите числовой user_id."
            )
            return
        context.chat_data.pop("raffle_state", None)
        uid = int(text)
        body, markup = await build_user_card(campaign_id, uid)
        await _panel_send_or_edit(context, chat_id, body, reply_markup=markup)
        return

    if state == "edit_info":
        await update_campaign_text(campaign_id, info_text=text)
        context.chat_data.pop("raffle_state", None)
        camp = await _campaign_by_id(context, campaign_id)
        await _panel_send_or_edit(
            context,
            chat_id,
            "✅ Описание сохранено.\n\n" + build_text_tab(camp),
            reply_markup=_text_keyboard(campaign_id),
        )
        return

    if state == "edit_how":
        await update_campaign_text(campaign_id, how_to_text=text)
        context.chat_data.pop("raffle_state", None)
        camp = await _campaign_by_id(context, campaign_id)
        await _panel_send_or_edit(
            context,
            chat_id,
            "✅ Текст сохранён.\n\n" + build_text_tab(camp),
            reply_markup=_text_keyboard(campaign_id),
        )
        return

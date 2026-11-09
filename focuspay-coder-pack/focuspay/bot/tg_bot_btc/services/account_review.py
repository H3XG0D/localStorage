"""Ручная проверка подозрительного аккаунта до выдачи Payfast-реквизитов."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

logger = logging.getLogger("account_review")


async def _avatar_info(bot, user_id: int) -> tuple[bool | None, int]:
    """(has_avatar, photo_count). has_avatar=None при ошибке API."""
    if bot is None:
        return None, 0
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        total = int(getattr(photos, "total_count", 0) or 0)
        return total > 0, total
    except Exception as e:
        logger.debug("get_user_profile_photos failed user=%s: %s", user_id, e)
        return None, 0


async def ensure_account_review_or_block(
    *,
    user_id: int,
    bot,
    username: str | None = None,
    first_name: str | None = None,
    wallet: str | None = None,
    is_premium: bool | None = None,
    fiat_amount: float | int | None = None,
    crypto: str | None = None,
    crypto_amount: float | None = None,
    network: str | None = None,
    amount_currency: str | None = None,
) -> tuple[bool, str | None]:
    """
    Проверить, можно ли выдавать реквизиты.

    Returns (allowed, client_message_html).
    allowed=False → реквизиты не выдаём; client_message для пользователя.
    """
    from services.buyer_access_guards import (
        format_account_review_pending_message,
        format_account_review_rejected_message,
        is_suspicious_account,
    )
    from services.buyer_risk import needs_account_review
    from services.db import (
        ensure_bot_user,
        find_wallet_reuse,
        get_bot_user,
        get_buyer_ops_stats,
        set_account_review_status,
    )

    await ensure_bot_user(user_id, username=username, first_name=first_name)
    bot_user = await get_bot_user(user_id)
    stats = await get_buyer_ops_stats(user_id)
    paid_count = int(stats.get("paid_count") or 0)

    status = "none"
    if bot_user:
        status = str(bot_user.get("account_review_status") or "none")

    if status == "rejected":
        return False, format_account_review_rejected_message()

    if status == "approved" or paid_count > 0:
        return True, None

    has_avatar, avatar_count = await _avatar_info(bot, user_id)
    reuse_rows: list[dict] = []
    if wallet and str(wallet).strip():
        try:
            reuse_rows = await find_wallet_reuse(str(wallet).strip(), user_id)
        except Exception as e:
            logger.warning("find_wallet_reuse failed user=%s: %s", user_id, e)

    from services.tg_account_age import estimate_age_days

    account_age_days = estimate_age_days(user_id)

    reasons = is_suspicious_account(
        bot_user,
        paid_count,
        has_avatar=has_avatar,
        first_name=first_name,
        wallet_reuse=bool(reuse_rows),
        is_premium=is_premium,
        account_age_days=account_age_days,
    )

    has_ref: bool | None = None
    try:
        from services.user_referral_attribution import user_has_attribution

        has_ref = await user_has_attribution(user_id)
    except Exception as e:
        logger.debug("user_has_attribution failed user=%s: %s", user_id, e)

    fiat_f = float(fiat_amount) if fiat_amount is not None else None
    if not needs_account_review(
        reasons,
        has_referral=has_ref,
        amount_currency=amount_currency,
        fiat_amount=fiat_f,
    ):
        return True, None

    # Обогащаем reasons для ops-карточки (холодный комбо / маркеры сделки).
    from services.buyer_access_guards import REASON_NO_REFERRAL, REASON_ROUND_RUB
    from services.buyer_risk import is_round_rub_input

    if has_ref is False and REASON_NO_REFERRAL not in reasons:
        reasons = [*reasons, REASON_NO_REFERRAL]
    if is_round_rub_input(amount_currency, fiat_f) and REASON_ROUND_RUB not in reasons:
        reasons = [*reasons, REASON_ROUND_RUB]

    if status == "pending":
        # Уже ждём решения — повторно шлём обогащённую карточку (сумма могла
        # измениться), чтобы оператору было что смотреть.
        await notify_ops_account_review(
            user_id=user_id,
            bot=bot,
            username=username,
            first_name=first_name,
            reasons=reasons,
            wallet=wallet,
            wallet_reuse_rows=reuse_rows,
            is_premium=is_premium,
            has_avatar=has_avatar,
            avatar_count=avatar_count,
            fiat_amount=fiat_amount,
            crypto=crypto,
            crypto_amount=crypto_amount,
            network=network,
            amount_currency=amount_currency,
            bot_user=bot_user,
            ops_stats=stats,
            account_age_days=account_age_days,
            resend=True,
        )
        return False, format_account_review_pending_message()

    await set_account_review_status(
        user_id,
        "pending",
        reason=",".join(reasons),
    )
    await notify_ops_account_review(
        user_id=user_id,
        bot=bot,
        username=username,
        first_name=first_name,
        reasons=reasons,
        wallet=wallet,
        wallet_reuse_rows=reuse_rows,
        is_premium=is_premium,
        has_avatar=has_avatar,
        avatar_count=avatar_count,
        fiat_amount=fiat_amount,
        crypto=crypto,
        crypto_amount=crypto_amount,
        network=network,
        amount_currency=amount_currency,
        bot_user=bot_user,
        ops_stats=stats,
        account_age_days=account_age_days,
    )
    return False, format_account_review_pending_message()


def _format_wallet_reuse_html(rows: list[dict] | None) -> str:
    """Список чужих аккаунтов с тем же кошельком (ops + t.me)."""
    if not rows:
        return ""
    from services.order_ops_notify import operator_client_url

    bits: list[str] = []
    for r in rows[:5]:
        uid = int(r.get("user_id") or 0)
        uname = (r.get("username") or "").strip().lstrip("@")
        oid = html.escape(str(r.get("order_id") or ""))
        st = html.escape(str(r.get("status") or ""))
        profile = operator_client_url(uid) if uid else ""
        parts: list[str] = []
        if uname and profile and uid > 0:
            parts.append(
                f'<a href="{html.escape(profile)}">@{html.escape(uname)}</a>'
            )
            parts.append(
                f'<a href="https://t.me/{html.escape(uname)}">'
                f"t.me/{html.escape(uname)}</a>"
            )
        elif uname and profile:
            parts.append(
                f'<a href="{html.escape(profile)}">@{html.escape(uname)}</a>'
            )
        elif uname:
            parts.append(f"@{html.escape(uname)}")
        elif profile:
            parts.append(f'<a href="{html.escape(profile)}">id {uid}</a>')
            if uid > 0:
                parts.append(f'<a href="tg://user?id={uid}">Telegram</a>')
        else:
            parts.append(f"id {uid}")
        if oid:
            parts.append(f"заявка <code>{oid}</code>")
            if st:
                parts.append(f"({st})")
        bits.append(" · ".join(parts))
    return ", ".join(bits)


def _mark(ok: bool | None) -> str:
    if ok is True:
        return "✅"
    if ok is False:
        return "❌"
    return "❔"


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    return html.escape(str(dt)[:19])


def _fmt_dt_short(dt) -> str:
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%d.%m.%Y")
    return html.escape(str(dt)[:10])


def _fmt_start_age_checklist(first_seen) -> str:
    """«21 дн назад (06.07.2026)» для чеклиста."""
    from services.buyer_access_guards import format_account_age_hours

    _, age_label = format_account_age_hours(first_seen)
    date_s = _fmt_dt_short(first_seen)
    # Нормализуем «21.0д назад» → «21 дн назад»
    label = age_label.replace("д назад", " дн назад").replace("ч назад", " ч назад")
    label = label.replace(".0 ", " ")
    if first_seen:
        return f"{html.escape(label)} ({date_s})"
    return html.escape(label)


def _fmt_tg_age_checklist(account_age_days: int | None) -> str:
    if account_age_days is None:
        return "неизвестно"
    d = int(account_age_days)
    if d < 1:
        return "меньше суток (по ID)"
    if d < 30:
        return f"~{d} дн (по ID)"
    if d < 365:
        months = max(1, d // 30)
        return f"~{months} мес (по ID)"
    years = d / 365.0
    if years < 1.5:
        return "~1 год (по ID)"
    y = int(round(years))
    if y % 10 == 1 and y % 100 != 11:
        return f"~{y} год (по ID)"
    if 2 <= y % 10 <= 4 and not (12 <= y % 100 <= 14):
        return f"~{y} года (по ID)"
    return f"~{y} лет (по ID)"


def _build_checklist_html(
    *,
    bot_user: dict | None,
    reasons: list[str],
    has_avatar: bool | None,
    avatar_count: int,
    is_premium: bool | None,
    first_name: str | None,
    wallet_reuse: bool,
    has_ref: bool,
    account_age_days: int | None = None,
    wallet_reuse_rows: list[dict] | None = None,
    attribution_label: str | None = None,
    membership: dict | None = None,
) -> list[str]:
    from services.buyer_access_guards import (
        REASON_FRESH_ACCOUNT,
        REASON_NO_USERNAME,
        REASON_TG_NEW,
        REASON_USERNAME_CHANGED,
        REASON_WALLET_REUSE,
        REASON_WEAK_NAME,
        _weak_first_name,
    )

    bu = bot_user or {}
    uname = (str(bu.get("username") or "").strip().lstrip("@")) or ""
    prev = (str(bu.get("previous_username") or "").strip().lstrip("@")) or ""
    name = (first_name if first_name is not None else bu.get("first_name")) or ""
    first_seen = bu.get("first_seen_at")

    lines = ["📋 <b>Чеклист безопасности</b>"]

    # name
    if _weak_first_name(name):
        shown = html.escape(name) if name else "пусто"
        lines.append(f"❌ Имя: слабое ({shown})")
    else:
        lines.append(f"✅ Имя: {html.escape(str(name))}")

    # username
    if REASON_NO_USERNAME in reasons or not uname:
        lines.append("❌ Username: нет")
    else:
        lines.append(f"✅ Username: @{html.escape(uname)}")

    # /start age
    if REASON_FRESH_ACCOUNT in reasons:
        lines.append(f"❌ /start: {_fmt_start_age_checklist(first_seen)}")
    elif first_seen:
        lines.append(f"✅ /start: {_fmt_start_age_checklist(first_seen)}")
    else:
        lines.append("❔ /start: нет first_seen_at")

    # TG account age by user_id
    tg_age_label = _fmt_tg_age_checklist(account_age_days)
    if REASON_TG_NEW in reasons or (
        account_age_days is not None and int(account_age_days) < 7
    ):
        lines.append(f"❌ Возраст TG: {html.escape(tg_age_label)}")
    elif account_age_days is not None:
        lines.append(f"✅ Возраст TG: {html.escape(tg_age_label)}")
    else:
        lines.append("❔ Возраст TG: неизвестно")

    # username change
    if REASON_USERNAME_CHANGED in reasons:
        lines.append(
            f"❌ Смена ника: было @{html.escape(prev)} → @{html.escape(uname)}"
        )
    else:
        lines.append("✅ Смена ника: нет")

    # wallet
    reuse_who = _format_wallet_reuse_html(wallet_reuse_rows)
    if wallet_reuse or REASON_WALLET_REUSE in reasons:
        if reuse_who:
            lines.append(f"❌ Кошелёк: уже у {reuse_who}")
        else:
            lines.append("❌ Кошелёк: уже у другого аккаунта")
    else:
        lines.append("✅ Кошелёк: совпадений нет")

    # referral
    if attribution_label:
        mark = "✅" if has_ref else "❌"
        lines.append(
            f"{mark} Реферал/промо: {html.escape(str(attribution_label))}"
        )
    else:
        lines.append(
            f"{_mark(has_ref)} Реферал/промо: {'да' if has_ref else 'нет'}"
        )

    # premium
    if is_premium is True:
        lines.append("✅ TG Premium: есть")
    elif is_premium is False:
        lines.append("❌ TG Premium: нет")
    else:
        lines.append("❔ TG Premium: неизвестно")

    from services.chat_membership import format_membership_checklist_lines

    lines.extend(format_membership_checklist_lines(membership))

    # avatar — только если проблема (не засоряем чеклист)
    if has_avatar is False:
        lines.append("❌ Аватар: нет")
    elif REASON_WEAK_NAME not in reasons and has_avatar is True and avatar_count:
        pass  # ок, не показываем

    return lines


async def notify_ops_account_review(
    *,
    user_id: int,
    bot,
    username: str | None = None,
    first_name: str | None = None,
    reasons: list[str],
    wallet: str | None = None,
    wallet_reuse_rows: list[dict] | None = None,
    is_premium: bool | None = None,
    has_avatar: bool | None = None,
    avatar_count: int = 0,
    fiat_amount: float | int | None = None,
    crypto: str | None = None,
    crypto_amount: float | None = None,
    network: str | None = None,
    amount_currency: str | None = None,
    bot_user: dict | None = None,
    ops_stats: dict | None = None,
    account_age_days: int | None = None,
    resend: bool = False,
) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error import BadRequest

    from services import config_rates
    from services.buyer_risk import account_review_title, is_round_rub_input
    from services.callback_signatures import sign_account_review
    from services.db import get_bot_user, get_buyer_ops_stats
    from services.order_ops_notify import (
        OPS_MSG_SEPARATOR,
        format_device_signal_lines,
        format_ops_crypto_amount_html,
        format_ops_user_line,
        ops_client_link_specs,
    )

    chat_id = config_rates.client_review_group_id()
    if not chat_id:
        chat_id = config_rates.ops_group_id()
        logger.warning(
            "client review group not set — fallback ops group user=%s", user_id
        )
    if not chat_id:
        logger.warning("account review notify skipped: no group user=%s", user_id)
        return

    if bot_user is None:
        bot_user = await get_bot_user(user_id)
    if ops_stats is None:
        ops_stats = await get_buyer_ops_stats(user_id)

    review_signature = sign_account_review(user_id)
    uname = (username or (bot_user or {}).get("username") or "").strip().lstrip("@")
    fname = first_name or (bot_user or {}).get("first_name")
    user_line = format_ops_user_line(
        user_id, first_name=fname, username=uname or None, include_id=True
    )

    has_ref = False
    attribution_label: str | None = None
    try:
        from services.user_referral_attribution import get_attribution_details

        attr = await get_attribution_details(user_id)
        has_ref = bool(attr.get("has"))
        attribution_label = str(attr.get("label") or "") or None
    except Exception as e:
        logger.debug("get_attribution_details failed user=%s: %s", user_id, e)

    # --- сделка ---
    deal_lines = ["🔄 <b>Сделка (ждёт реквизиты)</b>"]
    if fiat_amount is not None or crypto:
        crypto_u = html.escape(str(crypto or "?").upper().split("_")[0])
        fiat_s = (
            f"{float(fiat_amount):,.0f}".replace(",", " ")
            if fiat_amount is not None
            else "—"
        )
        crypto_s = ""
        if crypto_amount is not None:
            crypto_s = f" · {format_ops_crypto_amount_html(crypto_amount, str(crypto or 'btc'))}"
        input_hint = ""
        cur = (amount_currency or "").strip().lower()
        if cur == "rub":
            roundish = is_round_rub_input(cur, float(fiat_amount or 0))
            input_hint = " · ввод в рублях" + (" ⚠" if roundish else "")
        elif cur == "crypto":
            input_hint = " · ввод в крипте"
        deal_lines.append(f"BUY {crypto_u} · <b>{fiat_s} ₽</b>{crypto_s}{input_hint}")
    else:
        deal_lines.append("<i>сумма не передана в уведомление</i>")
    if wallet and str(wallet).strip():
        deal_lines.append(
            f"👛 <code>{html.escape(str(wallet).strip())}</code>"
        )
    reuse_line = _format_wallet_reuse_html(wallet_reuse_rows)
    if reuse_line:
        deal_lines.append("Кошелёк уже у: " + reuse_line)

    # --- статистика ---
    paid = int((ops_stats or {}).get("paid_count") or 0)
    vol = float((ops_stats or {}).get("total_volume_rub") or 0)
    stats_line = (
        f"📊 В боте · PAID: <b>{paid}</b> · объём {vol:,.0f} ₽".replace(",", " ")
    )

    if account_age_days is None:
        try:
            from services.tg_account_age import estimate_age_days

            account_age_days = estimate_age_days(user_id)
        except Exception:
            account_age_days = None

    membership: dict | None = None
    try:
        from services.chat_membership import public_chat_membership

        membership = await public_chat_membership(bot, user_id)
    except Exception as e:
        logger.debug("public_chat_membership failed user=%s: %s", user_id, e)

    checklist = _build_checklist_html(
        bot_user=dict(bot_user) if bot_user else None,
        reasons=reasons,
        has_avatar=has_avatar,
        avatar_count=avatar_count,
        is_premium=is_premium,
        first_name=fname,
        wallet_reuse=bool(wallet_reuse_rows),
        has_ref=has_ref,
        account_age_days=account_age_days,
        wallet_reuse_rows=wallet_reuse_rows,
        attribution_label=attribution_label,
        membership=membership,
    )

    # мини-апп — последний сигнал пользователя (если есть)
    device_block: list[str] = []
    try:
        from services.db import get_latest_device_signal_for_user

        device_signal = await get_latest_device_signal_for_user(user_id)
        if device_signal:
            fake_order = {
                "user_id": user_id,
                "device_signal": {
                    "ip": device_signal.get("ip"),
                    "fingerprint": device_signal.get("fingerprint"),
                    "platform": device_signal.get("platform"),
                    "screen": device_signal.get("screen"),
                    "timezone": device_signal.get("timezone"),
                },
                "payment_snapshot": {
                    "attribution_label": attribution_label,
                },
            }
            # обогатить reuse из сигнала, если есть в bot/ops
            device_block = format_device_signal_lines(fake_order)
            if not any("Реферал" in x for x in device_block) and attribution_label:
                device_block.append(
                    f"🎯 Реферал: {html.escape(str(attribution_label))}"
                )
    except Exception as e:
        logger.debug("device signal for account review: %s", e)
        if attribution_label:
            device_block = [
                "ℹ️ <b>Данные мини-аппа</b>",
                f"🎯 Реферал: {html.escape(str(attribution_label))}",
            ]

    resend_note = "\n<i>↻ повторная попытка получить реквизиты</i>\n" if resend else ""
    parts = [
        f"<b>{account_review_title(reasons)}</b>",
        OPS_MSG_SEPARATOR,
        resend_note,
        user_line,
        "",
        *deal_lines,
        "",
        *checklist,
    ]
    if device_block:
        parts.append("")
        parts.extend(device_block)
    parts.append("")
    parts.append(stats_line)
    parts.append("")
    parts.append("Одобрите, чтобы клиент получил реквизиты")
    text = "\n".join(p for p in parts if p is not None)
    client_links = [
        InlineKeyboardButton(label, url=url)
        for label, url in ops_client_link_specs(user_id, uname or None)
    ]

    def _review_markup(links: list) -> InlineKeyboardMarkup:
        rows = [links] if links else []
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "✅ Одобрить",
                        callback_data=f"areview:ok:{user_id}:{review_signature}",
                    ),
                    InlineKeyboardButton(
                        "🔇 Тихий блок",
                        callback_data=f"areview:soft:{user_id}:{review_signature}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Бан",
                        callback_data=f"areview:no:{user_id}:{review_signature}",
                    ),
                ],
            ]
        )
        return InlineKeyboardMarkup(rows)

    keyboard = _review_markup(client_links)

    async def _send(markup: InlineKeyboardMarkup | None) -> None:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    try:
        await _send(keyboard)
    except BadRequest as e:
        logger.warning("account review ops notify failed user=%s: %s", user_id, e)
        http_links = [
            b for b in client_links if not str(getattr(b, "url", "") or "").startswith("tg://")
        ]
        try:
            if len(http_links) != len(client_links):
                await _send(_review_markup(http_links))
                return
        except Exception as retry_error:
            logger.warning(
                "account review tg-url retry failed user=%s: %s",
                user_id,
                retry_error,
            )
        try:
            await _send(None)
        except Exception as fallback_error:
            logger.warning(
                "account review fallback failed user=%s: %s",
                user_id,
                fallback_error,
            )
    except Exception as e:
        logger.warning("account review ops notify failed user=%s: %s", user_id, e)


async def approve_account_review(user_id: int, operator_id: int) -> tuple[bool, str]:
    from services.db import get_bot_user, set_account_review_status

    row = await get_bot_user(user_id)
    if not row:
        return False, "user_not_found"
    status = str(row.get("account_review_status") or "none")
    if status == "approved":
        return True, "already_approved"
    ok = await set_account_review_status(
        user_id,
        "approved",
        reason="ops_approved",
        operator_id=operator_id,
    )
    if not ok:
        return False, "update_failed"
    return True, "ok"


async def reject_account_review(
    user_id: int,
    operator_id: int,
    *,
    ban: bool = True,
    ban_type: str = "hard",
) -> tuple[bool, str]:
    from services.db import ban_user, get_bot_user, set_account_review_status

    row = await get_bot_user(user_id)
    if not row:
        return False, "user_not_found"
    status = str(row.get("account_review_status") or "none")
    if status == "rejected":
        # уже отклонён — всё равно можно добить soft/hard бан
        if ban:
            await ban_user(
                user_id,
                reason="account_review_rejected",
                operator_id=operator_id,
                ban_type=ban_type if ban_type in ("hard", "soft") else "hard",
            )
        return True, "already_rejected"
    ok = await set_account_review_status(
        user_id,
        "rejected",
        reason="ops_rejected_soft" if ban_type == "soft" else "ops_rejected",
        operator_id=operator_id,
    )
    if not ok:
        return False, "update_failed"
    if ban:
        await ban_user(
            user_id,
            reason="account_review_rejected",
            operator_id=operator_id,
            ban_type=ban_type if ban_type in ("hard", "soft") else "hard",
        )
    return True, "ok"


async def soft_block_account_review(user_id: int, operator_id: int) -> tuple[bool, str]:
    """Тихий блок: реквизиты не выдаются, клиенту ничего про проверку не пишем."""
    return await reject_account_review(
        user_id, operator_id, ban=True, ban_type="soft"
    )

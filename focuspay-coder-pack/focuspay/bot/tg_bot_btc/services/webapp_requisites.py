"""Mini App: выдача реквизитов + fingerprint/IP antifraud."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any
from services.payment_snapshot import order_payment_snapshot

logger = logging.getLogger("webapp_requisites")


def _parse_snap(order: dict) -> dict:
    return order_payment_snapshot(order)


def _bill(order: dict) -> dict | None:
    bill = _parse_snap(order).get("bill")
    return bill if isinstance(bill, dict) else None


def _client_deny_message() -> str:
    return (
        "❌ Нет реквизитов на нужную сумму.\n\n"
        "Напишите оператору: @focus_operator"
    )


def _payfast_requisites_closed(order: dict, snap: dict) -> tuple[bool, int | None]:
    if int(order.get("required_receipt_type") or 0) == 3:
        return False, None
    merchant_raw = snap.get("merchant_expires_at")
    requisites_end = order.get("expires_at")
    if not merchant_raw or not requisites_end:
        return False, None
    try:
        merchant_end = datetime.fromisoformat(str(merchant_raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False, None
    if merchant_end.tzinfo is None:
        merchant_end = merchant_end.replace(tzinfo=timezone.utc)
    if requisites_end.tzinfo is None:
        requisites_end = requisites_end.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    merchant_end = merchant_end.astimezone(timezone.utc)
    if now < requisites_end.astimezone(timezone.utc):
        return False, None
    return True, max(0, int((merchant_end - now).total_seconds()))


def _requisites_closed_message(remaining_sec: int | None) -> str:
    if remaining_sec is not None and remaining_sec > 0:
        minutes = max(1, (int(remaining_sec) + 59) // 60)
        return (
            "⏰ Реквизиты закрыты.\n\n"
            "Если вы уже сделали перевод, у вас есть ещё "
            f"≈{minutes} мин., чтобы написать оператору.\n"
            "Иначе деньги могут быть утеряны.\n\n"
            "Напишите оператору: @focus_operator"
        )
    return "⏰ Время на оплату истекло. Напишите оператору: @focus_operator"


async def open_requisites(
    *,
    order_id: str,
    sig: str,
    init_data: str,
    fingerprint: str | None,
    signals: dict | None,
    client_ip: str | None,
    honeypot: str | None = None,
) -> dict[str, Any]:
    """
    Returns JSON-serializable dict:
      ok, blocked, bill, message, expires_at, fiat_amount, ...
    """
    from services import config_rates
    from services.callback_signatures import verify_order_signature
    from services.db import (
        count_fingerprint_users,
        find_fingerprint_reuse,
        find_ip_reuse,
        get_bot_user,
        get_buyer_ops_stats,
        get_order,
        is_popular_fingerprint,
        is_user_banned,
        merge_order_payment_snapshot,
        save_device_signal,
        serialize_reuse_matches,
        set_device_review_status,
        set_order_client_ip,
    )
    from services.merchant_api_helpers import cancel_payin_safe
    from services.tg_webapp_initdata import InitDataError, verify_webapp_init_data

    if (honeypot or "").strip():
        return {"ok": False, "blocked": True, "message": _client_deny_message(), "error": "bot"}

    if not verify_order_signature(order_id, sig or ""):
        return {"ok": False, "blocked": True, "message": _client_deny_message(), "error": "bad_sig"}

    try:
        idata = verify_webapp_init_data(
            init_data, config_rates.TELEGRAM_BOT_TOKEN, max_age_seconds=3600
        )
    except InitDataError as e:
        return {
            "ok": False,
            "blocked": True,
            "message": "Откройте реквизиты кнопкой внутри Telegram.",
            "error": f"init:{e}",
        }

    order = await get_order(order_id)
    if not order:
        return {"ok": False, "blocked": True, "message": _client_deny_message(), "error": "not_found"}

    uid = int(order.get("user_id") or 0)
    if uid != int(idata.user.id):
        return {"ok": False, "blocked": True, "message": _client_deny_message(), "error": "owner"}

    banned, _, ban_type = await is_user_banned(uid)
    if banned:
        return {"ok": False, "blocked": True, "message": _client_deny_message(), "error": "banned"}

    st = str(order.get("status") or "")
    snap = _parse_snap(order)
    requisites_closed, remaining_sec = _payfast_requisites_closed(order, snap)
    if requisites_closed:
        return {
            "ok": False,
            "blocked": True,
            "requisites_closed": True,
            "merchant_expires_at": snap.get("merchant_expires_at"),
            "message": _requisites_closed_message(remaining_sec),
            "error": "requisites_closed",
        }
    already = bool(snap.get("requisites_revealed_at"))

    if st not in ("CREATED", "AWAITING_CHECK") and not already:
        return {
            "ok": False,
            "blocked": True,
            "message": "Заявка больше не активна.",
            "error": "status",
        }

    sigs = signals if isinstance(signals, dict) else {}
    fp = (fingerprint or "").strip().lower() or None
    await save_device_signal(
        user_id=uid,
        order_id=order_id,
        fingerprint=fp,
        ip=client_ip,
        user_agent=str(sigs.get("user_agent") or "")[:500] or None,
        platform=str(sigs.get("platform") or "")[:120] or None,
        screen=str(sigs.get("screen") or "")[:80] or None,
        timezone=str(sigs.get("timezone") or "")[:80] or None,
        languages=sigs.get("languages") if isinstance(sigs.get("languages"), list) else None,
        extra={"source": "tg_webapp"},
    )
    if client_ip:
        await set_order_client_ip(order_id, client_ip)

    fp_rows: list[dict] = []
    ip_rows: list[dict] = []
    if fp:
        try:
            fp_rows = await find_fingerprint_reuse(fp, uid)
        except Exception as e:
            logger.debug("fp reuse: %s", e)
    if client_ip:
        try:
            ip_rows = await find_ip_reuse(client_ip, uid)
        except Exception as e:
            logger.debug("ip reuse: %s", e)

    fp_user_count = 0
    if fp:
        try:
            fp_user_count = await count_fingerprint_users(fp)
        except Exception as e:
            logger.debug("fp count: %s", e)
            fp_user_count = len({r["user_id"] for r in fp_rows}) + (1 if fp_rows else 1)

    # Старые FP (без v2:) часто одинаковы у одной модели iPhone в TG WebView.
    fp_common = bool(fp_rows) and is_popular_fingerprint(fp_user_count)
    fp_reuse = bool(fp_rows) and not fp_common
    ip_reuse = bool(ip_rows)
    reuse_count = len({r["user_id"] for r in fp_rows} | {r["user_id"] for r in ip_rows})

    def _reuse_snap_fields() -> dict[str, Any]:
        return {
            "device_fp_reuse": bool(fp_rows),  # факт совпадения (для ops)
            "device_fp_common": fp_common,  # когорта модели, не hard-signal
            "device_fp_user_count": fp_user_count,
            "device_ip_reuse": ip_reuse,
            "device_reuse_count": reuse_count,
            "device_fp_matches": serialize_reuse_matches(fp_rows),
            "device_ip_matches": serialize_reuse_matches(ip_rows),
        }

    stats = await get_buyer_ops_stats(uid)
    paid_count = int(stats.get("paid_count") or 0)
    bot_user = await get_bot_user(uid) or {}
    device_st = str(bot_user.get("device_review_status") or "none")

    def _bill_payload():
        bill = _bill(order) or {}
        return {
            "ok": True,
            "blocked": False,
            "bill": {
                "bank": bill.get("bank"),
                "reciver": bill.get("reciver"),
                "fio": bill.get("fio"),
            },
            "fiat_amount": float(order.get("fiat_amount") or 0),
            "crypto": order.get("crypto"),
            "expires_at": order.get("expires_at").isoformat()
            if hasattr(order.get("expires_at"), "isoformat")
            else order.get("expires_at"),
            "merchant_expires_at": snap.get("merchant_expires_at"),
            "requisites_closed": False,
            "order_id": order_id,
            "message": None,
        }

    # Already revealed or trusted → show
    if already or paid_count >= 1 or device_st == "approved" or st == "AWAITING_CHECK":
        patch = _reuse_snap_fields()
        if not already and st == "CREATED":
            patch["requisites_revealed_at"] = datetime.now(tz=timezone.utc).isoformat()
        await merge_order_payment_snapshot(order_id, patch)
        return _bill_payload()

    # New buyer + hard reuse → cancel + device review.
    # Популярный FP модели (общий у iPhone в TG) сам по себе НЕ блокирует — только IP
    # или редкий FP (пока один другой аккаунт с таким же хешем).
    if st == "CREATED" and (ip_reuse or fp_reuse):
        await merge_order_payment_snapshot(
            order_id,
            {
                **_reuse_snap_fields(),
                "device_review_pending": True,
            },
        )
        await set_device_review_status(
            uid,
            "pending",
            reason=(
                f"fp={fp_reuse},fp_common={fp_common},fp_users={fp_user_count},"
                f"ip={ip_reuse},count={reuse_count}"
            ),
        )
        try:
            await cancel_payin_safe(dict(order), allow_awaiting_check=False, update_local=True)
        except Exception as e:
            logger.warning("device reuse cancel failed order=%s: %s", order_id, e)
        try:
            await _notify_device_review(
                user_id=uid,
                order_id=order_id,
                fp_rows=fp_rows,
                ip_rows=ip_rows,
                fingerprint=fp,
                client_ip=client_ip,
                reuse_count=reuse_count,
            )
        except Exception as e:
            logger.warning("device review notify failed: %s", e)
        return {
            "ok": False,
            "blocked": True,
            "bill": None,
            "message": _client_deny_message(),
            "error": "device_review",
        }

    # Clean reveal
    await merge_order_payment_snapshot(
        order_id,
        {
            "requisites_revealed_at": datetime.now(tz=timezone.utc).isoformat(),
            **_reuse_snap_fields(),
        },
    )
    return _bill_payload()


async def _notify_device_review(
    *,
    user_id: int,
    order_id: str,
    fp_rows: list[dict],
    ip_rows: list[dict],
    fingerprint: str | None,
    client_ip: str | None,
    reuse_count: int,
) -> None:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.error import BadRequest

    from services import config_rates
    from services.callback_signatures import sign_device_review
    from services.db import get_bot_user
    from services.order_ops_notify import (
        OPS_MSG_SEPARATOR,
        format_ops_user_line,
        format_reuse_who_html,
        ops_client_link_specs,
    )

    chat_id = config_rates.client_review_group_id() or config_rates.ops_group_id()
    if not chat_id or not config_rates.TELEGRAM_BOT_TOKEN:
        return

    bu = await get_bot_user(user_id) or {}
    uname = (bu.get("username") or "").strip().lstrip("@") or None
    fname = (bu.get("first_name") or "").strip() or None

    others_lines: list[str] = []
    others_fp = format_reuse_who_html(fp_rows)
    others_ip = format_reuse_who_html(ip_rows)
    if others_fp:
        others_lines.append(f"⚠️ FP совпал с: {others_fp}")
    if others_ip:
        others_lines.append(f"⚠️ IP совпал с: {others_ip}")
    if not others_lines:
        others_lines.append("Совпадений с другими: —")

    fp_short = (fingerprint or "—")
    if len(fp_short) > 16:
        fp_short = fp_short[:16] + "…"

    sig = sign_device_review(user_id)
    text = "\n".join(
        [
            "<b>🛡 Проверка устройства · fingerprint/IP</b>",
            OPS_MSG_SEPARATOR,
            "",
            format_ops_user_line(
                user_id, first_name=fname, username=uname, include_id=True
            ),
            f"🆔 Заявка: <code>{html.escape(order_id)}</code> (отменена до выдачи реквизитов)",
            f"Совпадений с другими: <b>{reuse_count}</b>",
            "",
            "ℹ️ <b>Данные мини-аппа</b>",
            f"🌐 IP: <code>{html.escape(client_ip or '—')}</code>",
            f"🔏 FP: <code>{html.escape(fp_short)}</code>",
            *others_lines,
            "",
            "Одобрите, чтобы клиент мог снова получить реквизиты.",
        ]
    )
    client_links = [
        InlineKeyboardButton(label, url=url)
        for label, url in ops_client_link_specs(user_id, uname)
    ]

    def _device_markup(links: list) -> InlineKeyboardMarkup:
        rows = [links] if links else []
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "✅ Одобрить устройство",
                        callback_data=f"dreview:ok:{user_id}:{sig}",
                    ),
                    InlineKeyboardButton(
                        "🔇 Тихий блок",
                        callback_data=f"dreview:soft:{user_id}:{sig}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Бан",
                        callback_data=f"dreview:no:{user_id}:{sig}",
                    ),
                ],
            ]
        )
        return InlineKeyboardMarkup(rows)

    kb = _device_markup(client_links)
    bot = Bot(token=config_rates.TELEGRAM_BOT_TOKEN)

    async def _send(markup: InlineKeyboardMarkup | None) -> None:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    try:
        await _send(kb)
    except BadRequest as e:
        logger.warning("device review notify failed user=%s: %s", user_id, e)
        http_links = [
            b for b in client_links if not str(getattr(b, "url", "") or "").startswith("tg://")
        ]
        try:
            if len(http_links) != len(client_links):
                await _send(_device_markup(http_links))
                return
        except Exception as retry_error:
            logger.warning(
                "device review tg-url retry failed user=%s: %s",
                user_id,
                retry_error,
            )
        try:
            await _send(None)
        except Exception as fallback_error:
            logger.warning(
                "device review fallback failed user=%s: %s",
                user_id,
                fallback_error,
            )
    except Exception as e:
        logger.warning("device review notify failed user=%s: %s", user_id, e)

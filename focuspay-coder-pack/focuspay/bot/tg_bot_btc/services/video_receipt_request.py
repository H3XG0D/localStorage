"""Запрос PDF/видео у клиента (вебхук Payfast или сообщение в appeals-группе)."""
from __future__ import annotations

import logging

import requests

from services.db import get_order, mark_ops_alert_once, update_order_to_awaiting_check
from services.receipt_instructions import (
    receipt_request_message,
    receipt_success_status_request_message,
)

logger = logging.getLogger("video_receipt_request")

_RECEIPT_BLOCKED_STATUSES = frozenset({"PAID", "COMPLETED", "FAILED"})
_APPEALS_SUCCESS_SOURCE = "appeals_success_receipt"


async def request_client_receipt_check(
    order_id: str,
    req_type: int,
    *,
    bot=None,
    source: str = "webhook",
    allow_late: bool = False,
) -> tuple[bool, str]:
    """Перевести BUY-заявку в AWAITING_CHECK и попросить клиента прислать чек/видео."""
    order = await get_order(str(order_id).strip())
    if not order:
        return False, "order_not_found"

    if (order.get("direction") or "").lower() != "buy":
        return False, "not_buy"

    status = str(order.get("status") or "").upper()
    oid = str(order["order_id"])
    is_success_receipt = source == _APPEALS_SUCCESS_SOURCE

    # Appeals запросил видео (req_type=3) уже после подтверждения мерчантом:
    # ставим выплату крипты на удержание — возвращаем COMPLETED → AWAITING_CHECK.
    # PAID/FAILED не трогаем (крипта уже ушла / провал — откатывать нельзя).
    is_video_hold_after_complete = req_type == 3 and status == "COMPLETED"

    if status in _RECEIPT_BLOCKED_STATUSES and not is_video_hold_after_complete:
        if not (allow_late and is_success_receipt and status in ("PAID", "COMPLETED")):
            # Appeals запросил видео/PDF, но заявка уже завершена.
            # Если статус COMPLETED или PAID — шлём ops-алерт (возможна нехватка подтверждения).
            if status in ("COMPLETED", "PAID"):
                dedup_key = f"receipt_blocked_alert_{req_type}"
                should_alert = await mark_ops_alert_once(oid, dedup_key)
                if should_alert:
                    from services.order_ops_notify import notify_ops_order

                    refreshed = await get_order(oid) or order
                    alert_note = (
                        f"⚠️ Appeals запросил доп. проверку (req_type={req_type}), "
                        f"но заявка уже в статусе {status}. "
                        f"Источник: {source}. Проверьте вручную — выплата крипты может быть под вопросом."
                    )
                    try:
                        await notify_ops_order(
                            "receipt_requested_again",
                            dict(refreshed),
                            bot=bot,
                            note=alert_note,
                        )
                    except Exception as e:
                        logger.warning("ops alert blocked receipt failed order=%s: %s", oid, e)
                else:
                    logger.info(
                        "request_client_receipt_check blocked dedup order=%s status=%s source=%s",
                        oid, status, source,
                    )
            else:
                logger.info(
                    "request_client_receipt_check blocked order=%s status=%s source=%s",
                    oid, status, source,
                )
            return False, f"status_blocked ({status})"
        dedup_key = "client_receipt_req_success_pdf"
        should_notify = await mark_ops_alert_once(oid, dedup_key)
        if not should_notify:
            logger.info(
                "request_client_receipt_check dedup late order=%s source=%s",
                oid,
                source,
            )
            return True, "dedup"
        refreshed = await get_order(oid) or order
        user_id = int(refreshed["user_id"])
        text = receipt_success_status_request_message(oid)
        event = "receipt_requested_again"
        note = (
            "📎 Appeals: нужен повторный PDF со статусом «Выполнено» "
            f"(заявка уже {status}, источник: {source})."
        )
        from services.order_ops_notify import miniapp_ops_note, notify_ops_order

        try:
            await notify_ops_order(
                event, dict(refreshed), bot=bot, note=miniapp_ops_note(refreshed, note)
            )
        except Exception as e:
            logger.warning("ops notify late receipt request failed order=%s: %s", oid, e)
        await _notify_user(user_id, text, bot=bot)
        logger.info(
            "request_client_receipt_check late ok order=%s source=%s user=%s",
            oid,
            source,
            user_id,
        )
        return True, "ok_late"

    from services.payfast_buy_complete import has_client_video_file

    # Recheck (APPEAL + status_check=3) крутится каждые 2 мин. Если клиент уже
    # прислал видео, не откатываем PENDING → AWAITING_CHECK и не дёргаем
    # updated_at — иначе Payfast SUCCSES потом упирается в видео-холд.
    if req_type == 3 and has_client_video_file(order):
        logger.info(
            "request_client_receipt_check skip rollback video already submitted "
            "order=%s status=%s source=%s",
            oid,
            status,
            source,
        )
        return True, "video_already_submitted"

    should_notify = await mark_ops_alert_once(oid, f"client_receipt_req_{req_type}")

    if not await update_order_to_awaiting_check(oid, req_type):
        refreshed = await get_order(oid)
        if (
            not refreshed
            or str(refreshed.get("status") or "").upper() != "AWAITING_CHECK"
            or int(refreshed.get("required_receipt_type") or 0) != int(req_type)
        ):
            return False, "awaiting_check_rejected"

    # Метка повторного запроса: пока клиент ищет PDF или записывает видео,
    # экспайрер не имеет права убить заявку по таймеру оплаты.
    from datetime import datetime, timezone

    from services.db import merge_order_payment_snapshot

    try:
        await merge_order_payment_snapshot(
            oid,
            {"receipt_recheck_requested_at": datetime.now(tz=timezone.utc).isoformat()},
        )
    except Exception as e:
        logger.warning("receipt recheck marker failed order=%s: %s", oid, e)

    if is_video_hold_after_complete:
        # Выплата уходит на удержание: сбрасываем дедуп подтверждения, чтобы после
        # присылки видео и повторного COMPLETED оператор получил свежую карточку.
        from services.db import clear_ops_alert_once

        await clear_ops_alert_once(oid, "merchant_confirmed_notify")

    if not should_notify:
        logger.info(
            "request_client_receipt_check dedup order=%s req_type=%s source=%s",
            oid,
            req_type,
            source,
        )
        return True, "dedup"

    refreshed = await get_order(oid) or order
    user_id = int(refreshed["user_id"])
    if is_success_receipt and req_type == 2:
        text = receipt_success_status_request_message(oid)
    else:
        text = receipt_request_message(oid, req_type)

    if req_type == 3:
        event = "video_requested"
        if is_video_hold_after_complete:
            note = (
                "🛑 ВЫПЛАТА НА УДЕРЖАНИИ: Payfast отклонил PDF, запрошено видео у клиента. "
                f"НЕ отправляйте крипту до подтверждения (источник: {source})."
            )
        else:
            note = f"🎥 Запрошено видео у клиента (источник: {source})."
    elif is_success_receipt:
        event = "receipt_requested_again"
        note = f"📎 Appeals: повторный PDF со статусом «Выполнено» (источник: {source})."
    else:
        event = "receipt_requested_again"
        note = f"📎 Мерчант запросил чек повторно (источник: {source})."

    from services.order_ops_notify import miniapp_ops_note, notify_ops_order

    try:
        await notify_ops_order(
            event,
            dict(refreshed),
            bot=bot,
            note=miniapp_ops_note(refreshed, note),
        )
    except Exception as e:
        logger.warning("ops notify receipt request failed order=%s: %s", oid, e)

    await _notify_user(user_id, text, bot=bot)
    logger.info(
        "request_client_receipt_check ok order=%s req_type=%s source=%s user=%s",
        oid,
        req_type,
        source,
        user_id,
    )
    return True, "ok"


async def _notify_user(user_id: int, message: str, *, bot=None) -> None:
    if not user_id or int(user_id) <= 0:
        return
    if bot:
        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=message,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            logger.warning("notify_user async failed user=%s: %s", user_id, e)
    from services import config_rates as cfg

    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": int(user_id),
                "text": message,
                "parse_mode": "HTML",
            },
            timeout=5,
        )
        if not resp.ok:
            logger.warning(
                "notify_user failed user=%s status=%s body=%s",
                user_id,
                resp.status_code,
                resp.text[:200],
            )
    except Exception as e:
        logger.warning("notify_user error user=%s: %s", user_id, e)

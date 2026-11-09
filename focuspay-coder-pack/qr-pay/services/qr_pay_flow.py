"""Сценарий оплаты по QR СБП: проверка кода, подтверждение, применение итога."""
from __future__ import annotations

import html
import logging

from services import finance666_client as api
from services import qr_pay_wallet as wallet
from services.finance666_client import Finance666Error
from services.qr_pay_status import UNAVAILABLE_TEXT
from services.qr_pay_wallet import QrPayError

logger = logging.getLogger("qr_pay_flow")

SUPPORT_CONTACT = "@focus_operator"


def qrpay_webapp_url() -> str:
    from services.buy_payment_prompt import webapp_base_url

    return f"{webapp_base_url()}/webapp/qrpay"


def _money(value) -> str:
    return f"{float(value or 0):,.2f}".replace(",", " ")


def ops_notify(lines: list[str]) -> None:
    from services.order_ops_notify import (
        OPS_MSG_SEPARATOR,
        _admin_chat_id,
        send_telegram_message_http,
    )

    chat_id = _admin_chat_id()
    if not chat_id:
        return
    text = "\n".join([lines[0], OPS_MSG_SEPARATOR, "", *lines[1:]])
    send_telegram_message_http(chat_id, text)


def _user_notify(user_id: int, text: str) -> None:
    from services.order_ops_notify import send_telegram_message_http

    send_telegram_message_http(int(user_id), text)


async def start_check(
    *, user_id: int, qr_code: str, username: str | None = None
) -> dict:
    """Проверить код и показать клиенту сумму. Деньги не трогаются."""
    from services.qr_pay_status import availability

    code = (qr_code or "").strip()
    state = await availability(user_id=user_id, username=username)
    if not state["available"]:
        if state["reason"] == "low_balance":
            logger.warning(
                "qr pay unavailable: merchant balance %.2f < %.2f",
                state["balance"],
                state["threshold"],
            )
        raise QrPayError(UNAVAILABLE_TEXT)
    if not api.is_nspk_qr(code):
        raise QrPayError("Это не QR-код СБП. Отсканируйте код для оплаты.")

    mtid = wallet.new_merchant_transaction_id()
    try:
        payment = await api.qr_check(code, mtid)
    except Finance666Error as exc:
        logger.warning("qr check failed %s: %s", mtid, exc)
        raise QrPayError("Не удалось проверить код, попробуйте ещё раз.") from exc

    if not payment.success or not payment.status.payable:
        logger.info(
            "qr check not payable %s: group=%s code=%s",
            mtid,
            payment.status.group,
            payment.status.code,
        )
        raise QrPayError("По этому коду оплата невозможна.")
    if payment.is_balance_sufficient is False:
        # Кеш баланса устарел — следующий клиент не должен дойти до этого места.
        from services.qr_pay_status import invalidate

        invalidate()
        ops_notify(
            [
                "<b>⚠️ Оплата по QR · не хватает баланса платформы</b>",
                f"Клиент: <code>{user_id}</code>",
                f"Сумма: <b>{_money(payment.amount_in_currency)} ₽</b>",
                "Пополните мерчантский баланс finance666.",
            ]
        )
        raise QrPayError(UNAVAILABLE_TEXT)

    row = await wallet.record_check(
        user_id=user_id,
        merchant_transaction_id=mtid,
        qr_code=code,
        payment=payment,
    )
    return {
        "payment_id": row["merchant_transaction_id"],
        "payee_name": row.get("payee_name"),
        "amount_rub": float(row.get("amount_rub") or 0),
        "charged_rub": float(row.get("charged_rub") or 0),
        "markup_pct": float(row.get("markup_pct") or 0),
        "expires_at": (
            row["expires_at"].isoformat() if row.get("expires_at") else None
        ),
    }


async def confirm_pay(*, user_id: int, payment_id: str) -> dict:
    """Зарезервировать деньги и провести выплату."""
    reserved = await wallet.reserve(merchant_transaction_id=payment_id, user_id=user_id)
    provider_tx = str(reserved.get("provider_transaction_id") or "")
    if not provider_tx:
        await wallet.release(payment_id)
        raise QrPayError("Платёж не найден на стороне платформы.")

    try:
        payment = await api.qr_pay(provider_tx)
    except Finance666Error as exc:
        # Исход неизвестен: резерв держим, итог доберём вебхуком или опросом.
        logger.warning("qr pay call failed %s: %s", payment_id, exc)
        ops_notify(
            [
                "<b>⚠️ Оплата по QR · нет ответа платформы</b>",
                f"Платёж: <code>{html.escape(payment_id)}</code>",
                f"Клиент: <code>{user_id}</code>",
                f"Сумма: <b>{_money(reserved.get('charged_rub'))} ₽</b>",
                "Резерв держим, итог ждём вебхуком.",
            ]
        )
        return {"state": "processing", "payment_id": payment_id}

    if payment.status.code == api.CODE_INSUFFICIENT_FUNDS:
        # По докам вебхука в этом случае не будет: средства не морозились.
        from services.qr_pay_status import invalidate

        invalidate()
        await wallet.release(payment_id)
        ops_notify(
            [
                "<b>⚠️ Оплата по QR · баланс платформы исчерпан</b>",
                f"Платёж: <code>{html.escape(payment_id)}</code>",
                f"Сумма: <b>{_money(reserved.get('charged_rub'))} ₽</b>",
                "Пополните мерчантский баланс finance666.",
            ]
        )
        raise QrPayError(UNAVAILABLE_TEXT)

    await apply_outcome(payment_id, payment, notify_user=False)

    if payment.status.succeeded:
        return {"state": "paid", "payment_id": payment_id}
    if payment.status.lost:
        raise QrPayError("Платёж не прошёл, деньги остались на балансе.")
    return {"state": "processing", "payment_id": payment_id}


async def apply_outcome(payment_id: str, payment, *, notify_user: bool = True) -> dict | None:
    """Применить статус платформы к платежу: списать, вернуть или оставить в работе."""
    row, applied = await wallet.apply_provider_status(payment_id, payment)
    if row is None:
        logger.warning("qr pay outcome for unknown payment %s", payment_id)
        return None
    if not applied:
        return row

    user_id = int(row["user_id"])
    charged = _money(row.get("charged_rub"))
    payee = html.escape(str(row.get("payee_name") or "получателю"))

    if payment.status.succeeded:
        settled = await wallet.settle(payment_id)
        if notify_user and settled and settled.get("local_status") == "SETTLED":
            _user_notify(
                user_id,
                f"✅ Оплата по QR прошла.\n\n{payee} — <b>{_money(row.get('amount_rub'))} ₽</b>\n"
                f"Списано с баланса: <b>{charged} ₽</b>",
            )
        return settled or row

    if payment.status.refunded:
        refunded = await wallet.refund(payment_id)
        _user_notify(
            user_id,
            f"↩️ Оплата по QR отменена, <b>{charged} ₽</b> вернулись на баланс.",
        )
        ops_notify(
            [
                "<b>↩️ Оплата по QR · возврат платформой</b>",
                f"Платёж: <code>{html.escape(payment_id)}</code>",
                f"Клиент: <code>{user_id}</code>",
                f"Возвращено клиенту: <b>{charged} ₽</b>",
            ]
        )
        return refunded or row

    if payment.status.lost:
        released = await wallet.release(payment_id)
        if notify_user:
            _user_notify(
                user_id,
                f"❌ Оплата по QR не прошла. <b>{charged} ₽</b> остались на балансе.",
            )
        if payment.status.group == api.GROUP_FAILED:
            ops_notify(
                [
                    "<b>❌ Оплата по QR · сбой выплаты</b>",
                    f"Платёж: <code>{html.escape(payment_id)}</code>",
                    f"Клиент: <code>{user_id}</code>",
                    f"Статус: <code>{html.escape(payment.status.code or '—')}</code>",
                ]
            )
        return released or row

    if payment.status.unknown_outcome:
        # Незнакомая группа при is_final: сами решить не можем, резерв не трогаем.
        ops_notify(
            [
                "<b>❓ Оплата по QR · неизвестный итог</b>",
                f"Платёж: <code>{html.escape(payment_id)}</code>",
                f"Клиент: <code>{user_id}</code>",
                f"Группа: <code>{html.escape(payment.status.group or '—')}</code>",
                f"Код: <code>{html.escape(payment.status.code or '—')}</code>",
                f"Резерв <b>{charged} ₽</b> держим. Уточните исход в поддержке платформы.",
            ]
        )
    return row

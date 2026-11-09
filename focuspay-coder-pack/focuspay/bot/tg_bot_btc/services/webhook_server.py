from pathlib import Path
import json
import re
import logging
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.responses import JSONResponse, FileResponse
import requests
from services import config_rates as cfg
from services.callback_signatures import sign_order
from services.db import get_order, update_order_status, init_db
from services.payfast_payin_guard import (
    is_webhook_payment_failure,
    verify_payfast_ready_for_complete,
)
from services.webhook_security import (
    amount_matches_order,
    is_payment_success_payload,
    order_ready_for_merchant_complete,
    resolve_client_ip,
    verify_incoming_webhook,
    verify_receipt_access,
    verify_webhook_client_ip,
)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
logger = logging.getLogger("webhook_server")
EARLY_PAYFAST_FAILURE_GRACE_SEC = 15


def _created_order_failure_is_early(order: dict) -> bool:
    """Only suppress an ERROR callback during the create/insert race."""
    raw = order.get("created_at")
    if raw is None:
        return True
    if isinstance(raw, datetime):
        created_at = raw
    else:
        try:
            created_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds()
    return age <= EARLY_PAYFAST_FAILURE_GRACE_SEC


def notify_admin_late_payment(order: dict, amount) -> None:
    import html

    from services.merchant_order_id import format_ops_order_id_html

    chat_id = cfg.reports_group_id() or None
    if not chat_id:
        return
    text = (
        "🚨 <b>Опоздавший webhook успеха</b>\n\n"
        f"Заявка уже <code>{html.escape(str(order['status']))}</code>, "
        f"мерч прислал успех.\n"
        f"{format_ops_order_id_html(order)}\n"
        f"💵 сумма: <code>{html.escape(str(amount))}</code>\n"
        "Нужна ручная проверка."
    )
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("late payment admin alert failed: %s", e)


def notify_ops_payfast_reversal(order: dict, payfast_status: str | None) -> None:
    import html

    from services.merchant_order_id import format_ops_order_id_html

    chat_id = cfg.ops_group_id() or cfg.reports_group_id() or None
    if not chat_id:
        return
    st = html.escape(str(payfast_status or "ERROR"))
    text = (
        "🚨 <b>Payfast отменил оплату</b>\n\n"
        f"Статус мерчанта: <code>{st}</code>\n"
        f"{format_ops_order_id_html(order)}\n\n"
        "❗ Заявка переведена в CANCELED — <b>крипту НЕ отправлять</b>."
    )
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("payfast reversal ops alert failed: %s", e)


def notify_ops_receipt_missing_on_success(order: dict, amount) -> None:
    import html

    from services.merchant_order_id import format_ops_order_id_html

    chat_id = cfg.ops_group_id() or cfg.reports_group_id() or None
    if not chat_id:
        return
    text = (
        "🚨 <b>Оплата подтверждена, но чек НЕ отправлен мерчанту</b>\n\n"
        f"{format_ops_order_id_html(order)}\n"
        f"💵 сумма: <code>{html.escape(str(amount))}</code>\n\n"
        "Заявка осталась в AWAITING_CHECK — <b>крипту НЕ отправлять</b> до "
        "получения чека. Проверьте оплату вручную."
    )
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("receipt-missing ops alert failed: %s", e)


def notify_ops_payfast_error_after_payout(order: dict, payfast_status: str | None) -> None:
    import html

    from services.merchant_order_id import format_ops_order_id_html

    chat_id = cfg.ops_group_id() or cfg.reports_group_id() or None
    if not chat_id:
        return
    st = html.escape(str(payfast_status or "ERROR"))
    text = (
        "🚨 <b>Payfast ERROR после выплаты</b>\n\n"
        f"Статус мерчанта: <code>{st}</code>\n"
        f"{format_ops_order_id_html(order)}\n\n"
        "Крипта уже отправлена — нужна срочная ручная проверка."
    )
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("payfast post-payout ops alert failed: %s", e)


from services.receipts_storage import receipts_dir as get_receipts_dir

RECEIPTS_DIR = get_receipts_dir()
SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9]+\.[a-zA-Z0-9]{1,20}$")
_RECEIPT_MEDIA = {
    "pdf": "application/pdf",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
}


@app.get("/receipt/{filename:path}")
async def serve_receipt(filename: str, request: Request, sig: str = "", exp: str = ""):
    filename = filename.strip()
    if not sig or not verify_receipt_access(filename, sig, exp or None):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if not SAFE_FILENAME_RE.match(filename.strip()):
        return JSONResponse({"error": "invalid"}, status_code=400)
    path = (RECEIPTS_DIR / filename).resolve()
    if path.parent != RECEIPTS_DIR.resolve() or not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media = _RECEIPT_MEDIA.get(ext, "application/octet-stream")
    # filename + inline: панель Payfast встраивает PDF, а не показывает ссылку.
    return FileResponse(
        path,
        media_type=media,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def notify_user(user_id: int, message: str) -> None:
    if not user_id or int(user_id) <= 0:
        logger.info("notify_user skip non-telegram user_id=%s", user_id)
        return
    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": user_id,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if not resp.ok:
            logger.warning(
                "notify_user failed user_id=%s status=%s body=%s",
                user_id,
                resp.status_code,
                resp.text[:200],
            )
    except Exception as e:
        logger.warning("notify_user error user_id=%s: %s", user_id, e)


@app.on_event("startup")
async def startup_event():
    cfg.validate_webhook_config()
    await init_db(cfg.DATABASE_DSN)
    try:
        from telegram import Bot
        from services.bot_context import set_bot

        set_bot(Bot(cfg.TELEGRAM_BOT_TOKEN))
    except Exception as e:
        logger.warning("Telegram bot for split notifications not initialized: %s", e)
    print("✅ Webhook DB connected")


FINAL_STATUSES = {"COMPLETED", "PAID", "FAILED", "CANCELED", "EXPIRED"}


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "service": "tg-bot-webhook"})


def _internal_token_ok(header: str | None) -> bool:
    import os

    expected = (os.getenv("INTERNAL_API_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()
    return bool(expected) and (header or "").strip() == expected


@app.post("/internal/reki-issue")
async def internal_reki_issue(
    request: Request,
    x_internal_token: str | None = Header(default=None),
):
    """Реквизит у @madsidmaofao_bot для бота внештатников. Тикет пишет вызывающий."""
    if not _internal_token_ok(x_internal_token):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    amount = (body or {}).get("amount_rub")
    sub_token = str((body or {}).get("sub_token") or "")
    try:
        from services.reki_request import request_ready, request_requisite

        if not request_ready():
            return JSONResponse({"ok": False, "reason": "Сессия реки-бота не настроена."})
        issued = await request_requisite(amount, sub_token)
    except Exception:
        logger.warning("internal reki-issue failed", exc_info=True)
        return JSONResponse({"ok": False, "reason": "Реки-бот не ответил."})
    if issued is None:
        return JSONResponse({"ok": False, "reason": "Реки-бот не выдал реквизит на эту сумму."})
    bill = {
        "bank": issued.bank or "",
        "reciver": issued.requisite,
        "fio": issued.holder or "",
    }
    if isinstance(issued.message_id, int) and issued.message_id > 0:
        bill["reki_message_id"] = issued.message_id
    payfast_id = issued.payfast_id if isinstance(issued.payfast_id, str) else None
    payfast_id = (payfast_id or "").strip() or None
    if payfast_id:
        bill["payfast_id"] = payfast_id
    return JSONResponse({"ok": True, "bill": bill, "payfast_id": payfast_id})


@app.post("/internal/reki-cancel")
async def internal_reki_cancel(
    request: Request,
    x_internal_token: str | None = Header(default=None),
):
    """Жмёт «Отменить заявку» на сообщении реки. Тикет закрывает вызывающий."""
    if not _internal_token_ok(x_internal_token):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        message_id = int((body or {}).get("message_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "reason": "Нет сообщения для отмены."})
    try:
        from services.reki_request import cancel_reki_message

        clicked = await cancel_reki_message(message_id)
    except Exception:
        logger.warning("internal reki-cancel failed", exc_info=True)
        return JSONResponse({"ok": False, "reason": "Не удалось отменить заявку у реки-бота."})
    if not clicked:
        return JSONResponse({"ok": False, "reason": "Не удалось отменить заявку у реки-бота."})
    return JSONResponse({"ok": True})


_WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp" / "requisites"


@app.get("/webapp")
@app.get("/webapp/")
async def webapp_index():
    index = _WEBAPP_DIR / "index.html"
    if not index.is_file():
        return JSONResponse({"error": "webapp missing"}, status_code=404)
    return FileResponse(index, media_type="text/html; charset=utf-8")


@app.post("/webapp/api/requisites/open")
async def webapp_requisites_open(request: Request):
    from services.webhook_security import resolve_client_ip
    from services.webapp_requisites import open_requisites

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "blocked": True, "message": "bad json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "blocked": True, "message": "bad json"}, status_code=400)

    client_host = resolve_client_ip(
        request.client.host if request.client else None,
        cf_connecting_ip=request.headers.get("cf-connecting-ip")
        or request.headers.get("CF-Connecting-IP"),
        real_ip=request.headers.get("x-real-ip") or request.headers.get("X-Real-IP"),
        forwarded_for=request.headers.get("x-forwarded-for"),
    )
    result = await open_requisites(
        order_id=str(body.get("order_id") or "").strip(),
        sig=str(body.get("sig") or "").strip(),
        init_data=str(body.get("init_data") or ""),
        fingerprint=str(body.get("fingerprint") or "") or None,
        signals=body.get("signals") if isinstance(body.get("signals"), dict) else {},
        client_ip=client_host,
        honeypot=str(body.get("honeypot") or ""),
    )
    status = 200
    if result.get("error") in ("bad_sig", "init:bad signature", "init:empty init_data"):
        status = 401
    elif result.get("error") == "owner":
        status = 403
    return JSONResponse(result, status_code=status)


@app.get("/callback")
async def callback_get_help():
    return JSONResponse({"error": "forbidden"}, status_code=403)


@app.post("/callback")
@app.post("/callback/{order_ref}")
async def callback_post(
    request: Request,
    background_tasks: BackgroundTasks,
    order_ref: str | None = None,
):
    client_host = resolve_client_ip(
        request.client.host if request.client else None,
        cf_connecting_ip=request.headers.get("cf-connecting-ip")
        or request.headers.get("CF-Connecting-IP"),
        real_ip=request.headers.get("x-real-ip") or request.headers.get("X-Real-IP"),
        forwarded_for=request.headers.get("x-forwarded-for"),
    )
    if not verify_webhook_client_ip(client_host):
        logger.warning("webhook rejected ip=%s", client_host)
        return JSONResponse({"error": "forbidden"}, status_code=403)

    raw_body = await request.body()
    signature = request.headers.get("x-signature") or request.headers.get("X-Signature")
    timestamp = request.headers.get("x-timestamp") or request.headers.get("X-Timestamp")

    try:
        body = json.loads(raw_body.decode("utf-8") if raw_body else "{}")
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if not verify_incoming_webhook(raw_body, body, signature, timestamp):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    data_order = body.get("data_order") or {}
    order_id = data_order.get("client_transaction_id") or body.get("client_transaction_id")
    status_raw = data_order.get("status") or body.get("status")
    status = str(status_raw).strip().upper() if status_raw is not None else None
    status_pending = body.get("status_pending") or data_order.get("status_pending")
    status_check = body.get("status_check") or data_order.get("status_check")
    status_file = body.get("status_file") or data_order.get("status_file")

    if not order_id:
        return JSONResponse({"ok": False, "reason": "no client_transaction_id"}, status_code=400)
    order_id = str(order_id).strip()
    if order_ref is not None and str(order_ref).strip() != order_id:
        logger.warning(
            "webhook order mismatch path=%s body=%s ip=%s",
            order_ref,
            order_id,
            client_host,
        )
        return JSONResponse({"ok": False, "reason": "order_id_mismatch"}, status_code=409)

    order = await get_order(order_id)
    if not order:
        # PayFast may deliver the first callback before the bot commits the
        # local order row.  A 404 is treated by the provider as a failed
        # callback and can make a freshly issued payin enter ERROR.  Acknowledge
        # the signed event; the reconciler will verify the payin once the row
        # is visible in PostgreSQL.
        if is_payment_success_payload(
            status,
            status_pending,
            status_check,
            "buy",
            status_file=status_file,
        ):
            from services.external_deal_payfast_webhook import (
                handle_external_deal_payfast_webhook,
            )

            background_tasks.add_task(
                handle_external_deal_payfast_webhook, order_id, body
            )
            return JSONResponse({"ok": True, "type": "external_deal"})
        logger.warning(
            "webhook arrived before local order insert order=%s status=%s",
            order_id,
            status,
        )
        return JSONResponse({"ok": True, "reason": "order_pending"})

    current_status = order["status"]
    user_id = order["user_id"]

    if is_webhook_payment_failure(status):
        # A freshly created payin can report ERROR while PayFast is still
        # delivering/assigning its requisites.  Treating that callback as a
        # payment failure immediately cancels orders seconds after creation.
        # Keep CREATED alive; the reconciler/expiry path will handle a real
        # failure after the payment flow has started.
        if current_status == "CREATED" and _created_order_failure_is_early(dict(order)):
            logger.warning(
                "ignoring early PayFast failure for CREATED order=%s status=%s",
                order_id,
                status,
            )
            return JSONResponse({"ok": True, "reason": "created_failure_ignored"})
        if current_status == "COMPLETED":
            if await update_order_status(order_id, "CANCELED"):
                background_tasks.add_task(
                    notify_ops_payfast_reversal,
                    dict(order),
                    status,
                )
                background_tasks.add_task(
                    notify_user,
                    user_id,
                    f"❌ <b>Заявка отменена</b>\n\n🆔 <code>{order_id}</code>",
                )
            return JSONResponse({"ok": True, "reason": "completed_reverted_payfast_error"})
        if current_status == "PAID":
            background_tasks.add_task(
                notify_ops_payfast_error_after_payout,
                dict(order),
                status,
            )
            return JSONResponse({"ok": True, "reason": "paid_payfast_error_logged"})
        if current_status not in FINAL_STATUSES:
            if await update_order_status(order_id, "CANCELED"):
                background_tasks.add_task(
                    notify_user,
                    user_id,
                    f"❌ <b>Заявка отменена</b>\n\n🆔 <code>{order_id}</code>",
                )
            else:
                return JSONResponse({"ok": False, "reason": "transition_rejected"}, status_code=409)
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": True, "reason": f"already_final ({current_status})"})

    direction = (order.get("direction") or "buy").lower()
    payment_confirmed = is_payment_success_payload(
        status,
        status_pending,
        status_check,
        direction,
        status_file=status_file,
    )

    if status_check in (2, 3, 4, "2", "3", "4") and not payment_confirmed:
        from services.payfast_payin_guard import handle_payfast_recheck

        ok, reason = await handle_payfast_recheck(
            dict(order),
            body,
            source="webhook",
        )
        if not ok and reason == "appeal_ended":
            return JSONResponse({"ok": True, "reason": "appeal_ended"})
        if not ok:
            return JSONResponse(
                {"ok": False, "reason": f"receipt_request_failed ({reason})"},
                status_code=409,
            )
        return JSONResponse({"ok": True})

    if current_status in FINAL_STATUSES:
        if is_payment_success_payload(
            status, status_pending, status_check, status_file=status_file
        ):
            if current_status in ("EXPIRED", "CANCELED"):
                background_tasks.add_task(
                    notify_admin_late_payment,
                    dict(order),
                    data_order.get("amount"),
                )
        return JSONResponse({"ok": True, "reason": f"already_final ({current_status})"})

    if payment_confirmed:
        ready, ready_reason = order_ready_for_merchant_complete(order)
        if not ready:
            if current_status in ("EXPIRED", "CANCELED"):
                background_tasks.add_task(
                    notify_admin_late_payment,
                    dict(order),
                    data_order.get("amount"),
                )
                return JSONResponse({"ok": True, "reason": "late_success_logged"})
            if ready_reason == "receipt_not_submitted":
                from services.payfast_buy_complete import (
                    awaiting_check_can_settle,
                    complete_buy_from_payfast_settled,
                )

                if awaiting_check_can_settle(order):
                    settled_ok, settled_err = await complete_buy_from_payfast_settled(
                        order_id,
                        dict(order),
                        webhook_body=body,
                    )
                    if settled_ok:
                        return JSONResponse(
                            {"ok": True, "reason": "awaiting_check_receipt_settled"}
                        )
                    logger.warning(
                        "webhook awaiting_check settle failed order=%s reason=%s",
                        order_id,
                        settled_err,
                    )
                # В AWAITING_CHECK без PDF не даём заявке дойти до COMPLETED.
                pf_ok, pf_reason, _ = await verify_payfast_ready_for_complete(
                    dict(order), body
                )
                if not pf_ok:
                    logger.warning(
                        "webhook receipt_not_submitted payfast verify fail order=%s reason=%s",
                        order_id,
                        pf_reason,
                    )

                from services.db import mark_ops_alert_once

                if await mark_ops_alert_once(order_id, "receipt_not_submitted"):
                    background_tasks.add_task(
                        notify_ops_receipt_missing_on_success,
                        dict(order),
                        data_order.get("amount"),
                    )
                return JSONResponse(
                    {"ok": True, "reason": "receipt_not_submitted_alerted"}
                )
            return JSONResponse(
                {"ok": False, "reason": ready_reason},
                status_code=409,
            )
        amount_ok, amount_reason = amount_matches_order(data_order, order)
        amount_note: str | None = None
        if not amount_ok:
            logger.warning(
                "webhook amount diff (proceeding, Payfast confirmed) order=%s reason=%s",
                order_id,
                amount_reason,
            )
            amount_note = amount_reason
        pf_ok, pf_reason, _ = await verify_payfast_ready_for_complete(dict(order), body)
        if not pf_ok:
            logger.warning(
                "webhook success rejected order=%s reason=%s status=%r status_check=%r",
                order_id,
                pf_reason,
                status,
                status_check,
            )
            return JSONResponse({"ok": False, "reason": pf_reason}, status_code=422)
        updated = await update_order_status(order_id, "COMPLETED")
        if not updated:
            if is_payment_success_payload(
                status,
                status_pending,
                status_check,
                direction,
                status_file=status_file,
            ):
                background_tasks.add_task(
                    notify_admin_late_payment,
                    dict(order),
                    data_order.get("amount"),
                )
                return JSONResponse({"ok": True, "reason": "late_success_logged"})
            return JSONResponse(
                {"ok": False, "reason": f"transition_rejected ({current_status})"},
                status_code=409,
            )
        order = await get_order(order_id)
        from services.order_ops_notify import notify_ops_order_sync
        from services.db import mark_ops_alert_once

        if order:
            confirm_note = "Отправьте крипту клиенту"
            if amount_note:
                confirm_note += (
                    f"\n⚠️ Расхождение суммы: {amount_note} "
                    "(Payfast подтвердил — ставка зафиксирована при создании)"
                )
            if await mark_ops_alert_once(order_id, "merchant_confirmed_notify"):
                background_tasks.add_task(
                    notify_ops_order_sync,
                    "merchant_confirmed",
                    dict(order),
                    pay_signature=sign_order(order_id),
                    note=confirm_note,
                )
            else:
                logger.info(
                    "merchant_confirmed ops notify dedup order=%s", order_id
                )
        background_tasks.add_task(
            notify_user,
            user_id,
            (
                f"✅ <b>Платёж подтверждён</b>\n\n"
                f"🆔 Заявка: <code>{order_id}</code>\n\n"
                "⏳ Ожидайте зачисления средств — вам придёт транзакция "
                "на кошелёк в течение пары минут."
            ),
        )

    elif status == "EXPIRED":
        if not await update_order_status(order_id, "EXPIRED"):
            return JSONResponse({"ok": False, "reason": "transition_rejected"}, status_code=409)
        background_tasks.add_task(
            notify_user,
            user_id,
            f"⏰ <b>Заявка истекла</b>\n\n🆔 <code>{order_id}</code>",
        )

    else:
        logger.info(
            "webhook ignored (not payment success) order=%s status=%r "
            "status_pending=%r status_check=%r",
            order_id,
            status,
            status_pending,
            status_check,
        )

    return JSONResponse({"ok": True})

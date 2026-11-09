"""HTTP-куски, которые висели на webhook_server бота обменника.

Монтировать на приложении кошелька. Личность только из подписанного initData.
Оплата зовёт services.finance666_client.qr_pay через services.qr_pay_flow.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import BackgroundTasks, Header, Request
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("qr_pay_http")

_QRPAY_WEBAPP_DIR = Path(__file__).resolve().parent / "webapp" / "qrpay"


def mount(app) -> None:
    app.get("/webapp/qrpay")(webapp_qrpay_index)
    app.get("/webapp/qrpay/")(webapp_qrpay_index)
    app.post("/webapp/api/qr/check")(webapp_qr_check)
    app.post("/webapp/api/qr/pay")(webapp_qr_pay)
    app.post("/webhooks/finance666")(finance666_webhook)


async def webapp_qrpay_index():
    index = _QRPAY_WEBAPP_DIR / "index.html"
    if not index.is_file():
        return JSONResponse({"error": "webapp missing"}, status_code=404)
    return FileResponse(index, media_type="text/html; charset=utf-8")


def _qrpay_identity(init_data: str) -> tuple[int, str | None]:
    """Личность берём только из подписанного initData, из тела — никогда."""
    from services import config_rates as cfg
    from services.tg_webapp_initdata import verify_webapp_init_data

    idata = verify_webapp_init_data(
        init_data, cfg.TELEGRAM_BOT_TOKEN, max_age_seconds=3600
    )
    return int(idata.user.id), idata.user.username


async def webapp_qr_check(request: Request):
    from services.qr_pay_wallet import QrPayError
    from services.tg_webapp_initdata import InitDataError
    from services.qr_pay_flow import start_check

    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "message": "bad json"}, status_code=400)
    try:
        user_id, username = _qrpay_identity(str(body.get("init_data") or ""))
    except InitDataError:
        return JSONResponse(
            {"ok": False, "message": "Откройте оплату кнопкой внутри Telegram."},
            status_code=401,
        )
    try:
        result = await start_check(
            user_id=user_id,
            username=username,
            qr_code=str(body.get("qr_code") or ""),
        )
    except QrPayError as e:
        return JSONResponse({"ok": False, "message": str(e)})
    except Exception:
        logger.warning("qr check failed user=%s", user_id, exc_info=True)
        return JSONResponse({"ok": False, "message": "Сервис недоступен, попробуйте позже."})
    return JSONResponse({"ok": True, **result})


async def webapp_qr_pay(request: Request):
    from services.qr_pay_wallet import QrPayError
    from services.tg_webapp_initdata import InitDataError
    from services.qr_pay_flow import confirm_pay

    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "message": "bad json"}, status_code=400)
    try:
        user_id, _username = _qrpay_identity(str(body.get("init_data") or ""))
    except InitDataError:
        return JSONResponse(
            {"ok": False, "message": "Откройте оплату кнопкой внутри Telegram."},
            status_code=401,
        )
    payment_id = str(body.get("payment_id") or "").strip()
    if not payment_id:
        return JSONResponse({"ok": False, "message": "Платёж не найден."})
    try:
        result = await confirm_pay(user_id=user_id, payment_id=payment_id)
    except QrPayError as e:
        return JSONResponse({"ok": False, "message": str(e)})
    except Exception:
        logger.warning("qr pay failed user=%s payment=%s", user_id, payment_id, exc_info=True)
        return JSONResponse({"ok": False, "message": "Сервис недоступен, попробуйте позже."})
    return JSONResponse({"ok": True, **result})


async def _handle_finance666_webhook(webhook_id: str, payload: dict) -> None:
    """Обработка вне ответа: у платформы таймаут доставки 5 секунд."""
    from services import qr_pay_wallet as wallet
    from services.finance666_client import parse_payment
    from services.qr_pay_flow import apply_outcome

    try:
        payment = parse_payment(payload)
        mtid = payment.merchant_transaction_id
        if not mtid and payment.transaction_id:
            row = await wallet.get_payment_by_provider(payment.transaction_id)
            mtid = str(row["merchant_transaction_id"]) if row else None
        if not mtid:
            logger.warning("finance666 webhook %s: payment not matched", webhook_id)
            return
        await apply_outcome(mtid, payment)
        await wallet.mark_webhook_handled(webhook_id)
    except Exception:
        logger.warning("finance666 webhook %s failed", webhook_id, exc_info=True)


async def finance666_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_id: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
    x_webhook_signature: str | None = Header(default=None),
):
    from services.qr_pay_wallet import webhook_already_handled
    from services.webhook_security import verify_finance666_webhook

    raw_body = await request.body()
    if not verify_finance666_webhook(
        raw_body,
        webhook_id=x_webhook_id,
        timestamp=x_webhook_timestamp,
        signature=x_webhook_signature,
    ):
        logger.warning("finance666 webhook rejected id=%s", x_webhook_id)
        return JSONResponse({"ok": False}, status_code=401)

    try:
        payload = json.loads(raw_body)
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False}, status_code=400)

    if await webhook_already_handled(str(x_webhook_id)):
        return JSONResponse({"ok": True, "duplicate": True})

    background_tasks.add_task(_handle_finance666_webhook, str(x_webhook_id), payload)
    return JSONResponse({"ok": True})

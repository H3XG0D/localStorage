"""Internal VPN billing API for the FocusVPN bot (X-Internal-Token).

The bot only asks FocusPay; FocusPay holds money, grants days on the FocusVPN
control plane and confirms the spend (see vpn_billing).
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

import vpn_billing
import vpn_reviews
from config import settings
from db import get_pool

logger = logging.getLogger("internal_vpn")

router = APIRouter()


def _verify_internal_token(token: str | None) -> None:
    expected = (settings.internal_api_secret or settings.webhook_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API not configured")
    supplied = (token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")


class PurchaseIn(BaseModel):
    telegram_id: int = Field(gt=0)
    plan_code: str = Field(min_length=1, max_length=32)
    idem_key: str = Field(min_length=8, max_length=128)


class TrialIn(BaseModel):
    telegram_id: int = Field(gt=0)
    idem_key: str = Field(min_length=8, max_length=128)


def _refusal(exc: Exception) -> HTTPException:
    if isinstance(exc, vpn_billing.GateError):
        return HTTPException(
            status_code=403,
            detail={
                "code": "exchange_gate",
                "need": exc.need,
                "have": exc.have,
                "invited_need": exc.invited_need,
                "invited_have": exc.invited_have,
                "message": str(exc),
            },
        )
    if isinstance(exc, vpn_billing.BillingError):
        status = 402 if exc.code == "insufficient_funds" else 409 if exc.code == "trial_used" else 400
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    raise exc


@router.get("/plans")
async def vpn_plans(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        cfg = await vpn_billing.load_settings(conn)
    return {
        "plans": vpn_billing.plan_cards(cfg["plans"]),
        "device_addons": vpn_billing.plan_cards(cfg["device_addons"]),
        "trial": cfg["trial"],
        "purchase_min_exchanges": cfg["purchase_min_exchanges"],
        "purchase_min_invited": cfg["purchase_min_invited"],
        "app_url": cfg["app_url"],
    }


@router.get("/status/{telegram_id}")
async def vpn_status(telegram_id: int, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        out = await vpn_billing.user_status(conn, telegram_id)
    cp = await vpn_billing.cp_status(telegram_id)
    out["subscription"] = vpn_billing.subscription_view(cp)
    out["devices_limit"] = vpn_billing.devices_limit_view(cp)
    try:
        async with pool.acquire() as conn:
            out["review"] = await vpn_reviews.offer_for_user(conn, telegram_id, out["subscription"])
    except Exception:
        logger.exception("vpn review offer failed tg=%s", telegram_id)
        out["review"] = {
            "eligible": False,
            "pending": False,
            "reason": "unavailable",
            "next_at": None,
            "text_rub": 25,
            "photo_rub": 50,
        }
    return out


@router.post("/purchase")
async def vpn_purchase(body: PurchaseIn, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            out = await vpn_billing.purchase(
                conn, telegram_id=body.telegram_id, plan_code=body.plan_code, idem_key=body.idem_key
            )
        except (vpn_billing.GateError, vpn_billing.BillingError) as exc:
            raise _refusal(exc) from exc
    return out.as_dict()


@router.post("/device")
async def vpn_device(body: PurchaseIn, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            out = await vpn_billing.purchase_device(
                conn, telegram_id=body.telegram_id, plan_code=body.plan_code, idem_key=body.idem_key
            )
        except (vpn_billing.GateError, vpn_billing.BillingError) as exc:
            raise _refusal(exc) from exc
    return out.as_dict()


@router.post("/trial")
async def vpn_trial(body: TrialIn, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            out = await vpn_billing.trial(conn, telegram_id=body.telegram_id, idem_key=body.idem_key)
        except (vpn_billing.GateError, vpn_billing.BillingError) as exc:
            raise _refusal(exc) from exc
    return out.as_dict()


class NotifiedIn(BaseModel):
    telegram_id: int = Field(gt=0)
    kind: str = Field(pattern="^(soon|ended)$")
    ends_at: datetime


@router.get("/expiring")
async def vpn_expiring(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    """Reminders the VPN bot still has to send (ends within 6 h / ended within a day)."""
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            due = await vpn_billing.due_reminders(conn)
        except vpn_billing.CPError as exc:
            raise HTTPException(status_code=502, detail={"code": "cp_unavailable", "message": str(exc)}) from exc
    return {"reminders": due}


@router.post("/notified")
async def vpn_notified(body: NotifiedIn, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        first = await vpn_billing.mark_reminded(conn, body.telegram_id, body.kind, body.ends_at)
    return {"recorded": first}


@router.post("/reviews")
async def vpn_review_submit(
    telegram_id: int = Form(..., gt=0),
    text: str = Form(""),
    author: str = Form(""),
    photo: UploadFile | None = File(None),
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    photo_bytes = None
    photo_ext = None
    if photo is not None:
        raw = await photo.read()
        if raw:
            ctype = (photo.content_type or "").split(";")[0].strip().lower()
            photo_ext = vpn_reviews.PHOTO_EXT.get(ctype)
            if photo_ext is None:
                name = (photo.filename or "").lower()
                for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                    if name.endswith("." + ext):
                        photo_ext = "jpg" if ext == "jpeg" else ext
                        break
            if photo_ext is None:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "photo", "message": "Нужен скрин JPG, PNG или WEBP."},
                )
            if len(raw) > vpn_reviews.MAX_PHOTO_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "photo", "message": "Скрин слишком большой. Пришлите файл до 8 МБ."},
                )
            photo_bytes = raw
    cp = await vpn_billing.cp_status(telegram_id)
    subscription = vpn_billing.subscription_view(cp)
    try:
        created = await vpn_reviews.submit_and_notify(
            telegram_id=telegram_id,
            text=text,
            author=author,
            subscription=subscription,
            photo=photo_bytes,
            photo_ext=photo_ext,
        )
    except vpn_reviews.ReviewRejected as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    return {"id": created["id"], "status": "pending", "tier": created["tier"]}


@router.get("/review-reminders")
async def vpn_review_reminders(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        due = await vpn_reviews.due_reminders(conn)
    return {"reminders": due}


class ReviewNotifiedIn(BaseModel):
    telegram_id: int = Field(gt=0)
    window_at: datetime


@router.post("/review-notified")
async def vpn_review_notified(
    body: ReviewNotifiedIn,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        first = await vpn_reviews.mark_reminded(conn, body.telegram_id, body.window_at)
    return {"recorded": first}


@router.api_route("/crypto-invoice", methods=["POST"])
@router.api_route("/crypto-settle", methods=["POST"])
@router.api_route("/hold", methods=["POST"])
@router.api_route("/confirm", methods=["POST"])
@router.api_route("/release", methods=["POST"])
@router.api_route("/quote", methods=["POST"])
async def vpn_gone():
    raise HTTPException(status_code=410, detail="Removed: use /purchase")

import os
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from auth import (
    bearer_scheme,
    decode_token,
    get_web_user_by_id,
    get_web_user_by_session,
    resolve_client_user_id,
)
from fastapi.security import HTTPAuthorizationCredentials

from client_ip import get_client_ip
from panel_cookies import read_user_cookie
from order_service import (
    attach_receipt,
    cancel_web_order,
    confirm_order_paid,
    create_web_order,
    get_order_for_user,
    payfast_requisites_are_closed,
)

router = APIRouter()

RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts"))


def _ensure_receipts_dir() -> Path:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    probe = RECEIPTS_DIR / ".write_probe"
    try:
        probe.write_bytes(b"")
        probe.unlink(missing_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=503,
            detail="Receipt storage unavailable (server permissions)",
        ) from e
    return RECEIPTS_DIR


class CreateOrderBody(BaseModel):
    direction: Literal["buy", "sell"]
    crypto: str
    network: Optional[str] = None
    fiat_amount: Optional[float] = None
    crypto_amount: Optional[float] = None
    requisites: str
    sub_token: Optional[str] = None
    plan_mode: Optional[str] = None
    payin_round_up: bool = False


class PayinPreviewBody(BaseModel):
    fiat_amount: float = Field(gt=0)
    sub_token: str = "SBPRUB"


async def resolve_orders_user_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> int:
    """Заказы только для авторизованных: Bearer-токен или постоянная cookie-сессия.
    Гостевые заказы на сайте отключены — требуется регистрация/вход."""
    if credentials and credentials.scheme.lower() == "bearer":
        payload = decode_token(credentials.credentials)
        if payload.get("scope") == "user" and payload.get("sub"):
            user = await get_web_user_by_id(int(payload["sub"]))
            if user:
                return resolve_client_user_id(dict(user))

    raw_token = read_user_cookie(request)
    if raw_token:
        user = await get_web_user_by_session(raw_token)
        if user:
            return resolve_client_user_id(dict(user))

    raise HTTPException(
        status_code=401,
        detail="Войдите или зарегистрируйтесь, чтобы оформить заказ",
    )


def order_source_from_bearer(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str:
    """Miniapp bearer carries via=tg_miniapp. Cookie and site logins stay site."""
    from order_source import ORDER_SOURCE_SITE, order_source_for_via

    if not credentials or credentials.scheme.lower() != "bearer":
        return ORDER_SOURCE_SITE
    payload = decode_token(credentials.credentials)
    return order_source_for_via(payload.get("via"))


@router.post("/orders/payin-preview")
async def payin_preview_route(
    body: PayinPreviewBody,
    user_id: int = Depends(resolve_orders_user_id),
):
    from buy_order_web import payin_preview

    return await payin_preview(int(body.fiat_amount), body.sub_token, user_id)


@router.post("/orders/payin-fit")
async def payin_fit_route(
    body: PayinPreviewBody,
    user_id: int = Depends(resolve_orders_user_id),
):
    from buy_order_web import payin_fit_preview

    return await payin_fit_preview(int(body.fiat_amount), body.sub_token, user_id)


@router.get("/orders/active")
async def get_active_order_route(
    request: Request,
    user_id: int = Depends(resolve_orders_user_id),
):
    from order_service import get_active_web_order

    from buyer_payout_notify import recent_payout_sent

    order = await get_active_web_order(user_id, get_client_ip(request))
    try:
        payout_sent = await recent_payout_sent(user_id)
    except Exception:
        payout_sent = None
    if not order:
        return {"active": False, "payout_sent": payout_sent}
    return {"active": True, "order": order, "payout_sent": payout_sent}


@router.get("/orders/payout-track")
async def payout_track_route(user_id: int = Depends(resolve_orders_user_id)):
    from payout_track import payout_track_for_user

    return await payout_track_for_user(user_id)


class PayoutPushBody(BaseModel):
    quote_rub: float = Field(gt=0, le=1_000_000)
    fee_rate_sat_vb: Optional[float] = Field(None, gt=0, le=10_000)


class PayoutWalletConfirmBody(BaseModel):
    action: Literal["confirm", "replace"]
    address: Optional[str] = Field(None, max_length=200)


@router.post("/orders/{order_id}/payout-wallet-confirm")
async def payout_wallet_confirm_route(
    order_id: str,
    body: PayoutWalletConfirmBody,
    user_id: int = Depends(resolve_orders_user_id),
):
    from payout_wallet_confirm import apply_client_decision

    return await apply_client_decision(
        order_id=order_id,
        user_id=user_id,
        action=body.action,
        address=body.address,
    )


@router.post("/orders/{order_id}/payout-push")
async def payout_push_route(
    order_id: str,
    body: PayoutPushBody,
    user_id: int = Depends(resolve_orders_user_id),
):
    from payout_track import PushError, push_payout

    try:
        return await push_payout(user_id, order_id, body.quote_rub, body.fee_rate_sat_vb)
    except PushError as exc:
        status = 409 if exc.code in ("price_changed", "busy", "unknown") else 400
        if exc.code == "not_found":
            status = 404
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message, **exc.extra},
        ) from exc


@router.post("/orders")
async def create_order(
    request: Request,
    body: CreateOrderBody,
    x_device_fingerprint: Optional[str] = Header(None, alias="X-Device-Fingerprint"),
    user_id: int = Depends(resolve_orders_user_id),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    order = await create_web_order(
        user_id=user_id,
        direction=body.direction,
        crypto=body.crypto.lower(),
        network=body.network,
        fiat_amount=body.fiat_amount,
        crypto_amount=body.crypto_amount,
        requisites=body.requisites,
        sub_token=body.sub_token,
        plan_mode=body.plan_mode,
        client_ip=client_ip,
        user_agent=user_agent,
        fingerprint=x_device_fingerprint,
        payin_round_up=body.payin_round_up,
        order_source=order_source_from_bearer(credentials),
    )
    return order


@router.post("/orders/requisite-retry")
async def requisite_retry_route(
    request: Request,
    user_id: int = Depends(resolve_orders_user_id),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
):
    """Повтор сохранённого запроса реквизитов. Черновик заявкой не становится."""
    from requisite_retry import fulfill_open_retry

    return await fulfill_open_retry(
        user_id=user_id,
        client_ip=get_client_ip(request),
        order_source=order_source_from_bearer(credentials),
    )


@router.get("/orders/{order_id}")
async def get_order(
    request: Request,
    order_id: str,
    user_id: int = Depends(resolve_orders_user_id),
):
    order = await get_order_for_user(order_id, user_id, get_client_ip(request))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/orders/{order_id}/confirm-paid")
async def confirm_paid(
    request: Request,
    order_id: str,
    user_id: int = Depends(resolve_orders_user_id),
):
    return await confirm_order_paid(order_id, user_id, get_client_ip(request))


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    request: Request,
    order_id: str,
    user_id: int = Depends(resolve_orders_user_id),
):
    return await cancel_web_order(order_id, user_id, get_client_ip(request))


@router.get("/orders/{order_id}/payout-receipt")
async def download_payout_receipt(
    request: Request,
    order_id: str,
    user_id: int = Depends(resolve_orders_user_id),
):
    """Чек о выплате по SELL: файл, приложенный оператором к чеку заявки."""
    from db import get_pool
    from payout_requisite_receipts import doliv_receipt_response

    order = await get_order_for_user(order_id, user_id, get_client_ip(request))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["direction"] != "sell":
        raise HTTPException(status_code=404, detail="Чек выплаты есть только по продаже")

    pool = await get_pool()
    async with pool.acquire() as conn:
        receipt = await conn.fetchval(
            """
            SELECT receipt_file
            FROM payout_requisite_allocations
            WHERE order_id = $1 AND status = 'PAID' AND receipt_file IS NOT NULL
            ORDER BY paid_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            order_id,
        )
    return doliv_receipt_response(receipt)


@router.post("/orders/{order_id}/payout-receipt/confirm")
async def confirm_payout_receipt(
    request: Request,
    order_id: str,
    user_id: int = Depends(resolve_orders_user_id),
):
    from payout_client_receipt import confirm_payout_receipt as confirm

    order = await get_order_for_user(order_id, user_id, get_client_ip(request))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return await confirm(order_id, user_id)


@router.post("/orders/{order_id}/receipt")
async def upload_receipt(
    request: Request,
    order_id: str,
    file: UploadFile = File(...),
    user_id: int = Depends(resolve_orders_user_id),
):
    from db import get_pool
    from receipt_public_url import build_receipt_public_url
    from receipt_validation import (
        ALLOWED_VIDEO_EXTENSIONS,
        MAX_RECEIPT_PDF_BYTES,
        MAX_RECEIPT_VIDEO_BYTES,
        is_valid_pdf_bytes,
        is_valid_video_bytes,
    )

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1 AND user_id = $2",
            order_id,
            user_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    if row["status"] != "AWAITING_CHECK":
        raise HTTPException(status_code=400, detail="Receipt not expected now")
    if payfast_requisites_are_closed(row):
        raise HTTPException(
            status_code=409,
            detail="Реквизиты закрыты. Если перевод уже отправлен, напишите оператору.",
        )

    req_type = int(row.get("required_receipt_type") or 2)
    filename = (file.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""

    if req_type == 3:
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="Only video files are accepted (MP4, MOV, WebM, MKV, AVI)",
            )
        max_size = MAX_RECEIPT_VIDEO_BYTES
    else:
        if ext != "pdf":
            raise HTTPException(status_code=400, detail="Only PDF receipts are accepted")
        max_size = MAX_RECEIPT_PDF_BYTES

    content = await file.read()
    if len(content) > max_size:
        limit_mb = max_size // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"File too large (max {limit_mb} MB)")

    if req_type == 3:
        if not is_valid_video_bytes(content):
            raise HTTPException(status_code=400, detail="Invalid video file")
    elif not is_valid_pdf_bytes(content):
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    _ensure_receipts_dir()
    receipt_id = uuid.uuid4().hex
    safe_ext = ext if ext.isalnum() else ("mp4" if req_type == 3 else "pdf")
    receipt_name = f"{receipt_id}.{safe_ext}"
    path = RECEIPTS_DIR / receipt_name
    path.write_bytes(content)

    receipt_url = build_receipt_public_url(receipt_name)

    return await attach_receipt(
        order_id, user_id, receipt_url, get_client_ip(request), receipt_name
    )

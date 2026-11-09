import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Header
from pydantic import BaseModel, Field, field_validator

from external_exchanger_accounts import exchanger_account_to_dict
from auth import (
    admin_user_to_dict,
    create_access_token,
    create_user_session,
    decode_token,
    ensure_bot_user,
    get_current_admin,
    get_current_operator,
    get_current_partner,
    get_current_exchanger,
    get_exchanger_account_by_id,
    get_exchanger_account_by_username,
    get_current_user,
    get_operator_by_id,
    get_operator_by_username,
    get_partner_account_by_id,
    get_partner_account_by_username,
    get_web_user_by_id,
    get_web_user_by_username,
    hash_password,
    link_telegram_to_web_user,
    operator_to_dict,
    operator_public_dict,
    partner_account_to_dict,
    register_password_web_user,
    reset_password_with_recovery_code,
    resolve_client_user_id,
    revoke_user_session,
    upsert_web_user_from_telegram,
    user_to_dict,
    validate_username,
    verify_password,
)
from config import settings
from panel_cookies import (
    clear_panel_cookie,
    clear_user_cookie,
    guest_session_trusted,
    read_user_cookie,
    set_panel_cookie,
    set_user_cookie,
)
from totp_auth import generate_totp_secret, totp_provisioning_uri, verify_totp_code
from db import get_pool
from telegram_auth import verify_telegram_login
from telegram_bot_login import (
    attach_telegram_to_start,
    consume_ticket,
    consume_wait,
    create_bot_login,
    sanitize_casino_return_path,
)
from guest_sessions import get_or_create_guest_user_id, merge_guest_orders_to_telegram
from chat_service import merge_guest_chat_to_telegram
from client_ip import get_client_ip
from web_attribution import resolve_pending_for_user

logger = logging.getLogger("auth_router")
from geoip_lookup import lookup_geo
from login_rate_limit import login_allowed
from security_access_log import insert_access_log
from security_alerts import send_security_alert
from security_threats import record_auth_failure

router = APIRouter()


async def _resolve_web_attribution(
    request: Request,
    real_user_id: int,
    x_guest_session: str | None,
    x_device_fingerprint: str | None,
) -> None:
    try:
        trusted_guest_session = (
            x_guest_session
            if guest_session_trusted(request, x_guest_session)
            else None
        )
        await resolve_pending_for_user(
            real_user_id,
            guest_session=trusted_guest_session,
            fingerprint=x_device_fingerprint,
            client_ip=get_client_ip(request),
        )
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)


def _login_rate_key(request: Request, username: str) -> str:
    return f"{get_client_ip(request)}:{username.strip().lower()}"


def _enforce_login_rate(request: Request, username: str) -> None:
    if not login_allowed(_login_rate_key(request, username)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Попробуйте позже.",
        )


def _partner_login_payload(account: dict) -> dict:
    """Ответ успешного входа партнёра (общий для /partner/login и редиректа с /login)."""
    if account.get("totp_enabled") and account.get("totp_secret"):
        pre = create_access_token(
            {"sub": str(account["id"]), "campaign_id": account["promo_campaign_id"]},
            scope="partner_preauth",
            expires_delta=timedelta(minutes=5),
        )
        return {
            "account_kind": "partner",
            "requires_2fa": True,
            "pre_auth_token": pre,
            "partner": partner_account_to_dict(account),
        }

    token = create_access_token(
        {"sub": str(account["id"]), "campaign_id": account["promo_campaign_id"]},
        scope="partner",
    )
    return {
        "account_kind": "partner",
        "access_token": token,
        "token_type": "bearer",
        "partner": partner_account_to_dict(account),
    }


async def _try_partner_login(username: str, password: str) -> dict | None:
    account = await get_partner_account_by_username(username)
    if (
        account
        and account.get("is_active")
        and verify_password(password, account["password_hash"])
    ):
        return _partner_login_payload(dict(account))
    return None


async def _log_admin_login(
    request: Request,
    *,
    ok: bool,
    user_id: int | None = None,
    username: str | None = None,
) -> None:
    ip = get_client_ip(request)
    if not ip:
        return
    country, city = lookup_geo(ip)
    ua = request.headers.get("user-agent")
    path = "/api/auth/admin/login"
    if ok:
        await insert_access_log(
            ip=ip,
            method="POST",
            path=path,
            status_code=200,
            latency_ms=0,
            zone="auth",
            user_agent=ua,
            scope="admin",
            user_id=user_id,
            country_code=country,
            city=city,
            threat_type="admin_login_ok",
            threat_score=0,
        )
        return
    await insert_access_log(
        ip=ip,
        method="POST",
        path=path,
        status_code=401,
        latency_ms=0,
        zone="auth",
        user_agent=ua,
        country_code=country,
        city=city,
        threat_type="auth_fail_admin",
        threat_score=40,
        extra={"username": (username or "")[:64]} if username else None,
    )
    alert_type = record_auth_failure(ip)
    if alert_type:
        send_security_alert(
            threat_type=alert_type,
            ip=ip,
            path=path,
            method="POST",
            status_code=401,
            city=city,
            country_code=country,
            zone="auth",
            extra={"username": username} if username else None,
        )


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str

    model_config = {"extra": "ignore"}


class AdminLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class AdminLogin2FARequest(BaseModel):
    pre_auth_token: str
    code: str


class UserLoginRequest(BaseModel):
    username: str
    password: str
    captcha_token: Optional[str] = None
    captcha_answer: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class UserLogin2FARequest(BaseModel):
    pre_auth_token: str
    code: str


class UserRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    captcha_token: Optional[str] = None
    captcha_answer: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


class UserChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


class ForgotPasswordRequest(BaseModel):
    username: str
    recovery_code: str
    new_password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


class OperatorLogin2FARequest(BaseModel):
    pre_auth_token: str
    code: str


class TotpConfirmRequest(BaseModel):
    code: str


class TotpDisableRequest(BaseModel):
    current_password: str
    code: str


def _login_response(
    response: Response,
    *,
    scope: str,
    token: str,
    body: dict,
    request: Request | None = None,
) -> dict:
    if settings.panel_http_only_cookies:
        set_panel_cookie(response, scope=scope, token=token, request=request)
    return {**body, "access_token": token, "token_type": "bearer"}


async def _issue_user_session(
    response: Response,
    request: Request,
    web_user_id: int,
    fingerprint: str | None,
) -> None:
    """Поставить постоянную HttpOnly-куку покупателя (вход без повторного логина)."""
    try:
        raw_token = await create_user_session(
            web_user_id,
            ip=get_client_ip(request),
            fingerprint=fingerprint,
        )
        set_user_cookie(response, raw_token, request=request)
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)


class TelegramBotStartRequest(BaseModel):
    return_path: Optional[str] = None


class TelegramBotCompleteRequest(BaseModel):
    ticket: str


class TelegramBotAttachRequest(BaseModel):
    start_token: str
    telegram_user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None


async def _finish_bot_telegram_login(
    request: Request,
    response: Response,
    login_row: dict,
    x_guest_session: str | None,
    x_device_fingerprint: str | None,
    via: str | None = None,
) -> dict:
    tg_id = int(login_row["telegram_user_id"])
    first = (login_row.get("tg_first_name") or "") or ""
    display_name = first.strip() or None
    await ensure_bot_user(
        tg_id,
        username=login_row.get("tg_username"),
        first_name=login_row.get("tg_first_name"),
    )
    row = await upsert_web_user_from_telegram(tg_id, display_name)

    if x_guest_session:
        from panel_cookies import set_guest_cookie

        set_guest_cookie(response, x_guest_session, request)

    if x_guest_session and guest_session_trusted(request, x_guest_session):
        try:
            guest_id = await get_or_create_guest_user_id(x_guest_session)
            await merge_guest_orders_to_telegram(guest_id, tg_id)
            await merge_guest_chat_to_telegram(x_guest_session, tg_id)
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    await _resolve_web_attribution(request, tg_id, x_guest_session, x_device_fingerprint)
    await _issue_user_session(response, request, int(row["id"]), x_device_fingerprint)
    claims: dict = {"sub": str(row["id"])}
    if via:
        claims["via"] = via
    token = create_access_token(claims, scope="user")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_dict(row),
        "return_path": sanitize_casino_return_path(login_row.get("return_path")),
    }


class CasinoMiniAppAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16384)


@router.post("/casino/telegram-miniapp")
async def auth_casino_miniapp(
    body: CasinoMiniAppAuthRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    from casino_miniapp_auth import verify_casino_init_data

    tg = verify_casino_init_data(body.init_data, settings.casino_telegram_bot_token)
    return await _finish_bot_telegram_login(request, response, {
        "telegram_user_id": tg['id'], "tg_username": tg.get('username'),
        "tg_first_name": tg.get('first_name'), "return_path": "/casino",
    }, x_guest_session, x_device_fingerprint)


@router.post("/exchange/telegram-miniapp")
async def auth_exchange_miniapp(
    body: CasinoMiniAppAuthRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Вход в миниапп обменника. Подпись initData — токен обменного бота, не казино."""
    from casino_miniapp_auth import verify_casino_init_data

    from order_source import ORDER_VIA_TG_MINIAPP

    tg = verify_casino_init_data(body.init_data, settings.telegram_bot_token)
    payload = await _finish_bot_telegram_login(request, response, {
        "telegram_user_id": tg["id"], "tg_username": tg.get("username"),
        "tg_first_name": tg.get("first_name"), "return_path": "/exchange/tg",
    }, x_guest_session, x_device_fingerprint, via=ORDER_VIA_TG_MINIAPP)
    payload["return_path"] = "/exchange/tg"
    return payload


class PartnerLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


@router.post("/telegram")
async def auth_telegram(
    body: TelegramAuthRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Вход покупателя через Telegram Login Widget."""
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=503,
            detail="Telegram bot token not configured on server",
        )

    tg = verify_telegram_login(body.model_dump())

    display_name = tg.get("first_name") or ""
    if tg.get("last_name"):
        display_name = f"{display_name} {tg['last_name']}".strip()

    await ensure_bot_user(
        tg["id"],
        username=tg.get("username"),
        first_name=tg.get("first_name"),
    )
    row = await upsert_web_user_from_telegram(tg["id"], display_name or None)

    # Установить guest cookie перед проверкой merge
    if x_guest_session:
        from panel_cookies import set_guest_cookie
        set_guest_cookie(response, x_guest_session, request)

    if x_guest_session and guest_session_trusted(request, x_guest_session):
        try:
            guest_id = await get_or_create_guest_user_id(x_guest_session)
            await merge_guest_orders_to_telegram(guest_id, tg["id"])
            await merge_guest_chat_to_telegram(x_guest_session, tg["id"])
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)

    await _resolve_web_attribution(
        request, tg["id"], x_guest_session, x_device_fingerprint
    )

    await _issue_user_session(response, request, int(row["id"]), x_device_fingerprint)

    token = create_access_token({"sub": str(row["id"])}, scope="user")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_dict(row),
    }


@router.post("/telegram/bot-start")
async def auth_telegram_bot_start(
    body: TelegramBotStartRequest,
    request: Request,
):
    """Casino: one-time t.me/?start=cauth_ link. Browser keeps wait_token and polls."""
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=503,
            detail="Telegram bot token not configured on server",
        )
    _enforce_login_rate(request, "tg-bot-start")
    created = await create_bot_login(body.return_path)
    return {
        "deep_link": created["deep_link"],
        "wait_token": created["wait_token"],
        "expires_at": created["expires_at"],
        "return_path": created["return_path"],
    }


@router.get("/telegram/bot-wait")
async def auth_telegram_bot_wait(
    token: str,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Poll until the user pressed Start in the bot. Issues the same session as /auth/telegram."""
    status_name, row = await consume_wait(token)
    if status_name == "ready" and row:
        body = await _finish_bot_telegram_login(
            request, response, row, x_guest_session, x_device_fingerprint
        )
        return {"status": "ready", **body}
    return {"status": status_name}


@router.post("/telegram/bot-complete")
async def auth_telegram_bot_complete(
    body: TelegramBotCompleteRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """One-time ticket from the bot 'Open casino' button."""
    row = await consume_ticket(body.ticket)
    if not row:
        raise HTTPException(
            status_code=401,
            detail="Ссылка входа истекла или уже использована. Нажмите Start в боте ещё раз.",
        )
    body_out = await _finish_bot_telegram_login(
        request, response, row, x_guest_session, x_device_fingerprint
    )
    return {"status": "ready", **body_out}


def _verify_internal_bot_token(token: str | None) -> None:
    expected = (settings.internal_api_secret or settings.webhook_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API not configured")
    supplied = (token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/telegram/bot-attach")
async def auth_telegram_bot_attach(
    body: TelegramBotAttachRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Casino bot /start cauth_: mark the waiting site login. Same table as bot-start."""
    _verify_internal_bot_token(x_internal_token)
    attached = await attach_telegram_to_start(
        body.start_token,
        body.telegram_user_id,
        username=body.username,
        first_name=body.first_name,
    )
    if not attached:
        raise HTTPException(
            status_code=404,
            detail="Ссылка входа истекла. Вернитесь на сайт и нажмите «Войти» ещё раз.",
        )
    return {
        "ok": True,
        "url": attached["url"],
        "return_path": attached["return_path"],
    }


@router.post("/register")
async def auth_register(
    body: UserRegisterRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Регистрация покупателя: username + пароль. Возвращает разовый recovery-код."""
    _enforce_login_rate(request, body.username)
    from math_captcha import verify_captcha

    if not await verify_captcha(
        body.captcha_token,
        body.captcha_answer,
        guest_session=x_guest_session,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    ):
        raise HTTPException(status_code=400, detail="Неверный ответ на проверку. Обновите страницу и попробуйте снова.")

    # Установить guest cookie если есть
    if x_guest_session:
        from panel_cookies import set_guest_cookie
        set_guest_cookie(response, x_guest_session, request)

    try:
        row = await register_password_web_user(
            body.username,
            body.password,
            body.display_name,
            signup_ip=get_client_ip(request),
            fingerprint=x_device_fingerprint,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    recovery_code = row.pop("recovery_code", None)

    await _resolve_web_attribution(
        request,
        int(row["client_user_id"]),
        x_guest_session,
        x_device_fingerprint,
    )

    await _issue_user_session(response, request, int(row["id"]), x_device_fingerprint)

    token = create_access_token({"sub": str(row["id"])}, scope="user")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_dict(row),
        "recovery_code": recovery_code,
    }


@router.post("/login")
async def auth_login(
    body: UserLoginRequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Вход покупателя: username + пароль."""
    _enforce_login_rate(request, body.username)
    from math_captcha import verify_captcha

    if not await verify_captcha(
        body.captcha_token,
        body.captcha_answer,
        guest_session=x_guest_session,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    ):
        raise HTTPException(status_code=400, detail="Неверный ответ на проверку. Обновите страницу и попробуйте снова.")

    # Установить guest cookie если есть
    if x_guest_session:
        from panel_cookies import set_guest_cookie
        set_guest_cookie(response, x_guest_session, request)

    user = await get_web_user_by_username(body.username)
    if (
        not user
        or user.get("is_admin")
        or not user.get("password_hash")
        or not verify_password(body.password, user["password_hash"])
    ):
        partner_payload = await _try_partner_login(body.username, body.password)
        if partner_payload:
            return partner_payload
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    if user.get("totp_enabled") and user.get("totp_secret"):
        pre = create_access_token(
            {"sub": str(user["id"])},
            scope="user_preauth",
            expires_delta=timedelta(minutes=5),
        )
        return {
            "requires_2fa": True,
            "pre_auth_token": pre,
            "user": user_to_dict(dict(user)),
        }

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET last_login_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            user["id"],
        )

    await _resolve_web_attribution(
        request,
        resolve_client_user_id(dict(user)),
        x_guest_session,
        x_device_fingerprint,
    )

    await _issue_user_session(response, request, int(user["id"]), x_device_fingerprint)

    token = create_access_token({"sub": str(user["id"])}, scope="user")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_dict(dict(user)),
    }


@router.post("/login/2fa")
async def auth_login_2fa(
    body: UserLogin2FARequest,
    request: Request,
    response: Response,
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    payload = decode_token(body.pre_auth_token)
    if payload.get("scope") != "user_preauth":
        raise HTTPException(status_code=401, detail="Invalid pre-auth token")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Установить guest cookie если есть
    if x_guest_session:
        from panel_cookies import set_guest_cookie
        set_guest_cookie(response, x_guest_session, request)

    user = await get_web_user_by_id(int(user_id))
    if (
        not user
        or user.get("is_admin")
        or not user.get("totp_enabled")
        or not user.get("totp_secret")
    ):
        raise HTTPException(status_code=403, detail="2FA not configured")

    if not verify_totp_code(user["totp_secret"], body.code):
        _enforce_login_rate(request, user.get("username") or str(user_id))
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET last_login_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            user["id"],
        )

    await _resolve_web_attribution(
        request,
        resolve_client_user_id(dict(user)),
        x_guest_session,
        x_device_fingerprint,
    )

    await _issue_user_session(response, request, int(user["id"]), x_device_fingerprint)

    token = create_access_token({"sub": str(user["id"])}, scope="user")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_dict(dict(user)),
    }


@router.post("/telegram/link")
async def auth_telegram_link(
    body: TelegramAuthRequest,
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    x_guest_session: str | None = Header(None, alias="X-Guest-Session"),
    x_device_fingerprint: str | None = Header(None, alias="X-Device-Fingerprint"),
):
    """Привязать Telegram к password-аккаунту."""
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot token not configured")

    # Установить guest cookie если есть
    if x_guest_session:
        from panel_cookies import set_guest_cookie
        set_guest_cookie(response, x_guest_session, request)

    tg = verify_telegram_login(body.model_dump())
    row = await link_telegram_to_web_user(current_user, int(tg["id"]))
    if x_guest_session and guest_session_trusted(request, x_guest_session):
        try:
            guest_id = await get_or_create_guest_user_id(x_guest_session)
            await merge_guest_orders_to_telegram(guest_id, int(tg["id"]))
            await merge_guest_chat_to_telegram(x_guest_session, int(tg["id"]))
        except Exception:
            logger.debug("ignored non-fatal error", exc_info=True)
    await _resolve_web_attribution(
        request, int(tg["id"]), x_guest_session, x_device_fingerprint
    )
    return {"user": user_to_dict(row)}


@router.post("/totp/setup")
async def user_totp_setup(current_user: dict = Depends(get_current_user)):
    secret = generate_totp_secret()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_secret = $1, totp_enabled = FALSE WHERE id = $2",
            secret,
            current_user["id"],
        )
    username = current_user.get("username") or str(current_user["id"])
    return {
        "secret": secret,
        "uri": totp_provisioning_uri(secret=secret, username=username),
        "enabled": False,
    }


@router.post("/totp/confirm")
async def user_totp_confirm(
    body: TotpConfirmRequest,
    current_user: dict = Depends(get_current_user),
):
    secret = current_user.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала вызовите /totp/setup")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Неверный код. Проверьте время на телефоне.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_enabled = TRUE WHERE id = $1",
            current_user["id"],
        )
    return {"ok": True, "enabled": True}


@router.post("/totp/disable")
async def user_totp_disable(
    body: TotpDisableRequest,
    current_user: dict = Depends(get_current_user),
):
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль")
    if not verify_totp_code(current_user.get("totp_secret"), body.code):
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_secret = NULL, totp_enabled = FALSE WHERE id = $1",
            current_user["id"],
        )
    return {"ok": True, "enabled": False}


@router.post("/change-password")
async def user_change_password(
    body: UserChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    if verify_password(body.new_password, pw_hash):
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET password_hash = $1 WHERE id = $2",
            hash_password(body.new_password),
            current_user["id"],
        )
    return {"ok": True}


@router.post("/admin/login")
async def admin_login(body: AdminLoginRequest, request: Request, response: Response):
    """Вход в админ-панель: username + пароль (только учётки с is_admin=true)."""
    _enforce_login_rate(request, body.username)
    user = await get_web_user_by_username(body.username)
    if (
        not user
        or not user.get("is_admin")
        or not user.get("password_hash")
        or not verify_password(body.password, user["password_hash"])
    ):
        await _log_admin_login(request, ok=False, username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    if user.get("totp_enabled") and user.get("totp_secret"):
        pre = create_access_token(
            {"sub": str(user["id"])},
            scope="admin_preauth",
            expires_delta=timedelta(minutes=5),
        )
        return {
            "requires_2fa": True,
            "pre_auth_token": pre,
            "user": admin_user_to_dict(dict(user)),
        }

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET last_login_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            user["id"],
        )

    token = create_access_token({"sub": str(user["id"])}, scope="admin")
    await _log_admin_login(request, ok=True, user_id=int(user["id"]))
    return _login_response(
        response,
        scope="admin",
        token=token,
        body={"user": admin_user_to_dict(dict(user))},
        request=request,
    )


@router.post("/admin/login/2fa")
async def admin_login_2fa(body: AdminLogin2FARequest, request: Request, response: Response):
    payload = decode_token(body.pre_auth_token)
    if payload.get("scope") != "admin_preauth":
        raise HTTPException(status_code=401, detail="Invalid pre-auth token")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = await get_web_user_by_id(int(user_id))
    if (
        not user
        or not user.get("is_admin")
        or not user.get("totp_enabled")
        or not user.get("totp_secret")
    ):
        raise HTTPException(status_code=403, detail="2FA not configured")

    if not verify_totp_code(user["totp_secret"], body.code):
        await _log_admin_login(request, ok=False, username=user.get("username"))
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET last_login_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            user["id"],
        )

    token = create_access_token({"sub": str(user["id"])}, scope="admin")
    await _log_admin_login(request, ok=True, user_id=int(user["id"]))
    return _login_response(
        response,
        scope="admin",
        token=token,
        body={"user": admin_user_to_dict(dict(user))},
        request=request,
    )


@router.post("/admin/totp/setup")
async def admin_totp_setup(current_user: dict = Depends(get_current_admin)):
    secret = generate_totp_secret()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_secret = $1, totp_enabled = FALSE WHERE id = $2",
            secret,
            current_user["id"],
        )
    username = current_user.get("username") or str(current_user["id"])
    return {
        "secret": secret,
        "uri": totp_provisioning_uri(secret=secret, username=username),
        "enabled": False,
    }


@router.post("/admin/totp/confirm")
async def admin_totp_confirm(
    body: TotpConfirmRequest,
    current_user: dict = Depends(get_current_admin),
):
    secret = current_user.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала вызовите /admin/totp/setup")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Неверный код. Проверьте время на телефоне.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_enabled = TRUE WHERE id = $1",
            current_user["id"],
        )
    return {"ok": True, "enabled": True}


@router.post("/admin/totp/disable")
async def admin_totp_disable(
    body: TotpDisableRequest,
    current_user: dict = Depends(get_current_admin),
):
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль")
    if not verify_totp_code(current_user.get("totp_secret"), body.code):
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET totp_secret = NULL, totp_enabled = FALSE WHERE id = $1",
            current_user["id"],
        )
    return {"ok": True, "enabled": False}


@router.post("/admin/logout")
async def admin_logout(response: Response, _admin=Depends(get_current_admin)):
    if settings.panel_http_only_cookies:
        clear_panel_cookie(response, scope="admin")
    return {"ok": True}


@router.get("/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET last_login_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            current_user["id"],
        )
    return {"user": user_to_dict(current_user)}


@router.post("/logout")
async def auth_logout(request: Request, response: Response):
    """Выход покупателя: отозвать cookie-сессию и очистить куку."""
    raw_token = read_user_cookie(request)
    if raw_token:
        await revoke_user_session(raw_token)
    clear_user_cookie(response)
    return {"ok": True}


@router.post("/forgot/recover")
async def auth_forgot_recover(body: ForgotPasswordRequest, request: Request):
    """Сброс пароля по recovery-коду. Возвращает НОВЫЙ recovery-код."""
    _enforce_login_rate(request, body.username)
    try:
        new_code = await reset_password_with_recovery_code(
            body.username,
            body.recovery_code,
            body.new_password,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "recovery_code": new_code}


@router.get("/admin/me")
async def admin_me(current_user: dict = Depends(get_current_admin)):
    from permissions import enrich_admin_permissions

    enriched = await enrich_admin_permissions(current_user)
    user = admin_user_to_dict(enriched)
    user["permissions"] = enriched.get("permissions") or []
    user["rbac_role"] = "ADMIN"
    return {"user": user}


class AdminChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


@router.post("/admin/change-password")
async def admin_change_password(
    body: AdminChangePasswordRequest,
    current_user: dict = Depends(get_current_admin),
):
    """Смена пароля текущего администратора."""
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    if verify_password(body.new_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_users SET password_hash = $1 WHERE id = $2",
            hash_password(body.new_password),
            current_user["id"],
        )
    return {"ok": True}


class PartnerLogin2FARequest(BaseModel):
    pre_auth_token: str
    code: str


class PartnerChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


@router.post("/partner/login")
async def partner_login(body: PartnerLoginRequest, request: Request):
    """Вход в кабинет партнёра: username + пароль."""
    _enforce_login_rate(request, body.username)
    account = await get_partner_account_by_username(body.username)
    if (
        not account
        or not account.get("is_active")
        or not verify_password(body.password, account["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    return _partner_login_payload(dict(account))


@router.post("/partner/login/2fa")
async def partner_login_2fa(body: PartnerLogin2FARequest, request: Request):
    payload = decode_token(body.pre_auth_token)
    if payload.get("scope") != "partner_preauth":
        raise HTTPException(status_code=401, detail="Invalid pre-auth token")
    account_id = payload.get("sub")
    if account_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    account = await get_partner_account_by_id(int(account_id))
    if (
        not account
        or not account.get("is_active")
        or not account.get("totp_enabled")
        or not account.get("totp_secret")
    ):
        raise HTTPException(status_code=403, detail="2FA not configured")

    if not verify_totp_code(account["totp_secret"], body.code):
        _enforce_login_rate(request, account.get("username") or str(account_id))
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    token = create_access_token(
        {"sub": str(account["id"]), "campaign_id": account["promo_campaign_id"]},
        scope="partner",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "partner": partner_account_to_dict(dict(account)),
    }


@router.get("/partner/me")
async def partner_me(partner=Depends(get_current_partner)):
    return {"partner": partner_account_to_dict(partner)}


@router.post("/partner/change-password")
async def partner_change_password(
    body: PartnerChangePasswordRequest,
    partner=Depends(get_current_partner),
):
    """Смена пароля текущего партнёра."""
    pw_hash = partner.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    if verify_password(body.new_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE partner_accounts SET password_hash = $1 WHERE id = $2",
            hash_password(body.new_password),
            partner["id"],
        )
    return {"ok": True}


@router.post("/partner/totp/setup")
async def partner_totp_setup(partner=Depends(get_current_partner)):
    secret = generate_totp_secret()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE partner_accounts
            SET totp_secret = $1, totp_enabled = FALSE
            WHERE id = $2
            """,
            secret,
            partner["id"],
        )
    username = partner.get("username") or str(partner["id"])
    return {
        "secret": secret,
        "uri": totp_provisioning_uri(
            secret=secret,
            username=username,
            issuer="FocusPay Partner",
        ),
        "enabled": False,
    }


@router.post("/partner/totp/confirm")
async def partner_totp_confirm(
    body: TotpConfirmRequest,
    partner=Depends(get_current_partner),
):
    secret = partner.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала вызовите /partner/totp/setup")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Неверный код. Проверьте время на телефоне.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE partner_accounts SET totp_enabled = TRUE WHERE id = $1",
            partner["id"],
        )
    return {"ok": True, "enabled": True}


@router.post("/partner/totp/disable")
async def partner_totp_disable(
    body: TotpDisableRequest,
    partner=Depends(get_current_partner),
):
    pw_hash = partner.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль")
    if not verify_totp_code(partner.get("totp_secret"), body.code):
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE partner_accounts
            SET totp_secret = NULL, totp_enabled = FALSE
            WHERE id = $1
            """,
            partner["id"],
        )
    return {"ok": True, "enabled": False}


class ExchangerLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


class ExchangerChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


class ExchangerLogin2FARequest(BaseModel):
    pre_auth_token: str
    code: str


def _exchanger_login_payload(account: dict) -> dict:
    """Ответ успешного входа в кабинет магазина (с шагом 2FA, как у партнёра)."""
    claims = {
        "sub": str(account["id"]),
        "exchanger_id": account["external_exchanger_id"],
    }
    if account.get("totp_enabled") and account.get("totp_secret"):
        return {
            "requires_2fa": True,
            "pre_auth_token": create_access_token(
                claims,
                scope="exchanger_preauth",
                expires_delta=timedelta(minutes=5),
            ),
            "exchanger": exchanger_account_to_dict(account),
        }
    return {
        "access_token": create_access_token(claims, scope="exchanger"),
        "token_type": "bearer",
        "exchanger": exchanger_account_to_dict(account),
    }


@router.post("/exchanger/login")
async def exchanger_login(body: ExchangerLoginRequest, request: Request):
    """Вход в кабинет внештатника: username + пароль."""
    _enforce_login_rate(request, body.username)
    account = await get_exchanger_account_by_username(body.username)
    if (
        not account
        or not account.get("is_active")
        or not account.get("exchanger_is_active")
        or not verify_password(body.password, account["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    return _exchanger_login_payload(dict(account))


@router.post("/exchanger/login/2fa")
async def exchanger_login_2fa(body: ExchangerLogin2FARequest, request: Request):
    payload = decode_token(body.pre_auth_token)
    if payload.get("scope") != "exchanger_preauth":
        raise HTTPException(status_code=401, detail="Invalid pre-auth token")
    account_id = payload.get("sub")
    if account_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    account = await get_exchanger_account_by_id(int(account_id))
    if (
        not account
        or not account.get("exchanger_is_active")
        or not account.get("totp_enabled")
        or not account.get("totp_secret")
    ):
        raise HTTPException(status_code=403, detail="2FA not configured")

    if not verify_totp_code(account["totp_secret"], body.code):
        _enforce_login_rate(request, account.get("username") or str(account_id))
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    return {
        "access_token": create_access_token(
            {
                "sub": str(account["id"]),
                "exchanger_id": account["external_exchanger_id"],
            },
            scope="exchanger",
        ),
        "token_type": "bearer",
        "exchanger": exchanger_account_to_dict(dict(account)),
    }


@router.post("/exchanger/totp/setup")
async def exchanger_totp_setup(exchanger=Depends(get_current_exchanger)):
    secret = generate_totp_secret()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE external_exchanger_accounts
            SET totp_secret = $1, totp_enabled = FALSE
            WHERE id = $2
            """,
            secret,
            exchanger["id"],
        )
    username = exchanger.get("username") or str(exchanger["id"])
    return {
        "secret": secret,
        "uri": totp_provisioning_uri(
            secret=secret,
            username=username,
            issuer="FocusPay Shop",
        ),
        "enabled": False,
    }


@router.post("/exchanger/totp/confirm")
async def exchanger_totp_confirm(
    body: TotpConfirmRequest,
    exchanger=Depends(get_current_exchanger),
):
    secret = exchanger.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала вызовите /exchanger/totp/setup")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Неверный код. Проверьте время на телефоне.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE external_exchanger_accounts SET totp_enabled = TRUE WHERE id = $1",
            exchanger["id"],
        )
    return {"ok": True, "enabled": True}


@router.post("/exchanger/totp/disable")
async def exchanger_totp_disable(
    body: TotpDisableRequest,
    exchanger=Depends(get_current_exchanger),
):
    pw_hash = exchanger.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль")
    if not verify_totp_code(exchanger.get("totp_secret"), body.code):
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE external_exchanger_accounts
            SET totp_secret = NULL, totp_enabled = FALSE
            WHERE id = $1
            """,
            exchanger["id"],
        )
    return {"ok": True, "enabled": False}


@router.get("/exchanger/me")
async def exchanger_me(exchanger=Depends(get_current_exchanger)):
    return {"exchanger": exchanger_account_to_dict(exchanger)}


@router.post("/exchanger/change-password")
async def exchanger_change_password(
    body: ExchangerChangePasswordRequest,
    exchanger=Depends(get_current_exchanger),
):
    pw_hash = exchanger.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    if verify_password(body.new_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE external_exchanger_accounts SET password_hash = $1 WHERE id = $2",
            hash_password(body.new_password),
            exchanger["id"],
        )
    return {"ok": True}


class OperatorLoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return validate_username(v)


@router.post("/operator/login")
async def operator_login(body: OperatorLoginRequest, request: Request, response: Response):
    """Вход в кабинет оператора: username + пароль."""
    _enforce_login_rate(request, body.username)
    account = await get_operator_by_username(body.username)
    if (
        not account
        or not account.get("is_active")
        or not verify_password(body.password, account["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    if account.get("totp_enabled") and account.get("totp_secret"):
        pre = create_access_token(
            {"sub": str(account["id"])},
            scope="operator_preauth",
            expires_delta=timedelta(minutes=5),
        )
        return {
            "requires_2fa": True,
            "pre_auth_token": pre,
            "operator": operator_public_dict(dict(account)),
        }

    token = create_access_token({"sub": str(account["id"])}, scope="operator")
    return _login_response(
        response,
        scope="operator",
        token=token,
        body={"operator": operator_public_dict(dict(account))},
        request=request,
    )


@router.post("/operator/login/2fa")
async def operator_login_2fa(body: OperatorLogin2FARequest, request: Request, response: Response):
    payload = decode_token(body.pre_auth_token)
    if payload.get("scope") != "operator_preauth":
        raise HTTPException(status_code=401, detail="Invalid pre-auth token")
    operator_id = payload.get("sub")
    if operator_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    account = await get_operator_by_id(int(operator_id))
    if (
        not account
        or not account.get("is_active")
        or not account.get("totp_enabled")
        or not account.get("totp_secret")
    ):
        raise HTTPException(status_code=403, detail="2FA not configured")

    if not verify_totp_code(account["totp_secret"], body.code):
        _enforce_login_rate(request, account.get("username") or str(operator_id))
        raise HTTPException(status_code=401, detail="Неверный код 2FA")

    token = create_access_token({"sub": str(account["id"])}, scope="operator")
    return _login_response(
        response,
        scope="operator",
        token=token,
        body={"operator": operator_public_dict(dict(account))},
        request=request,
    )


@router.post("/operator/totp/setup")
async def operator_totp_setup(current_user: dict = Depends(get_current_operator)):
    secret = generate_totp_secret()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE operator_accounts
            SET totp_secret = $1, totp_enabled = FALSE
            WHERE id = $2
            """,
            secret,
            current_user["id"],
        )
    username = current_user.get("username") or str(current_user["id"])
    return {
        "secret": secret,
        "uri": totp_provisioning_uri(
            secret=secret,
            username=username,
            issuer="FocusPay Operator",
        ),
        "enabled": False,
    }


@router.post("/operator/totp/confirm")
async def operator_totp_confirm(
    body: TotpConfirmRequest,
    current_user: dict = Depends(get_current_operator),
):
    secret = current_user.get("totp_secret")
    if not secret:
        raise HTTPException(status_code=400, detail="Сначала вызовите /operator/totp/setup")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Неверный код. Проверьте время на телефоне.")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE operator_accounts SET totp_enabled = TRUE WHERE id = $1",
            current_user["id"],
        )
    return {"ok": True, "enabled": True}


@router.post("/operator/totp/disable")
async def operator_totp_disable(
    body: TotpDisableRequest,
    current_user: dict = Depends(get_current_operator),
):
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(status_code=400, detail="Неверный пароль")
    if not verify_totp_code(current_user.get("totp_secret"), body.code):
        raise HTTPException(status_code=400, detail="Неверный код 2FA")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE operator_accounts
            SET totp_secret = NULL, totp_enabled = FALSE
            WHERE id = $1
            """,
            current_user["id"],
        )
    return {"ok": True, "enabled": False}


class OperatorChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль — минимум 6 символов")
        return v


@router.post("/operator/change-password")
async def operator_change_password(
    body: OperatorChangePasswordRequest,
    current_user: dict = Depends(get_current_operator),
):
    """Смена пароля текущего оператора."""
    pw_hash = current_user.get("password_hash")
    if not pw_hash or not verify_password(body.current_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    if verify_password(body.new_password, pw_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE operator_accounts SET password_hash = $1 WHERE id = $2",
            hash_password(body.new_password),
            current_user["id"],
        )
    return {"ok": True}


@router.post("/operator/logout")
async def operator_logout(response: Response, _op=Depends(get_current_operator)):
    if settings.panel_http_only_cookies:
        clear_panel_cookie(response, scope="operator")
    return {"ok": True}


@router.get("/operator/me")
async def operator_me(op=Depends(get_current_operator)):
    from permissions import (
        PERM_FINANCE_PAYOUT,
        enrich_operator_permissions,
        has_permission,
        operator_is_senior,
    )

    enriched = await enrich_operator_permissions(op)
    public = operator_public_dict(enriched)
    public["permissions"] = enriched.get("permissions") or []
    public["rbac_role"] = "OPERATOR"
    try:
        public["can_adjust_balance"] = bool(
            has_permission(enriched, PERM_FINANCE_PAYOUT) or operator_is_senior(enriched)
        )
    except Exception:
        public["can_adjust_balance"] = bool(
            PERM_FINANCE_PAYOUT in (enriched.get("permissions") or [])
        )
    return {"operator": public}

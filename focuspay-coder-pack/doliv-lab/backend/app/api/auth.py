from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    extract_raw_token,
    get_current_user,
    revoke_token,
    security,
    verify_password,
)
from app.core.cookies import clear_auth_cookie, set_auth_cookie
from app.core.database import get_db
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserResponse
from app.services.rate_limit import check_login_rate_limit, record_login_failure

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_key(ip: str, login: str) -> str:
    return f"{ip}:{login.lower()}"


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ip = _client_ip(request)
    key = _rate_key(ip, data.login)
    await check_login_rate_limit(db, key)

    result = await db.execute(select(User).where(User.login == data.login))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        await record_login_failure(db, key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    user.last_login = datetime.now(timezone.utc)
    token = create_access_token(user.id, user.role, user.token_version or 0)
    set_auth_cookie(response, token, request)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return user


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Issue a new JWT for a valid non-revoked token (silent session extension)."""
    raw = extract_raw_token(request, credentials)
    if raw:
        await revoke_token(raw, db)
    token = create_access_token(user.id, user.role, user.token_version or 0)
    set_auth_cookie(response, token, request)
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Revokes the token server-side (if present) and clears the auth cookie."""
    raw = extract_raw_token(request, credentials)
    if raw:
        await revoke_token(raw, db)
    clear_auth_cookie(response, request)
    return {"message": "Logged out successfully"}

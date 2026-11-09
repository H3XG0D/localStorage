import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.cookies import AUTH_COOKIE_NAME
from app.core.database import get_db
from app.models import RevokedToken, User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _token_jti(raw_token: str) -> str:
    """Stable identifier for revocation: JWT jti claim or SHA-256 fallback."""
    try:
        payload = jwt.decode(
            raw_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
        jti = payload.get("jti")
        if jti:
            return str(jti)[:64]
    except JWTError:
        pass
    return hashlib.sha256(raw_token.encode()).hexdigest()[:64]


def create_access_token(user_id: int, role: UserRole, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "exp": expire,
        "jti": uuid.uuid4().hex,
        "tv": token_version,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def bump_token_version(user: User) -> None:
    """Invalidate all outstanding JWTs for this user (e.g. after password change)."""
    user.token_version = (user.token_version or 0) + 1


def extract_raw_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials and credentials.credentials:
        cred = credentials.credentials.strip()
        if cred and cred not in ("null", "undefined"):
            return cred
    return request.cookies.get(AUTH_COOKIE_NAME)


async def revoke_token(raw_token: str, db: AsyncSession) -> None:
    """Add token to revocation list and purge expired entries."""
    try:
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        exp_ts = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else datetime.now(timezone.utc)
    except JWTError:
        return

    jti = _token_jti(raw_token)
    if not (await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))).scalar_one_or_none():
        db.add(RevokedToken(jti=jti, expires_at=expires_at))

    await db.execute(
        delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(timezone.utc))
    )
    await db.flush()


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    raw_token = extract_raw_token(request, credentials)
    if not raw_token:
        raise credentials_exception

    try:
        payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub", 0))
        if not user_id:
            raise credentials_exception
    except (JWTError, ValueError):
        raise credentials_exception

    jti = _token_jti(raw_token)
    revoked = (
        await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
    ).scalar_one_or_none()
    if revoked:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception

    token_tv = payload.get("tv", 0)
    if int(token_tv) != int(user.token_version or 0):
        raise credentials_exception

    return user


def require_role(*roles: UserRole):
    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker


def require_admin():
    return require_role(UserRole.admin)


def require_owner():
    return require_role(UserRole.owner)

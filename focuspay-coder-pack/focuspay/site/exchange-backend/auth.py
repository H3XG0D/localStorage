from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
import hashlib
import re
import secrets

import bcrypt

from config import settings
from db import get_pool
from finance_access import is_finance_owner_admin, can_view_finance_admin

bearer_scheme = HTTPBearer(auto_error=False)


def _token_from_request(request: Request, credentials: HTTPAuthorizationCredentials | None, scope: str) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    from panel_cookies import read_panel_token

    return read_panel_token(request, scope)

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def validate_username(value: str) -> str:
    u = normalize_username(value)
    if not _USERNAME_RE.match(u):
        raise ValueError("username must be 3-32 chars: a-z, 0-9, underscore")
    return u


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def user_to_dict(row: dict) -> dict:
    """Покупательский профиль — без признака админа."""
    tg = row.get("telegram_user_id")
    return {
        "id": row["id"],
        "email": row.get("email"),
        "username": row.get("username"),
        "display_name": row.get("display_name"),
        "telegram_user_id": tg,
        "telegram_linked": tg is not None,
        "has_password": bool(row.get("password_hash")),
        "totp_enabled": bool(row.get("totp_enabled")),
        "is_admin": False,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def admin_user_to_dict(row: dict) -> dict:
    """Профиль оператора админ-панели."""
    user = {
        "id": row["id"],
        "username": row.get("username"),
        "display_name": row.get("display_name"),
        "telegram_user_id": row.get("telegram_user_id"),
        "is_admin": bool(row.get("is_admin")),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
    user["can_view_finance"] = can_view_finance_admin(user)
    user["is_finance_owner"] = is_finance_owner_admin(user)
    user["totp_enabled"] = bool(user.get("totp_enabled"))
    user.pop("totp_secret", None)
    user.pop("password_hash", None)
    return user


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    *,
    scope: str = "user",
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "scope": scope})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_web_user_by_username(username: str):
    u = normalize_username(username)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM web_users WHERE LOWER(username) = $1", u
        )


async def get_web_user_by_id(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM web_users WHERE id = $1", user_id)


async def get_web_user_by_telegram_id(telegram_user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM web_users WHERE telegram_user_id = $1", telegram_user_id
        )


# --- Постоянные cookie-сессии покупателя -----------------------------------

USER_SESSION_TTL_DAYS = 30


def _hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_user_session(
    user_id: int,
    *,
    ip: str | None = None,
    fingerprint: str | None = None,
) -> str:
    """Создать сессию и вернуть raw-токен для HttpOnly-куки (в БД — только хэш)."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_session_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=USER_SESSION_TTL_DAYS)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO web_user_sessions (user_id, token_hash, expires_at, ip, fingerprint)
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id,
            token_hash,
            expires_at,
            ip,
            fingerprint,
        )
    return raw_token


async def get_web_user_by_session(raw_token: str):
    if not raw_token:
        return None
    token_hash = _hash_session_token(raw_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.* FROM web_user_sessions s
            JOIN web_users u ON u.id = s.user_id
            WHERE s.token_hash = $1 AND s.revoked = FALSE AND s.expires_at > now()
            """,
            token_hash,
        )
        if row:
            await conn.execute(
                "UPDATE web_user_sessions SET last_seen_at = now() WHERE token_hash = $1",
                token_hash,
            )
    return row


async def revoke_user_session(raw_token: str) -> None:
    if not raw_token:
        return
    token_hash = _hash_session_token(raw_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_user_sessions SET revoked = TRUE WHERE token_hash = $1",
            token_hash,
        )


async def revoke_all_user_sessions(user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE web_user_sessions SET revoked = TRUE WHERE user_id = $1 AND revoked = FALSE",
            user_id,
        )


# --- Recovery-код для восстановления пароля (email не используется) ---------

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих 0/O, 1/I


def generate_recovery_code() -> str:
    """4 группы по 4 символа, например ABCD-EF23-GH45-JK67."""
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def normalize_recovery_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "").replace("-", "")


def hash_recovery_code(code: str) -> str:
    return bcrypt.hashpw(normalize_recovery_code(code).encode(), bcrypt.gensalt()).decode()


def verify_recovery_code(code: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(normalize_recovery_code(code).encode(), hashed.encode())
    except Exception:
        return False


# --- Антифрод: мультиаккаунты с одного устройства/IP -----------------------


async def count_recent_signups(
    fingerprint: str | None,
    ip: str | None,
    *,
    hours: int = 24,
) -> int:
    if not fingerprint and not ip:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM web_users
            WHERE created_at > now() - ($1 || ' hours')::interval
              AND (
                  ($2::text IS NOT NULL AND signup_fingerprint = $2)
                  OR ($3::text IS NOT NULL AND signup_ip = $3)
              )
            """,
            str(hours),
            fingerprint,
            ip,
        )


async def ensure_bot_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_users (user_id, username, first_name, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, now(), now())
            ON CONFLICT (user_id) DO UPDATE SET
                last_seen_at = now(),
                username = CASE
                    WHEN EXCLUDED.username IS NOT NULL THEN EXCLUDED.username
                    ELSE bot_users.username
                END,
                first_name = CASE
                    WHEN EXCLUDED.first_name IS NOT NULL THEN EXCLUDED.first_name
                    ELSE bot_users.first_name
                END
            """,
            user_id,
            username,
            first_name,
        )


async def upsert_web_user_from_telegram(
    telegram_user_id: int,
    display_name: str | None,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO web_users (telegram_user_id, display_name, is_admin, last_login_at)
            VALUES ($1, $2, FALSE, now())
            ON CONFLICT (telegram_user_id) DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, web_users.display_name),
                last_login_at = now()
            RETURNING *
            """,
            telegram_user_id,
            display_name,
        )
        if not row:
            row = await conn.fetchrow(
                "SELECT * FROM web_users WHERE telegram_user_id = $1",
                telegram_user_id,
            )
    return dict(row)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    # 1) Bearer JWT (legacy / localStorage)
    if credentials is not None and credentials.scheme.lower() == "bearer":
        payload = decode_token(credentials.credentials)
        scope = payload.get("scope", "user")
        if scope != "user":
            raise HTTPException(
                status_code=403,
                detail="Use the correct login for this token",
            )
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        user = await get_web_user_by_id(int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(user)

    # 2) Постоянная HttpOnly cookie-сессия покупателя
    from panel_cookies import read_user_cookie

    raw_token = read_user_cookie(request)
    if raw_token:
        user = await get_web_user_by_session(raw_token)
        if user:
            return dict(user)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_partner_account_by_id(account_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT pa.*, pc.id AS campaign_id, pc.code AS campaign_code, pc.name AS campaign_name,
                   pc.partner_commission_percent, pc.ad_spend_rub, pc.bonus_percent
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE pa.id = $1 AND pa.is_active = TRUE AND pc.is_active = TRUE
            """,
            account_id,
        )


async def get_partner_account_by_username(username: str):
    u = normalize_username(username)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT pa.*, pc.code AS campaign_code, pc.name AS campaign_name
            FROM partner_accounts pa
            JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
            WHERE LOWER(pa.username) = $1
            """,
            u,
        )


def partner_account_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row.get("display_name"),
        "campaign_id": row["promo_campaign_id"],
        "campaign_code": row.get("campaign_code"),
        "campaign_name": row.get("campaign_name"),
        "totp_enabled": bool(row.get("totp_enabled")),
    }


async def get_current_partner(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if payload.get("scope") != "partner":
        raise HTTPException(status_code=403, detail="Partner access required")
    account_id = payload.get("sub")
    campaign_id = payload.get("campaign_id")
    if account_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    row = await get_partner_account_by_id(int(account_id))
    if not row:
        raise HTTPException(status_code=403, detail="Partner access required")
    if campaign_id and int(campaign_id) != row["promo_campaign_id"]:
        raise HTTPException(status_code=403, detail="Invalid campaign in token")
    return dict(row)


async def get_exchanger_account_by_id(account_id: int):
    from external_exchanger_accounts import fetch_account_by_id

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await fetch_account_by_id(conn, account_id)


async def get_exchanger_account_by_username(username: str):
    from external_exchanger_accounts import fetch_account_by_username

    pool = await get_pool()
    async with pool.acquire() as conn:
        return await fetch_account_by_username(conn, username)


async def get_current_exchanger(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if payload.get("scope") != "exchanger":
        raise HTTPException(status_code=403, detail="Exchanger access required")
    account_id = payload.get("sub")
    exchanger_id = payload.get("exchanger_id")
    if account_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    row = await get_exchanger_account_by_id(int(account_id))
    if not row:
        raise HTTPException(status_code=403, detail="Exchanger access required")
    if exchanger_id and int(exchanger_id) != row["external_exchanger_id"]:
        raise HTTPException(status_code=403, detail="Invalid exchanger in token")
    return dict(row)


async def get_current_exchanger_owner(exchanger=Depends(get_current_exchanger)):
    """Только хозяин магазина: выводы, выпуск логинов кассиров."""
    from external_exchanger_accounts import is_owner_account

    if not is_owner_account(exchanger):
        raise HTTPException(
            status_code=403,
            detail="Доступно только владельцу магазина",
        )
    return exchanger


async def get_operator_by_username(username: str):
    u = normalize_username(username)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM operator_accounts WHERE LOWER(username) = $1", u
        )


async def get_operator_by_id(operator_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM operator_accounts WHERE id = $1", operator_id
        )


def operator_to_dict(row: dict) -> dict:
    from operator_avatars import operator_avatar_public_url

    roles = row.get("operator_roles") or [row.get("operator_role") or "client"]
    if isinstance(roles, str):
        roles = [roles]
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row.get("display_name"),
        "operator_role": row.get("operator_role") or roles[0],
        "operator_roles": list(roles),
        "is_active": row["is_active"],
        "avatar_url": operator_avatar_public_url(row.get("avatar_file_id")),
    }


def require_operator_role(operator: dict, *roles: str) -> dict:
    """Enforce operator capabilities server-side."""
    assigned = operator.get("operator_roles")
    if isinstance(assigned, str):
        assigned = [assigned]
    assigned = {str(role) for role in (assigned or [operator.get("operator_role") or "client"])}
    if roles and not assigned.intersection(roles):
        raise HTTPException(status_code=403, detail="Недостаточно прав для роли оператора")
    return operator


def require_operator_roles(*roles: str):
    """FastAPI Depends factory: get_current_operator + role check."""

    async def _dep(op: dict = Depends(get_current_operator)) -> dict:
        return require_operator_role(op, *roles)

    return _dep


def operator_public_dict(row: dict) -> dict:
    """Профиль оператора без % — не раскрываем формулу зарплаты."""
    from operator_avatars import operator_avatar_public_url

    roles = row.get("operator_roles") or [row.get("operator_role") or "client"]
    if isinstance(roles, str):
        roles = [roles]
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row.get("display_name"),
        "is_active": row["is_active"],
        "operator_role": row.get("operator_role") or roles[0],
        "operator_roles": list(roles),
        "totp_enabled": bool(row.get("totp_enabled")),
        "avatar_url": operator_avatar_public_url(row.get("avatar_file_id")),
    }


async def allocate_client_user_id() -> int:
    """Synthetic negative id из общего неймспейса с guest (без коллизий)."""
    from synthetic_user_ids import allocate_client_user_id as _alloc

    return await _alloc()


def resolve_client_user_id(web_user: dict) -> int:
    """Telegram ID приоритетнее synthetic client_user_id."""
    tg = web_user.get("telegram_user_id")
    if tg is not None:
        return int(tg)
    cid = web_user.get("client_user_id")
    if cid is not None:
        return int(cid)
    raise HTTPException(
        status_code=400,
        detail="Account has no client profile. Link Telegram or re-register.",
    )


async def register_password_web_user(
    username: str,
    password: str,
    display_name: str | None = None,
    *,
    signup_ip: str | None = None,
    fingerprint: str | None = None,
    max_accounts_per_device: int = 3,
) -> dict:
    """Регистрация покупателя. Возвращает строку аккаунта + разовый recovery-код
    под ключом 'recovery_code' (показывается клиенту один раз)."""
    u = validate_username(username)
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")

    # Антифрод: ограничение мультиаккаунтов с одного устройства/IP за сутки
    if max_accounts_per_device > 0:
        recent = await count_recent_signups(fingerprint, signup_ip, hours=24)
        if recent >= max_accounts_per_device:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много аккаунтов с этого устройства. Попробуйте позже.",
            )

    recovery_code = generate_recovery_code()
    recovery_hash = hash_recovery_code(recovery_code)

    client_user_id = await allocate_client_user_id()
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM web_users WHERE LOWER(username) = $1", u
        )
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken")

        row = await conn.fetchrow(
            """
            INSERT INTO web_users (
                username, password_hash, display_name, client_user_id,
                is_admin, last_login_at,
                recovery_code_hash, recovery_code_set_at, signup_ip, signup_fingerprint
            )
            VALUES ($1, $2, $3, $4, FALSE, now(), $5, now(), $6, $7)
            RETURNING *
            """,
            u,
            hash_password(password),
            display_name or u,
            client_user_id,
            recovery_hash,
            signup_ip,
            fingerprint,
        )

    await ensure_bot_user(
        client_user_id,
        username=u,
        first_name=display_name or u,
    )
    result = dict(row)
    result["recovery_code"] = recovery_code
    return result


async def reset_password_with_recovery_code(
    username: str,
    recovery_code: str,
    new_password: str,
) -> str:
    """Сброс пароля по recovery-коду. Возвращает НОВЫЙ recovery-код (ротация)."""
    if len(new_password) < 6:
        raise ValueError("password must be at least 6 characters")
    user = await get_web_user_by_username(username)
    if (
        not user
        or user.get("is_admin")
        or not user.get("password_hash")
        or not user.get("recovery_code_hash")
        or not verify_recovery_code(recovery_code, user["recovery_code_hash"])
    ):
        raise HTTPException(status_code=400, detail="Неверный логин или recovery-код")

    new_code = generate_recovery_code()
    new_code_hash = hash_recovery_code(new_code)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE web_users
            SET password_hash = $1,
                recovery_code_hash = $2,
                recovery_code_set_at = now()
            WHERE id = $3
            """,
            hash_password(new_password),
            new_code_hash,
            user["id"],
        )
    # Безопасность: после смены пароля гасим все активные сессии
    await revoke_all_user_sessions(int(user["id"]))
    return new_code


async def link_telegram_to_web_user(web_user: dict, telegram_user_id: int) -> dict:
    """Привязать Telegram к password-аккаунту и слить данные."""
    from client_user_merge import merge_client_user_to_telegram

    if web_user.get("telegram_user_id"):
        if int(web_user["telegram_user_id"]) == telegram_user_id:
            return dict(web_user)
        raise HTTPException(status_code=409, detail="Telegram already linked to this account")

    pool = await get_pool()
    async with pool.acquire() as conn:
        taken = await conn.fetchrow(
            """
            SELECT id FROM web_users
            WHERE telegram_user_id = $1 AND id != $2
            """,
            telegram_user_id,
            web_user["id"],
        )
        if taken:
            raise HTTPException(
                status_code=409,
                detail="This Telegram account is linked to another user",
            )

    client_user_id = web_user.get("client_user_id")
    if client_user_id:
        await merge_client_user_to_telegram(int(client_user_id), telegram_user_id)

    await ensure_bot_user(telegram_user_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE web_users
            SET telegram_user_id = $1,
                client_user_id = NULL,
                last_login_at = now()
            WHERE id = $2
            RETURNING *
            """,
            telegram_user_id,
            web_user["id"],
        )
    return dict(row)


async def get_current_operator(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    token = _token_from_request(request, credentials, "operator")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload.get("scope") != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")
    operator_id = payload.get("sub")
    if operator_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    row = await get_operator_by_id(int(operator_id))
    if not row or not row["is_active"]:
        raise HTTPException(status_code=403, detail="Operator access required")
    return dict(row)


# Depends aliases (после get_current_operator — factory вызывается здесь)
require_operator_finance = require_operator_roles("finance")
require_operator_client_or_finance = require_operator_roles("client", "finance")


async def get_current_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    token = _token_from_request(request, credentials, "admin")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if payload.get("scope") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await get_web_user_by_id(int(user_id))
    if not user or not user.get("is_admin") or not user.get("password_hash"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return dict(user)


async def get_current_finance_owner(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    admin = await get_current_admin(request, credentials)
    if not is_finance_owner_admin(admin):
        raise HTTPException(status_code=403, detail="Finance access restricted to owner")
    return admin


async def get_current_finance_viewer(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    admin = await get_current_admin(request, credentials)
    from permissions import PERM_FINANCE_ANALYTICS, enrich_admin_permissions, has_permission

    enriched = await enrich_admin_permissions(admin)
    # Связка Telegram admin IDs (can_view_finance) с единой RBAC-моделью.
    if not (
        can_view_finance_admin(enriched)
        or has_permission(enriched, PERM_FINANCE_ANALYTICS)
    ):
        raise HTTPException(status_code=403, detail="Finance access restricted")
    return enriched

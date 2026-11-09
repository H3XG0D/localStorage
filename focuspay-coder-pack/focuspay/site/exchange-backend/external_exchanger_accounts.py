"""Учётные записи кабинета внештатника (/exchanger).

На магазин один хозяин (owner) и любое число кассиров (clerk). Кассиру
недоступны выводы и выпуск логинов — гейт по role, см. ``is_owner_account``.
"""
from __future__ import annotations

import secrets

from config import settings
from auth import hash_password, normalize_username, validate_username

EXCHANGER_LOGIN_PATH = "/exchanger/login"
EXCHANGER_ROLES = ("owner", "clerk")
OWNER_ROLE = "owner"
CLERK_ROLE = "clerk"

_ACCOUNT_SELECT = """
    SELECT ea.*, ee.name AS exchanger_name, ee.is_active AS exchanger_is_active,
           ee.is_trusted_client, ee.auto_credit_on_payfast
    FROM external_exchanger_accounts ea
    JOIN external_exchangers ee ON ee.id = ea.external_exchanger_id
"""


def exchanger_login_url(site_base: str | None = None) -> str:
    base = (site_base or settings.public_site_url or "http://localhost:5173").rstrip("/")
    return f"{base}{EXCHANGER_LOGIN_PATH}"


def account_role(account_row) -> str:
    """Роль логина. Незнакомое/пустое значение считаем хозяином (legacy-строки)."""
    if not account_row:
        return OWNER_ROLE
    role = str(account_row.get("role") or OWNER_ROLE).strip().lower()
    return role if role in EXCHANGER_ROLES else OWNER_ROLE


def is_owner_account(account_row) -> bool:
    return account_role(account_row) == OWNER_ROLE


def credentials_response(username: str, password: str, *, role: str = OWNER_ROLE) -> dict:
    return {
        "username": username,
        "password": password,
        "role": role,
        "login_path": EXCHANGER_LOGIN_PATH,
        "login_url": exchanger_login_url(),
    }


def account_fields(account_row) -> dict:
    if not account_row:
        return {
            "has_account": False,
            "account_username": None,
            "login_path": EXCHANGER_LOGIN_PATH,
            "login_url": exchanger_login_url(),
        }
    return {
        "has_account": True,
        "account_username": account_row["username"],
        "login_path": EXCHANGER_LOGIN_PATH,
        "login_url": exchanger_login_url(),
    }


async def fetch_account_by_exchanger_id(conn, exchanger_id: int):
    """Логин хозяина магазина (кассиры сюда не попадают)."""
    return await conn.fetchrow(
        _ACCOUNT_SELECT
        + """
        WHERE ea.external_exchanger_id = $1 AND ea.role = 'owner'
        """,
        exchanger_id,
    )


async def fetch_accounts_for_exchanger(conn, exchanger_id: int):
    """Все логины магазина: хозяин первым, дальше кассиры по дате."""
    return await conn.fetch(
        _ACCOUNT_SELECT
        + """
        WHERE ea.external_exchanger_id = $1
        ORDER BY (ea.role = 'owner') DESC, ea.id
        """,
        exchanger_id,
    )


async def fetch_account_of_exchanger(conn, account_id: int, exchanger_id: int):
    """Логин по id, но только внутри своего магазина (для действий хозяина)."""
    return await conn.fetchrow(
        _ACCOUNT_SELECT
        + """
        WHERE ea.id = $1 AND ea.external_exchanger_id = $2
        """,
        account_id,
        exchanger_id,
    )


async def fetch_account_by_username(conn, username: str):
    u = normalize_username(username)
    return await conn.fetchrow(
        _ACCOUNT_SELECT
        + """
        WHERE LOWER(ea.username) = $1
        """,
        u,
    )


async def fetch_account_by_id(conn, account_id: int):
    return await conn.fetchrow(
        _ACCOUNT_SELECT
        + """
        WHERE ea.id = $1 AND ea.is_active = TRUE AND ee.is_active = TRUE
        """,
        account_id,
    )


async def username_taken(conn, username: str, *, exclude_account_id: int | None = None) -> bool:
    u = normalize_username(username)
    if exclude_account_id is not None:
        row = await conn.fetchval(
            """
            SELECT 1 FROM external_exchanger_accounts
            WHERE LOWER(username) = $1 AND id <> $2
            """,
            u,
            exclude_account_id,
        )
    else:
        row = await conn.fetchval(
            "SELECT 1 FROM external_exchanger_accounts WHERE LOWER(username) = $1",
            u,
        )
    if row:
        return True
    partner_dup = await conn.fetchval(
        "SELECT 1 FROM partner_accounts WHERE LOWER(username) = $1",
        u,
    )
    return bool(partner_dup)


async def create_exchanger_account(
    conn,
    exchanger_id: int,
    username: str,
    *,
    role: str = OWNER_ROLE,
    label: str | None = None,
    created_by_account_id: int | None = None,
) -> tuple[str, dict]:
    """Создаёт логин магазина, возвращает (password_plain, account_row)."""
    u = validate_username(username)
    if role not in EXCHANGER_ROLES:
        raise ValueError("invalid_role")
    if role == OWNER_ROLE:
        existing = await fetch_account_by_exchanger_id(conn, exchanger_id)
        if existing:
            raise ValueError("access_already_issued")
    if await username_taken(conn, u):
        raise ValueError("username_taken")

    password_plain = secrets.token_urlsafe(10)
    row = await conn.fetchrow(
        """
        INSERT INTO external_exchanger_accounts (
            external_exchanger_id, username, password_hash, role, label,
            created_by_account_id
        ) VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        exchanger_id,
        u,
        hash_password(password_plain),
        role,
        (label or "").strip() or None,
        created_by_account_id,
    )
    return password_plain, dict(row)


async def reset_account_password(conn, account_id: int) -> str:
    password_plain = secrets.token_urlsafe(10)
    await conn.execute(
        "UPDATE external_exchanger_accounts SET password_hash = $1 WHERE id = $2",
        hash_password(password_plain),
        account_id,
    )
    return password_plain


def exchanger_account_to_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "exchanger_id": row["external_exchanger_id"],
        "exchanger_name": row.get("exchanger_name"),
        "role": account_role(row),
        "is_owner": is_owner_account(row),
        "totp_enabled": bool(row.get("totp_enabled")),
    }


def account_public_dict(row) -> dict:
    """Карточка логина для списка (без секретов)."""
    data = dict(row)
    created = data.get("created_at")
    return {
        "id": data["id"],
        "username": data["username"],
        "role": account_role(data),
        "is_owner": is_owner_account(data),
        "label": data.get("label"),
        "is_active": bool(data.get("is_active", True)),
        "totp_enabled": bool(data.get("totp_enabled")),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }

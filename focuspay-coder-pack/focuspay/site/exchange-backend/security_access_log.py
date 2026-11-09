"""Запись событий доступа в security_access_log."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import jwt
from jwt.exceptions import InvalidTokenError as JWTError

from config import settings
from db import get_pool

logger = logging.getLogger("security_access")


def path_to_zone(path: str) -> str:
    p = (path or "").split("?")[0]
    if p.startswith("/api/admin"):
        return "admin"
    if p.startswith("/api/operator"):
        return "operator"
    if p.startswith("/api/partner"):
        return "partner"
    if p.startswith("/api/auth"):
        return "auth"
    if p.startswith("/api/user"):
        return "user"
    if p.startswith("/api/public"):
        return "public"
    return "api"


def parse_auth_header(authorization: str | None) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Returns (scope, user_id, operator_id) without raising.
    operator_id set when scope=operator; user_id for user/admin/partner sub.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None, None, None
    token = authorization[7:].strip()
    if not token:
        return None, None, None
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
    except JWTError:
        return None, None, None
    scope = payload.get("scope")
    sub = payload.get("sub")
    try:
        sub_id = int(sub) if sub is not None else None
    except (TypeError, ValueError):
        sub_id = None
    if scope == "operator":
        return scope, None, sub_id
    return scope, sub_id, None


async def insert_access_log(
    *,
    ip: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    zone: str,
    user_agent: str | None,
    scope: str | None = None,
    user_id: int | None = None,
    operator_id: int | None = None,
    country_code: str | None = None,
    city: str | None = None,
    threat_type: str | None = None,
    threat_score: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    if not ip:
        return
    extra_json = json.dumps(extra) if extra else None
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO security_access_log (
                    ip_address, method, path, status_code, latency_ms,
                    zone, user_id, operator_id, scope,
                    country_code, city, user_agent,
                    threat_type, threat_score, extra
                )
                VALUES (
                    $1::inet, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12,
                    $13, $14, $15::jsonb
                )
                """,
                ip,
                (method or "")[:10],
                (path or "")[:512],
                status_code,
                latency_ms,
                (zone or "api")[:20],
                user_id,
                operator_id,
                (scope or "")[:20] or None,
                (country_code or "")[:2] or None,
                (city or "")[:128] or None,
                (user_agent or "")[:2000] or None,
                (threat_type or "")[:40] or None,
                threat_score,
                extra_json,
            )
    except Exception as e:
        logger.warning("insert_access_log failed: %s", e)

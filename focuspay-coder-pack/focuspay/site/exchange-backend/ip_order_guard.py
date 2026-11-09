"""Логирование и лимиты веб-заявок по IP."""
import json
import logging
from typing import Any

from fastapi import HTTPException

from db import get_pool

logger = logging.getLogger("ip_order_guard")

ACTIVE_STATUSES = ("CREATED", "AWAITING_CHECK", "PENDING", "COMPLETED")


async def log_ip_event(
    *,
    ip: str,
    event: str,
    order_id: str | None = None,
    user_id: int | None = None,
    user_agent: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    pool = await get_pool()
    extra_json = json.dumps(extra) if extra else None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO web_order_ip_log (
                ip_address, event, order_id, user_id, user_agent, extra
            )
            VALUES ($1::inet, $2, $3, $4, $5, $6::jsonb)
            """,
            ip,
            event,
            order_id,
            user_id,
            (user_agent or "")[:500] or None,
            extra_json,
        )
    logger.info(
        "web_order_ip ip=%s event=%s order_id=%s user_id=%s",
        ip,
        event,
        order_id,
        user_id,
    )


async def get_active_order_id_for_ip(ip: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT order_id FROM orders
            WHERE client_ip = $1::inet
              AND status = ANY($2::varchar[])
            ORDER BY created_at DESC
            LIMIT 1
            """,
            ip,
            list(ACTIVE_STATUSES),
        )


async def count_recent_orders_by_ip(ip: str, minutes: int = 15) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM orders
            WHERE client_ip = $1::inet
              AND created_at > now() - ($2 || ' minutes')::interval
              AND status NOT IN ('PAID', 'COMPLETED')
            """,
            ip,
            str(minutes),
        )


async def count_recent_orders_by_fingerprint(fingerprint: str, minutes: int = 15) -> int:
    """Сколько заявок создано с этого устройства (fingerprint) за окно — антифрод."""
    if not fingerprint:
        return 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM web_order_ip_log
            WHERE event = 'create_ok'
              AND extra ->> 'fingerprint' = $1
              AND created_at > now() - ($2 || ' minutes')::interval
            """,
            fingerprint,
            str(minutes),
        )


async def enforce_one_active_order_per_ip(
    ip: str | None,
    user_id: int,
    user_agent: str | None = None,
) -> None:
    if not ip:
        raise HTTPException(
            status_code=400,
            detail="Не удалось определить IP. Отключите VPN/прокси или обновите страницу.",
        )

    existing = await get_active_order_id_for_ip(ip)
    if existing:
        await log_ip_event(
            ip=ip,
            event="create_denied_ip_active",
            user_id=user_id,
            user_agent=user_agent,
            extra={"blocked_by_order_id": existing},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_order_exists",
                "order_id": str(existing),
                "message": (
                    f"С вашего IP уже есть активная заявка #{existing}. "
                    "Продолжите оплату по ней или отмените перед созданием новой."
                ),
            },
        )

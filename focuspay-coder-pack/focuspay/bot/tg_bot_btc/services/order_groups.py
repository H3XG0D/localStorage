"""Группы split-заказов и создание следующей части после PAID."""
import json
import logging
from decimal import Decimal

from services.db import get_pool

logger = logging.getLogger("order_groups")


async def create_order_group(
    *,
    user_id: int,
    crypto: str,
    total_fiat: float,
    total_crypto: float,
    rate: float,
    requisites: str,
    sub_token: str,
    parts_count: int,
    parts_fiat: list[int] | None = None,
) -> int:
    meta = json.dumps({"parts_fiat": parts_fiat or []})
    pool = await get_pool()
    async with pool.acquire() as conn:
        gid = await conn.fetchval(
            """
            INSERT INTO order_groups (
                user_id, crypto, direction, total_fiat, total_crypto, rate,
                requisites, sub_token, parts_count, status, wallet_text
            )
            VALUES ($1, $2, 'buy', $3, $4, $5, $6, $7, $8, 'active', $9)
            RETURNING id
            """,
            user_id,
            crypto,
            total_fiat,
            total_crypto,
            rate,
            requisites,
            sub_token,
            parts_count,
            meta,
        )
    return int(gid)


async def get_group(group_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM order_groups WHERE id = $1", group_id)


async def part_crypto_amount(group: dict, part_fiat: int) -> float:
    total_fiat = float(group["total_fiat"])
    total_crypto = float(group["total_crypto"])
    if total_fiat <= 0:
        return 0.0
    return float(Decimal(str(total_crypto)) * Decimal(part_fiat) / Decimal(str(total_fiat)))


async def on_part_paid(order_id: str) -> dict | None:
    """После PAID части: обновить группу, вернуть данные для создания следующей части или None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id = $1", order_id
        )
        if not order or not order.get("group_id"):
            return None
        gid = int(order["group_id"])
        group = await conn.fetchrow(
            "SELECT * FROM order_groups WHERE id = $1 FOR UPDATE", gid
        )
        if not group or group["status"] != "active":
            return None

        paid_count = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM orders
            WHERE group_id = $1 AND status IN ('PAID', 'COMPLETED')
            """,
            gid,
        )
        await conn.execute(
            "UPDATE order_groups SET parts_paid = $1, updated_at = now() WHERE id = $2",
            paid_count,
            gid,
        )
        part_index = int(order.get("part_index") or 1)
        parts_count = int(group["parts_count"])
        if paid_count >= parts_count:
            await conn.execute(
                "UPDATE order_groups SET status = 'completed', updated_at = now() WHERE id = $1",
                gid,
            )
            return None

        next_index = part_index + 1
        parts_fiat = _parts_from_group(group)
        if next_index > len(parts_fiat):
            return None
        return {
            "group_id": gid,
            "part_index": next_index,
            "part_fiat": parts_fiat[next_index - 1],
            "group": dict(group),
        }


def _parts_from_group(group: dict) -> list[int]:
    raw = group.get("wallet_text") or ""
    try:
        data = json.loads(raw)
        parts = data.get("parts_fiat") or []
        if parts:
            return [int(p) for p in parts]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return [int(float(group["total_fiat"]))]


async def load_group_part_fiats(group_id: int) -> list[int]:
    group = await get_group(group_id)
    if group:
        parts = _parts_from_group(dict(group))
        if parts:
            return parts
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT fiat_amount FROM orders
            WHERE group_id = $1 ORDER BY part_index ASC NULLS LAST, created_at ASC
            """,
            group_id,
        )
    if rows:
        return [int(float(r["fiat_amount"])) for r in rows]
    return []


async def cancel_order_group(group_id: int) -> None:
    from services.db import update_order_status

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id FROM orders
            WHERE group_id = $1
              AND status IN (
                  'CREATED', 'AWAITING_CHECK', 'PENDING', 'OPERATOR_PENDING'
              )
            """,
            group_id,
        )

    for row in rows:
        try:
            await update_order_status(row["order_id"], "CANCELED")
        except Exception as e:
            logger.warning("cancel group order %s: %s", row["order_id"], e)

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE order_groups SET status = 'canceled', updated_at = now() WHERE id = $1",
            group_id,
        )

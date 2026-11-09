"""Ручная выдача реквизита оператору до создания заявки.

Заявку оператор заводит в панели и указывает там код тикета. До этого момента
выдача живёт только здесь: иначе зарезервированная карта или счёт мерчанта
останутся висеть, а деньги клиента придут «в никуда».
"""
from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger("manual_requisite")

SOURCE_RAIL = "rail"
SOURCE_MERCHANT = "merchant"
SOURCE_REKI_BOT = "reki_bot"
SOURCES = (SOURCE_RAIL, SOURCE_MERCHANT, SOURCE_REKI_BOT)

SOURCE_TITLES = {
    SOURCE_RAIL: "Наши карты",
    SOURCE_MERCHANT: "Мерчант",
    SOURCE_REKI_BOT: "Реки-бот",
}

STATUS_ISSUED = "ISSUED"
STATUS_LINKED = "LINKED"
STATUS_CANCELED = "CANCELED"

TICKET_TTL_MINUTES = 30
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_ticket_code() -> str:
    """MAN-XXXXXX: без похожих символов, чтобы диктовать голосом."""
    tail = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"MAN-{tail}"


def normalize_ticket_code(raw: str | None) -> str | None:
    text = (raw or "").strip().upper().replace(" ", "")
    if not text:
        return None
    if not text.startswith("MAN-"):
        text = f"MAN-{text.lstrip('-')}"
    return text if len(text) == 10 else None


@dataclass(frozen=True)
class ManualTicket:
    code: str
    source: str
    sub_token: str
    amount_rub: Decimal
    bill: dict[str, Any]
    requisite_id: int | None = None
    merchant_order_id: str | None = None
    operator_tg_id: int | None = None
    order_id: str | None = None
    status: str = STATUS_ISSUED

    @property
    def source_title(self) -> str:
        return SOURCE_TITLES.get(self.source, self.source)


def _bill_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _ticket_from_row(row) -> ManualTicket:
    return ManualTicket(
        code=str(row["code"]),
        source=str(row["source"]),
        sub_token=str(row["sub_token"]),
        amount_rub=Decimal(str(row["amount_rub"])),
        bill=_bill_dict(row["bill"]),
        requisite_id=int(row["requisite_id"]) if row["requisite_id"] is not None else None,
        merchant_order_id=row["merchant_order_id"],
        operator_tg_id=int(row["operator_tg_id"]) if row["operator_tg_id"] is not None else None,
        order_id=row["order_id"],
        status=str(row["status"]),
    )


async def save_ticket(
    *,
    code: str,
    source: str,
    sub_token: str,
    amount_rub,
    bill: dict[str, Any] | None = None,
    requisite_id: int | None = None,
    merchant_order_id: str | None = None,
    operator_tg_id: int | None = None,
) -> None:
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO manual_requisite_tickets
                (code, source, sub_token, amount_rub, bill, requisite_id,
                 merchant_order_id, operator_tg_id)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
            """,
            code,
            source,
            sub_token,
            Decimal(str(amount_rub)),
            json.dumps(bill or {}, ensure_ascii=False),
            requisite_id,
            merchant_order_id,
            operator_tg_id,
        )


async def get_ticket(code: str) -> ManualTicket | None:
    from services.db import get_pool

    normalized = normalize_ticket_code(code)
    if not normalized:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM manual_requisite_tickets WHERE code = $1",
            normalized,
        )
    return _ticket_from_row(row) if row else None


async def link_ticket_to_order(code: str, order_id: str) -> ManualTicket | None:
    """Связывает выдачу с заявкой. Повторная привязка к другой заявке запрещена."""
    from services.db import get_pool

    normalized = normalize_ticket_code(code)
    if not normalized:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE manual_requisite_tickets
            SET order_id = $2, status = $3, updated_at = now()
            WHERE code = $1 AND status = $4
            RETURNING *
            """,
            normalized,
            str(order_id),
            STATUS_LINKED,
            STATUS_ISSUED,
        )
    return _ticket_from_row(row) if row else None


async def cancel_ticket(code: str) -> ManualTicket | None:
    from services.db import get_pool

    normalized = normalize_ticket_code(code)
    if not normalized:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE manual_requisite_tickets
            SET status = $2, updated_at = now()
            WHERE code = $1 AND status = $3
            RETURNING *
            """,
            normalized,
            STATUS_CANCELED,
            STATUS_ISSUED,
        )
    return _ticket_from_row(row) if row else None


async def stale_tickets(ttl_minutes: int = TICKET_TTL_MINUTES) -> list[ManualTicket]:
    """Выдачи без заявки старше TTL — их держать нельзя, карта занята зря."""
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM manual_requisite_tickets
            WHERE status = $1
              AND order_id IS NULL
              AND created_at < now() - ($2::int * INTERVAL '1 minute')
            ORDER BY created_at
            """,
            STATUS_ISSUED,
            int(ttl_minutes),
        )
    return [_ticket_from_row(row) for row in rows]

"""Привязка ручной выдачи реквизита к заявке. Журнал пишет бот.

Код MAN-xxxx оператор получает в Telegram до создания заявки; здесь выдача
связывается с orders, чтобы зарезервированная карта не висела и не отменилась.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("manual_requisite_store")

STATUS_ISSUED = "ISSUED"
STATUS_LINKED = "LINKED"

SOURCE_RAIL = "rail"
SOURCE_MERCHANT = "merchant"
SOURCE_REKI_BOT = "reki_bot"


def normalize_ticket_code(raw: str | None) -> str | None:
    text = (raw or "").strip().upper().replace(" ", "")
    if not text:
        return None
    if not text.startswith("MAN-"):
        text = f"MAN-{text.lstrip('-')}"
    return text if len(text) == 10 else None


async def claim_ticket(conn, code: str, order_id: str) -> dict | None:
    """Занимает свободный тикет под заявку. None — кода нет или он уже занят."""
    normalized = normalize_ticket_code(code)
    if not normalized:
        return None
    row = await conn.fetchrow(
        """
        UPDATE manual_requisite_tickets
        SET order_id = $2, status = $3, updated_at = now()
        WHERE code = $1 AND status = $4 AND order_id IS NULL
        RETURNING code, source, sub_token, amount_rub, bill,
                  requisite_id, merchant_order_id
        """,
        normalized,
        str(order_id),
        STATUS_LINKED,
        STATUS_ISSUED,
    )
    return dict(row) if row else None


async def ticket_exists(conn, code: str) -> bool:
    normalized = normalize_ticket_code(code)
    if not normalized:
        return False
    row = await conn.fetchrow(
        "SELECT 1 FROM manual_requisite_tickets WHERE code = $1",
        normalized,
    )
    return row is not None


async def apply_ticket_to_order(conn, ticket: dict, order_id: str) -> None:
    """Переносит выдачу на заявку: карта оператора или счёт мерчанта."""
    source = str(ticket.get("source") or "")
    if source == SOURCE_RAIL and ticket.get("requisite_id") is not None:
        await conn.execute(
            "UPDATE orders SET payin_requisite_id = $2 WHERE order_id = $1",
            str(order_id),
            int(ticket["requisite_id"]),
        )
        await conn.execute(
            """
            UPDATE payout_requisite_allocations
            SET order_id = $2, updated_at = now()
            WHERE order_id = $1 AND kind = 'payin'
            """,
            str(ticket["code"]),
            str(order_id),
        )
    elif source == SOURCE_MERCHANT and ticket.get("merchant_order_id"):
        await conn.execute(
            "UPDATE orders SET merchant_order_id = $2 WHERE order_id = $1",
            str(order_id),
            str(ticket["merchant_order_id"]),
        )
    elif source == SOURCE_REKI_BOT and ticket.get("merchant_order_id"):
        # Чужой UUID остаётся в снимке. Колонка merchant_order_id — для нашего PayFast.
        payfast_id = str(ticket["merchant_order_id"]).strip()
        if not payfast_id:
            return
        await conn.execute(
            """
            UPDATE orders
            SET payment_snapshot = COALESCE(payment_snapshot, '{}'::jsonb) || $2::jsonb
            WHERE order_id = $1
            """,
            str(order_id),
            json.dumps({"reki_payfast_id": payfast_id}),
        )

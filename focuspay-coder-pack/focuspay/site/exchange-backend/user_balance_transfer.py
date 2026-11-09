"""Перевод доступного баланса другому человеку. Комиссия 10% остаётся у проекта."""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

from db import get_pool
from user_cashback_db import get_cashback_balance_conn
from user_unified_balance import _partner_parts, unified_available

MIN_TRANSFER = Decimal("100.00")
FEE_RATE = Decimal("0.10")
_USERNAME = re.compile(r"^[a-z0-9_]{4,32}$")


class TransferError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def quote_transfer(amount_rub: float) -> tuple[Decimal, Decimal, Decimal]:
    try:
        amount = Decimal(str(amount_rub)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise TransferError("amount", "Укажите сумму") from exc
    if amount < MIN_TRANSFER:
        raise TransferError("min", "Минимум 100 ₽")
    fee = (amount * FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net = (amount - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if net <= 0:
        raise TransferError("fee", "Сумма слишком мала после комиссии")
    return amount, fee, net


def parse_recipient(raw: str) -> tuple[str, int | str]:
    text = (raw or "").strip().lstrip("@")
    if not text:
        raise TransferError("recipient", "Укажите @username или Telegram ID")
    if text.isdigit():
        uid = int(text)
        if uid <= 0:
            raise TransferError("recipient", "Укажите @username или Telegram ID")
        return "id", uid
    lowered = text.lower()
    if not _USERNAME.fullmatch(lowered):
        raise TransferError("recipient", "Укажите @username или Telegram ID")
    return "username", lowered


def guard_transfer(
    sender_id: int,
    recipient_id: int | None,
    available: float,
    amount_rub: float,
) -> tuple[Decimal, Decimal, Decimal]:
    amount, fee, net = quote_transfer(amount_rub)
    if recipient_id is None:
        raise TransferError("unknown", "Получатель не найден")
    if int(recipient_id) <= 0:
        raise TransferError("unknown", "Получатель не найден")
    if int(recipient_id) == int(sender_id):
        raise TransferError("self", "Нельзя отправить себе")
    avail = Decimal(str(available)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if avail + Decimal("0.001") < amount:
        raise TransferError("funds", "Недостаточно средств")
    return amount, fee, net


def split_sources(cashback: float, referral: float, partner: float, amount: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Кэшбэк, затем реферальные, затем партнёрские. Сумма частей равна списанию."""
    cb = Decimal(str(max(cashback, 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ref = Decimal(str(max(referral, 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    part = Decimal(str(max(partner, 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if cb + ref + part + Decimal("0.001") < amount:
        raise TransferError("funds", "Недостаточно средств")
    from_cb = min(cb, amount)
    remainder = amount - from_cb
    from_ref = min(ref, remainder)
    from_partner = (remainder - from_ref).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if from_partner < 0 or from_partner > part + Decimal("0.001"):
        raise TransferError("funds", "Недостаточно средств")
    return from_cb, from_ref, from_partner


def recipient_label(row: dict) -> str:
    username = str(row.get("username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"
    name = str(row.get("first_name") or "").strip()
    if name:
        return name
    return str(row.get("user_id"))


async def _find_recipient(conn, raw: str) -> dict | None:
    kind, value = parse_recipient(raw)
    if kind == "id":
        row = await conn.fetchrow(
            "SELECT user_id, username, first_name FROM bot_users WHERE user_id = $1",
            int(value),
        )
        if row:
            return dict(row)
        row = await conn.fetchrow(
            """
            SELECT telegram_user_id AS user_id, username, display_name AS first_name
            FROM web_users WHERE telegram_user_id = $1
            """,
            int(value),
        )
        return dict(row) if row else None
    row = await conn.fetchrow(
        "SELECT user_id, username, first_name FROM bot_users WHERE LOWER(username) = $1",
        value,
    )
    if row:
        return dict(row)
    row = await conn.fetchrow(
        """
        SELECT telegram_user_id AS user_id, username, display_name AS first_name
        FROM web_users
        WHERE telegram_user_id IS NOT NULL AND LOWER(username) = $1
        """,
        value,
    )
    return dict(row) if row else None


async def _debit(conn, sender_id: int, amount: Decimal, transfer_id: int) -> None:
    cashback = await get_cashback_balance_conn(conn, sender_id)
    referral = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM user_referral_ledger WHERE referrer_user_id = $1
        """,
        sender_id,
    )
    partner = await _partner_parts(conn, sender_id)
    from_cb, from_ref, from_partner = split_sources(
        float(cashback),
        float(referral or 0),
        float(partner.get("available_rub") or 0),
        amount,
    )
    note = f"Перевод #{transfer_id}"
    if from_cb > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
            VALUES ($1, 'adjustment', $2, $3)
            """,
            sender_id,
            -from_cb,
            note,
        )
    if from_ref > 0:
        await conn.execute(
            """
            INSERT INTO user_referral_ledger (referrer_user_id, type, amount_rub, note)
            VALUES ($1, 'payout', $2, $3)
            """,
            sender_id,
            -from_ref,
            note,
        )
    if from_partner > 0:
        campaign_id = partner.get("campaign_id")
        if not campaign_id:
            raise TransferError("funds", "Недостаточно средств")
        await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", int(campaign_id))
        await conn.execute(
            """
            INSERT INTO partner_ledger (campaign_id, type, amount_rub, note)
            VALUES ($1, 'payout', $2, $3)
            """,
            int(campaign_id),
            -from_partner,
            note,
        )


async def transfer_balance(sender_id: int, recipient_raw: str, amount_rub: float) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            recipient = await _find_recipient(conn, recipient_raw)
            recipient_id = int(recipient["user_id"]) if recipient else None
            available = await unified_available(conn, sender_id) if recipient_id else 0
            amount, fee, net = guard_transfer(sender_id, recipient_id, available, amount_rub)
            assert recipient is not None and recipient_id is not None
            for uid in sorted((int(sender_id), recipient_id)):
                await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", uid)
            available = await unified_available(conn, sender_id)
            amount, fee, net = guard_transfer(sender_id, recipient_id, available, amount_rub)
            row = await conn.fetchrow(
                """
                INSERT INTO user_balance_transfers (
                    sender_user_id, recipient_user_id, amount_rub, fee_rub, net_rub
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                int(sender_id),
                recipient_id,
                amount,
                fee,
                net,
            )
            transfer_id = int(row["id"])
            await _debit(conn, int(sender_id), amount, transfer_id)
            await conn.execute(
                """
                INSERT INTO user_cashback_ledger (user_id, type, amount_rub, note)
                VALUES ($1, 'adjustment', $2, $3)
                """,
                recipient_id,
                net,
                f"Перевод от {sender_id} #{transfer_id}",
            )
    return {
        "id": transfer_id,
        "recipient_label": recipient_label(recipient),
        "amount_rub": float(amount),
        "fee_rub": float(fee),
        "net_rub": float(net),
    }

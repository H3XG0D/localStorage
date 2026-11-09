"""Обработка апдейтов общего бота внештатников."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from db import get_pool
from exchanger_bot_api import TelegramApiError, download_file, get_file, send_message, telegram_call
from exchanger_ops_requisite import fetch_operator, handle_operator_callback, handle_operator_message
from exchanger_bot_commands import (
    is_balance_command,
    is_paid_command,
    is_reki_command,
    is_who_command,
    parse_add_command,
    parse_kick_command,
    parse_requisite_command,
)
from exchanger_bot_config import fetch_config_row
from external_deal_payin import (
    attach_receipt_for_deal,
    confirm_deal_paid,
    create_cabinet_deal_with_payin,
    list_active_deals,
)
from payin_bill_display import format_client_payment_text
from external_exchange_payout import payout_balance_info
from receipt_public_url import build_receipt_public_url
from reki_snapshot import describe_fit, fit_reki, format_snapshot
from reki_store import load_reki_snapshot
from receipt_validation import MAX_RECEIPT_PDF_BYTES, is_valid_pdf_bytes

logger = logging.getLogger("exchanger_bot_handlers")
RECEIPTS_DIR = Path(os.getenv("RECEIPTS_DIR", "/opt/tg_bot_btc/receipts"))
HELP_TEXT = (
    "Реквизит: «сбп 5400» или «карта 12000».\n"
    "Дальше «оплатил» и PDF-чек.\n"
    "«баланс» — сколько на магазине.\n"
    "/reki — какие суммы сейчас свободны.\n"
    "Хозяин: /add 14114102312130 Вася · /kick 14114102312130 · /who"
)
DENIED_TEXT = "доступ не выдан"


async def _handle_callback(callback: dict[str, Any]) -> None:
    data = str(callback.get("data") or "")
    if not data.startswith("opq:"):
        return
    from_user = callback.get("from") or {}
    tg_id = from_user.get("id")
    if not tg_id:
        return
    cfg = await fetch_config_row()
    token = (cfg or {}).get("token")
    if not token:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        operator = await fetch_operator(conn, int(tg_id))
    notice = "доступ не выдан"
    if operator:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        try:
            notice = await handle_operator_callback(
                token,
                operator,
                data,
                chat_id=chat.get("id"),
                message_id=message.get("message_id"),
            )
        except Exception:
            logger.exception("operator callback failed tg_id=%s", tg_id)
            notice = "Не получилось обработать."
    query_id = callback.get("id")
    if query_id:
        try:
            await telegram_call(
                token,
                "answerCallbackQuery",
                json_payload={"callback_query_id": query_id, "text": notice[:180]},
            )
        except Exception:
            logger.debug("answerCallbackQuery failed", exc_info=True)


async def handle_telegram_update(update: dict[str, Any]) -> None:
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        await _handle_callback(callback)
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    if chat.get("type") and chat.get("type") != "private":
        return
    from_user = message.get("from") or {}
    tg_id = from_user.get("id")
    if not tg_id:
        return
    cfg = await fetch_config_row()
    token = (cfg or {}).get("token")
    if not token:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        member = await conn.fetchrow(
            """
            SELECT m.*, e.name AS exchanger_name, e.is_active AS exchanger_is_active
            FROM exchanger_bot_members m
            JOIN external_exchangers e ON e.id = m.exchanger_id
            WHERE m.telegram_user_id = $1
            """,
            int(tg_id),
        )
        if member and member.get("is_active"):
            await conn.execute(
                "UPDATE exchanger_bot_members SET last_seen_at = now() WHERE id = $1",
                member["id"],
            )
    if not member or not member.get("is_active") or not member.get("exchanger_is_active"):
        async with pool.acquire() as conn:
            operator = await fetch_operator(conn, int(tg_id))
        if operator:
            try:
                await handle_operator_message(token, operator, message)
            except Exception:
                logger.exception("operator requisite handler failed tg_id=%s", tg_id)
                await _safe_send(token, int(tg_id), "Не получилось обработать. Попробуйте ещё раз.")
            return
        await _safe_send(token, int(tg_id), DENIED_TEXT)
        return
    try:
        await _dispatch(token, dict(member), message)
    except Exception:
        logger.exception("exchanger bot handler failed tg_id=%s", tg_id)
        await _safe_send(token, int(tg_id), "Не получилось обработать. Попробуйте ещё раз.")


async def _dispatch(token: str, member: dict[str, Any], message: dict[str, Any]) -> None:
    tg_id = int(member["telegram_user_id"])
    text = (message.get("text") or message.get("caption") or "").strip()
    document = message.get("document")
    if document:
        await _handle_document(token, member, document)
        return
    if not text:
        await send_message(token, tg_id, HELP_TEXT)
        return
    cmd = text.split("@", 1)[0].split()[0].lower() if text.startswith("/") else ""
    if cmd in ("/start", "/help"):
        await send_message(token, tg_id, HELP_TEXT)
        return
    if is_balance_command(text):
        await _handle_balance(token, member)
        return
    if is_who_command(text):
        await _handle_who(token, member)
        return
    if is_reki_command(text):
        await _handle_reki(token, member)
        return
    added = parse_add_command(text)
    if added:
        await _handle_add(token, member, added[0], added[1])
        return
    kicked = parse_kick_command(text)
    if kicked:
        await _handle_kick(token, member, kicked)
        return
    req = parse_requisite_command(text)
    if req:
        await _handle_requisite(token, member, req["amount_rub"], req["sub_token"])
        return
    if is_paid_command(text):
        await _handle_paid(token, member)
        return
    await send_message(token, tg_id, HELP_TEXT)


async def _handle_balance(token: str, member: dict[str, Any]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        info = await payout_balance_info(conn, int(member["exchanger_id"]))
    await send_message(
        token,
        int(member["telegram_user_id"]),
        f"Баланс: ${float(info['balance_usd']):,.2f}\n"
        f"Доступно: ${float(info['available_usd']):,.2f}".replace(",", " "),
    )


async def _handle_who(token: str, member: dict[str, Any]) -> None:
    if member.get("role") != "owner":
        await send_message(token, int(member["telegram_user_id"]), "Только хозяин магазина.")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT telegram_user_id, role, label, is_active
            FROM exchanger_bot_members
            WHERE exchanger_id = $1
            ORDER BY (role = 'owner') DESC, id
            """,
            int(member["exchanger_id"]),
        )
    lines = [f"{member.get('exchanger_name') or 'Магазин'}:"]
    for row in rows:
        mark = "владелец" if row["role"] == "owner" else "сотрудник"
        off = "" if row["is_active"] else " (выкл)"
        label = f" {row['label']}" if row["label"] else ""
        lines.append(f"{row['telegram_user_id']} — {mark}{label}{off}")
    await send_message(token, int(member["telegram_user_id"]), "\n".join(lines))


async def _handle_add(token: str, member: dict[str, Any], new_id: int, label: str | None) -> None:
    if member.get("role") != "owner":
        await send_message(token, int(member["telegram_user_id"]), "Только хозяин магазина.")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, exchanger_id FROM exchanger_bot_members WHERE telegram_user_id = $1",
            new_id,
        )
        if existing and int(existing["exchanger_id"]) != int(member["exchanger_id"]):
            await send_message(token, int(member["telegram_user_id"]), "Этот id уже привязан к другому магазину.")
            return
        if existing:
            await conn.execute(
                """
                UPDATE exchanger_bot_members
                SET is_active = TRUE, label = COALESCE($2, label)
                WHERE telegram_user_id = $1
                """,
                new_id,
                label,
            )
        else:
            await conn.execute(
                """
                INSERT INTO exchanger_bot_members (
                    telegram_user_id, exchanger_id, role, label, invited_by
                ) VALUES ($1, $2, 'clerk', $3, $4)
                """,
                new_id,
                int(member["exchanger_id"]),
                label,
                int(member["telegram_user_id"]),
            )
    await send_message(token, int(member["telegram_user_id"]), f"Добавлен {new_id}")


async def _handle_kick(token: str, member: dict[str, Any], target_id: int) -> None:
    if member.get("role") != "owner":
        await send_message(token, int(member["telegram_user_id"]), "Только хозяин магазина.")
        return
    if target_id == int(member["telegram_user_id"]):
        await send_message(token, int(member["telegram_user_id"]), "Себя убрать нельзя.")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, role FROM exchanger_bot_members
            WHERE telegram_user_id = $1 AND exchanger_id = $2
            """,
            target_id,
            int(member["exchanger_id"]),
        )
        if not row:
            await send_message(token, int(member["telegram_user_id"]), "Такого id в магазине нет.")
            return
        if row["role"] == "owner":
            await send_message(token, int(member["telegram_user_id"]), "Хозяина убрать нельзя.")
            return
        await conn.execute(
            "UPDATE exchanger_bot_members SET is_active = FALSE WHERE id = $1",
            row["id"],
        )
    await send_message(token, int(member["telegram_user_id"]), f"Отключён {target_id}")


def _payment_text(deal: dict[str, Any]) -> str:
    ready = str(deal.get("payment_text") or "").strip()
    if ready:
        return ready
    payment = deal.get("payment") or {}
    amount = payment.get("fiat_amount") or deal.get("client_pays_rub") or 0
    return format_client_payment_text(
        amount_rub=amount,
        sub_token=deal.get("sub_token"),
        bill=(payment.get("bill") if isinstance(payment, dict) else None),
        deal_id=deal.get("id"),
    )


async def _handle_reki(token: str, member: dict[str, Any]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        snapshot = await load_reki_snapshot(conn)
    await send_message(
        token,
        int(member["telegram_user_id"]),
        format_snapshot(snapshot),
        parse_mode="HTML",
    )


async def _reki_hint(amount_rub: float, sub_token: str) -> str | None:
    """Подсказка, если запрошенная сумма не попадает ни в один свободный коридор."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            snapshot = await load_reki_snapshot(conn)
    except Exception:
        logger.warning("reki hint skipped", exc_info=True)
        return None
    return describe_fit(fit_reki(snapshot, sub_token, amount_rub))


async def _handle_requisite(token: str, member: dict[str, Any], amount_rub: float, sub_token: str) -> None:
    tg_id = int(member["telegram_user_id"])
    exchanger_id = int(member["exchanger_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            deal = await create_cabinet_deal_with_payin(
                conn,
                exchanger_id=exchanger_id,
                amount_rub=amount_rub,
                crypto="usdt",
                sub_token=sub_token,
                note=None,
                created_by=f"tg:{tg_id}",
                client_is_new=True,
            )
        except HTTPException as exc:
            hint = await _reki_hint(amount_rub, sub_token)
            detail = str(exc.detail)
            await send_message(token, tg_id, f"{detail}\n\n{hint}" if hint else detail)
            return
        deal_id = int(deal["id"])
        await conn.execute(
            "UPDATE external_deals SET created_by_tg_id = $1 WHERE id = $2",
            tg_id,
            deal_id,
        )
    await send_message(token, tg_id, _payment_text(deal))


async def _latest_awaiting(conn, exchanger_id: int):
    rows = await list_active_deals(conn, exchanger_id)
    for row in rows:
        if str(row.get("status")) == "awaiting_receipt":
            return row
    return rows[0] if rows else None


async def _handle_paid(token: str, member: dict[str, Any]) -> None:
    tg_id = int(member["telegram_user_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        deal = await _latest_awaiting(conn, int(member["exchanger_id"]))
        if not deal:
            await send_message(token, tg_id, "Нет активной сделки.")
            return
        try:
            await confirm_deal_paid(conn, int(deal["id"]), int(member["exchanger_id"]))
        except HTTPException as exc:
            await send_message(token, tg_id, str(exc.detail))
            return
    await send_message(token, tg_id, "Оплата отмечена. Пришлите PDF-чек.")


async def _handle_document(token: str, member: dict[str, Any], document: dict[str, Any]) -> None:
    tg_id = int(member["telegram_user_id"])
    mime = (document.get("mime_type") or "").lower()
    name = (document.get("file_name") or "").lower()
    if "pdf" not in mime and not name.endswith(".pdf"):
        await send_message(token, tg_id, "Нужен PDF-чек.")
        return
    file_id = document.get("file_id")
    if not file_id:
        await send_message(token, tg_id, "Не удалось получить файл.")
        return
    info = await get_file(token, str(file_id))
    path = info.get("file_path")
    if not path:
        await send_message(token, tg_id, "Не удалось скачать файл.")
        return
    content = await download_file(token, str(path))
    if len(content) > MAX_RECEIPT_PDF_BYTES or not is_valid_pdf_bytes(content):
        await send_message(token, tg_id, "Это не PDF или файл слишком большой.")
        return
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_name = f"{uuid.uuid4().hex}.pdf"
    (RECEIPTS_DIR / receipt_name).write_bytes(content)
    receipt_url = build_receipt_public_url(receipt_name)
    pool = await get_pool()
    async with pool.acquire() as conn:
        deal = await _latest_awaiting(conn, int(member["exchanger_id"]))
        if not deal:
            await send_message(token, tg_id, "Нет сделки для чека. Сначала «сбп 5400», потом «оплатил».")
            return
        if not deal.get("paid_confirmed_at"):
            try:
                await confirm_deal_paid(conn, int(deal["id"]), int(member["exchanger_id"]))
            except HTTPException:
                pass
        try:
            await attach_receipt_for_deal(
                conn,
                int(deal["id"]),
                int(member["exchanger_id"]),
                receipt_url,
                receipt_name,
            )
        except HTTPException as exc:
            await send_message(token, tg_id, str(exc.detail))
            return
    await send_message(token, tg_id, "Чек отправлен на проверку.")


async def notify_deal_credited(deal: dict[str, Any]) -> None:
    tg_id = deal.get("created_by_tg_id")
    if not tg_id:
        return
    cfg = await fetch_config_row()
    token = (cfg or {}).get("token")
    if not token:
        return
    usd = float(deal.get("principal_usdt") or deal.get("total_credit_usdt") or 0)
    rub = float(deal.get("amount_rub") or deal.get("client_pays_rub") or 0)
    text = f"На баланс зачислено ${usd:,.2f}".replace(",", " ")
    if rub:
        text += f" / {rub:,.0f} ₽".replace(",", " ")
    await _safe_send(token, int(tg_id), text)


async def _safe_send(token: str, chat_id: int, text: str) -> None:
    try:
        await send_message(token, chat_id, text)
    except TelegramApiError as exc:
        logger.warning("exchanger bot send failed chat=%s: %s", chat_id, exc)

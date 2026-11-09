"""Реквизит для оператора в боте внештатников, без external_deals.

Оператор — строка operator_accounts с telegram_user_id. Команда «сбп 5400»
выдаёт реквизит и код MAN-…, заявку он заводит в /ops/create.
"""
from __future__ import annotations

import html
import json
import logging
import os
import secrets
from decimal import Decimal
from typing import Any

import aiohttp

from db import get_pool
from exchanger_bot_api import edit_message, send_message
from exchanger_bot_commands import is_reki_command, parse_requisite_command
from reki_snapshot import SUB_TOKEN_CARD, format_snapshot
from reki_store import load_reki_snapshot

logger = logging.getLogger("exchanger_ops_requisite")

SOURCE_RAIL = "rail"
SOURCE_MERCHANT = "merchant"
SOURCE_REKI_BOT = "reki_bot"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

OPERATOR_HELP = (
    "Реквизит под нашу заявку, без внештатной сделки.\n"
    "«сбп 5400» или «карта 12000» — реквизит у реки-бота и код.\n"
    "/reki — какие суммы сейчас свободны.\n"
    "Код MAN-… укажите в /ops/create, иначе через 30 минут выдача отменится."
)
_CANCEL_PREFIX = "opq:x:"
_SEARCHING_TEXT = "🔎 Ищу реквизит…"


def new_ticket_code() -> str:
    tail = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"MAN-{tail}"


def cancel_keyboard(code: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [[{"text": "❌ Отменить", "callback_data": f"{_CANCEL_PREFIX}{code}"}]]
    }


def parse_cancel_callback(data: str) -> str | None:
    if not (data or "").startswith(_CANCEL_PREFIX):
        return None
    code = data[len(_CANCEL_PREFIX):].strip().upper()
    if len(code) == 10 and code.startswith("MAN-"):
        return code
    return None


async def fetch_operator(conn, telegram_user_id: int) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id, username, display_name, telegram_user_id
        FROM operator_accounts
        WHERE telegram_user_id = $1 AND is_active = TRUE
        """,
        int(telegram_user_id),
    )
    return dict(row) if row else None


def _format_issued(code: str, source: str, sub_token: str, amount_rub, bill: dict) -> str:
    """Та же карточка, что у Focus-бота. Источник в текст не пишем."""
    del source
    method = "Карта" if (sub_token or "").upper() == SUB_TOKEN_CARD else "СБП"
    quote = int(round(float(amount_rub or 0)))
    amount = f"{quote:,}".replace(",", " ")
    icon = "💳" if method == "Карта" else "📱"
    lines = [
        f"✅ <b>Реквизит · {method}</b>",
        "",
        "⚠️ <b>Не оплачивайте с МТС Банка и Уралсиба</b> — такие переводы не принимаем.",
    ]
    payfast_id = str(bill.get("payfast_id") or "").strip()
    if payfast_id:
        lines.append(f"🆔 Payfast: <code>{html.escape(payfast_id)}</code>")
    lines.extend(
        [
            "",
            f"💰 Сумма: <b>{amount}</b> ₽",
            f"{icon} Реквизит: <code>{html.escape(str(bill.get('reciver') or '—'))}</code>",
        ]
    )
    if bill.get("bank"):
        lines.append(f"🏦 Банк: {html.escape(str(bill['bank']))}")
    if bill.get("fio"):
        lines.append(f"👤 Получатель: {html.escape(str(bill['fio']))}")
    lines.append(f"🔀 Способ: {method}")
    lines.extend(["", "⚠️ Переводите <b>точную сумму</b>, одним платежом."])
    if method == "СБП":
        lines.append("🏦 По СБП — только на указанный банк.")
    lines.extend(
        [
            "⏱ Чек в течение <b>22.5 минут</b>, лучше PDF.",
            "🎥 Если попросят видео и его не будет — заявку закроют.",
            "",
            f"🔖 Код для заявки: <code>{html.escape(code)}</code>",
            "Укажите его в /ops/create. Если не указать, выдача снимется через 30 минут.",
        ]
    )
    return "\n".join(lines)


def _format_canceled(code: str) -> str:
    return (
        "❌ <b>Заявка отменена</b>\n\n"
        f"Код <code>{html.escape(code)}</code> больше не действует."
    )


def _bill_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _save_ticket(
    conn,
    *,
    code: str,
    source: str,
    sub_token: str,
    amount_rub,
    bill: dict,
    requisite_id: int | None,
    merchant_order_id: str | None,
    operator_tg_id: int,
) -> None:
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
        int(operator_tg_id),
    )


async def _issue_rail(conn, *, amount_rub, sub_token: str, operator_tg_id: int) -> tuple[bool, str]:
    from payin_requisite_rail import bill_from_requisite, reserve_payin_slot

    code = new_ticket_code()
    async with conn.transaction():
        reserved = await reserve_payin_slot(
            conn,
            order_id=code,
            amount_rub=amount_rub,
            sub_token=sub_token,
            accept_round_up=True,
        )
        if reserved is None:
            return False, "Свободных карт на эту сумму нет."
        candidate, fit = reserved
        bill = bill_from_requisite(
            {
                "bank": candidate.bank,
                "requisites": candidate.requisites,
                "holder_name": candidate.holder_name,
            }
        )
        await _save_ticket(
            conn,
            code=code,
            source=SOURCE_RAIL,
            sub_token=sub_token,
            amount_rub=fit.pay_rub,
            bill=bill,
            requisite_id=candidate.id,
            merchant_order_id=None,
            operator_tg_id=operator_tg_id,
        )
    return True, _format_issued(code, SOURCE_RAIL, sub_token, fit.pay_rub, bill)


async def _issue_merchant(*, amount_rub, sub_token: str, operator_tg_id: int) -> tuple[bool, str]:
    from merchant_client import cancel_payin, create_payin_order
    from payin_discovery import discover_payin_plan
    from payin_resolver import extract_merchant_uuid, get_bill_from_response

    quote = int(round(float(amount_rub)))
    discovery = await discover_payin_plan(
        fiat_amount=quote,
        sub_token=sub_token,
        user_id=int(operator_tg_id),
        create_payin_fn=create_payin_order,
        cancel_payin_fn=cancel_payin,
        client_transaction_id=f"MANPROBE-{secrets.token_hex(4)}",
    )
    bill = get_bill_from_response(discovery.probe_response or {})
    if discovery.plan.mode == "reject" or not bill:
        return False, discovery.plan.message or "Мерчант не выдал реквизит на эту сумму."
    code = new_ticket_code()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _save_ticket(
            conn,
            code=code,
            source=SOURCE_MERCHANT,
            sub_token=discovery.plan.resolved_sub_token or sub_token,
            amount_rub=quote,
            bill=bill,
            requisite_id=None,
            merchant_order_id=extract_merchant_uuid(discovery.probe_response),
            operator_tg_id=operator_tg_id,
        )
    return True, _format_issued(code, SOURCE_MERCHANT, sub_token, quote, bill)


async def _issue_reki_bot(
    *,
    amount_rub,
    sub_token: str,
    operator_tg_id: int,
) -> tuple[bool, str, str | None]:
    base = (os.environ.get("BOT_WEBHOOK_URL") or "http://127.0.0.1:8081").rstrip("/")
    token = (
        os.environ.get("INTERNAL_API_SECRET") or os.environ.get("WEBHOOK_SECRET") or ""
    ).strip()
    if not token:
        return False, "Сессия реки-бота не настроена.", None
    url = f"{base}/internal/reki-issue"
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={"amount_rub": float(amount_rub), "sub_token": sub_token},
                headers={"X-Internal-Token": token},
            ) as resp:
                body = await resp.json(content_type=None)
    except Exception:
        logger.warning("reki-issue call failed", exc_info=True)
        return False, "Реки-бот не ответил. Напишите сумму ещё раз.", None
    if not isinstance(body, dict) or not body.get("ok"):
        return False, str((body or {}).get("reason") or "Реки-бот не выдал реквизит на эту сумму."), None
    bill = dict(body.get("bill")) if isinstance(body.get("bill"), dict) else {}
    payfast_id = str(body.get("payfast_id") or bill.get("payfast_id") or "").strip() or None
    if payfast_id:
        bill["payfast_id"] = payfast_id
    code = new_ticket_code()
    quote = int(round(float(amount_rub)))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _save_ticket(
            conn,
            code=code,
            source=SOURCE_REKI_BOT,
            sub_token=sub_token,
            amount_rub=quote,
            bill=bill,
            requisite_id=None,
            merchant_order_id=payfast_id,
            operator_tg_id=operator_tg_id,
        )
    return True, _format_issued(code, SOURCE_REKI_BOT, sub_token, quote, bill), code


async def issue_for_operator(
    *,
    source: str,
    amount_rub,
    sub_token: str,
    operator_tg_id: int,
) -> tuple[bool, str]:
    try:
        if source == SOURCE_RAIL:
            pool = await get_pool()
            async with pool.acquire() as conn:
                return await _issue_rail(
                    conn,
                    amount_rub=amount_rub,
                    sub_token=sub_token,
                    operator_tg_id=operator_tg_id,
                )
        if source == SOURCE_MERCHANT:
            return await _issue_merchant(
                amount_rub=amount_rub,
                sub_token=sub_token,
                operator_tg_id=operator_tg_id,
            )
        if source == SOURCE_REKI_BOT:
            ok, text, _code = await _issue_reki_bot(
                amount_rub=amount_rub,
                sub_token=sub_token,
                operator_tg_id=operator_tg_id,
            )
            return ok, text
    except Exception:
        logger.warning("operator requisite issue failed source=%s", source, exc_info=True)
        return False, "Не удалось выдать реквизит. Попробуйте другой источник."
    return False, "Неизвестный источник реквизита."


async def handle_operator_message(token: str, operator: dict, message: dict[str, Any]) -> None:
    tg_id = int(operator["telegram_user_id"])
    text = (message.get("text") or "").strip()
    cmd = text.split("@", 1)[0].split()[0].lower() if text.startswith("/") else ""
    if not text or cmd in ("/start", "/help"):
        await send_message(token, tg_id, OPERATOR_HELP)
        return
    if is_reki_command(text):
        pool = await get_pool()
        async with pool.acquire() as conn:
            snapshot = await load_reki_snapshot(conn)
        await send_message(token, tg_id, format_snapshot(snapshot), parse_mode="HTML")
        return
    parsed = parse_requisite_command(text)
    if not parsed:
        await send_message(token, tg_id, OPERATOR_HELP)
        return
    wait = await send_message(token, tg_id, _SEARCHING_TEXT)
    ok, card, code = await _issue_reki_bot(
        amount_rub=float(parsed["amount_rub"]),
        sub_token=str(parsed["sub_token"]),
        operator_tg_id=tg_id,
    )
    wait_id = ((wait or {}).get("result") or {}).get("message_id")
    markup = cancel_keyboard(code) if ok and code else None
    if wait_id:
        try:
            await edit_message(
                token,
                tg_id,
                int(wait_id),
                card,
                parse_mode="HTML" if ok else None,
                reply_markup=markup,
            )
            return
        except Exception:
            logger.warning("requisite card edit failed tg=%s", tg_id, exc_info=True)
    await send_message(
        token,
        tg_id,
        card,
        parse_mode="HTML" if ok else None,
        reply_markup=markup,
    )


async def _load_operator_ticket(code: str, operator_tg_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT code, source, status, bill
            FROM manual_requisite_tickets
            WHERE code = $1 AND operator_tg_id = $2
            """,
            code,
            int(operator_tg_id),
        )
    return dict(row) if row else None


async def _mark_ticket_canceled(code: str, operator_tg_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE manual_requisite_tickets
            SET status = 'CANCELED', updated_at = now()
            WHERE code = $1 AND status = 'ISSUED' AND operator_tg_id = $2
            RETURNING code
            """,
            code,
            int(operator_tg_id),
        )
    return row is not None


async def _cancel_reki_remote(message_id: int) -> tuple[bool, str]:
    base = (os.environ.get("BOT_WEBHOOK_URL") or "http://127.0.0.1:8081").rstrip("/")
    token = (
        os.environ.get("INTERNAL_API_SECRET") or os.environ.get("WEBHOOK_SECRET") or ""
    ).strip()
    if not token:
        return False, "Не удалось отменить заявку у реки-бота."
    url = f"{base}/internal/reki-cancel"
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={"message_id": int(message_id)},
                headers={"X-Internal-Token": token},
            ) as resp:
                body = await resp.json(content_type=None)
    except Exception:
        logger.warning("reki-cancel call failed", exc_info=True)
        return False, "Не удалось отменить заявку у реки-бота."
    if not isinstance(body, dict) or not body.get("ok"):
        return False, str((body or {}).get("reason") or "Не удалось отменить заявку у реки-бота.")
    return True, "Заявка отменена"


async def handle_operator_callback(
    token: str,
    operator: dict,
    data: str,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> str:
    code = parse_cancel_callback(data)
    if not code:
        return "Напишите сумму заново, например «сбп 5400»."
    operator_tg_id = int(operator["telegram_user_id"])
    ticket = await _load_operator_ticket(code, operator_tg_id)
    if not ticket or str(ticket.get("status")) != "ISSUED" or ticket.get("source") != SOURCE_REKI_BOT:
        return "Эта выдача уже закрыта."
    bill = _bill_dict(ticket.get("bill"))
    try:
        reki_message_id = int(bill.get("reki_message_id"))
    except (TypeError, ValueError):
        return "Не удалось отменить заявку у реки-бота."
    if reki_message_id <= 0:
        return "Не удалось отменить заявку у реки-бота."
    ok, notice = await _cancel_reki_remote(reki_message_id)
    if not ok:
        return notice
    await _mark_ticket_canceled(code, operator_tg_id)
    if chat_id and message_id:
        try:
            await edit_message(
                token,
                int(chat_id),
                int(message_id),
                _format_canceled(code),
                parse_mode="HTML",
                reply_markup={"inline_keyboard": []},
            )
        except Exception:
            logger.warning("cancel edit failed code=%s", code, exc_info=True)
    return "Заявка отменена"

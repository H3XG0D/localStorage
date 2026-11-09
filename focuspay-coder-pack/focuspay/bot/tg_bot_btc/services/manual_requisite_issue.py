"""Ручная выдача реквизита оператору.

Новые выдачи берутся только у реки-бота. Карта пула и счёт мерчанта остаются
для старых тикетов: их ещё нужно отпускать, если заявка так и не появилась.
Выдача ничего не создаёт в orders: оператор заводит заявку в панели и указывает
там код тикета.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from services.manual_requisite import (
    SOURCE_MERCHANT,
    SOURCE_RAIL,
    SOURCE_REKI_BOT,
    new_ticket_code,
    save_ticket,
)
from services.reki_snapshot import SUB_TOKEN_CARD

logger = logging.getLogger("manual_requisite_issue")


@dataclass(frozen=True)
class IssueResult:
    """ok=False — показать reason оператору, тикет при этом не создан."""

    ok: bool
    code: str | None = None
    source: str | None = None
    bill: dict[str, Any] | None = None
    pay_rub: Decimal | None = None
    reason: str | None = None


def _failed(reason: str) -> IssueResult:
    return IssueResult(ok=False, reason=reason)


async def issue_from_rail(
    *,
    amount_rub,
    sub_token: str,
    operator_tg_id: int | None = None,
) -> IssueResult:
    """Резервирует карту оператора под код тикета вместо order_id."""
    from services.db import get_pool
    from services.payin_requisite_rail import bill_from_requisite, reserve_payin_slot

    code = new_ticket_code()
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                reserved = await reserve_payin_slot(
                    conn,
                    order_id=code,
                    amount_rub=amount_rub,
                    sub_token=sub_token,
                    accept_round_up=True,
                )
    except Exception:
        logger.warning("manual rail reserve failed amount=%s", amount_rub, exc_info=True)
        return _failed("Не удалось зарезервировать карту. Попробуйте другой источник.")

    if reserved is None:
        return _failed("Свободных карт на эту сумму нет.")

    candidate, fit = reserved
    bill = bill_from_requisite(
        {
            "bank": candidate.bank,
            "requisites": candidate.requisites,
            "holder_name": candidate.holder_name,
        }
    )
    await save_ticket(
        code=code,
        source=SOURCE_RAIL,
        sub_token=sub_token,
        amount_rub=fit.pay_rub,
        bill=bill,
        requisite_id=candidate.id,
        operator_tg_id=operator_tg_id,
    )
    return IssueResult(ok=True, code=code, source=SOURCE_RAIL, bill=bill, pay_rub=fit.pay_rub)


async def issue_from_merchant(
    *,
    amount_rub,
    sub_token: str,
    operator_tg_id: int | None = None,
) -> IssueResult:
    """Берёт счёт у мерчанта тем же probe, что и обычная покупка."""
    from handlers.exchange_flow import (
        cancel_order_merchant,
        create_payin_order,
        generate_local_order_id,
    )
    from services.config_rates import load_config
    from services.payin_discovery import discover_payin_plan
    from services.payin_resolver import extract_merchant_uuid, get_bill_from_response

    cfg = load_config()
    callback_url = (cfg.MERCHANT.get("callback_url") or "").strip()
    quote = int(round(float(amount_rub)))

    async def _create(**kwargs):
        kwargs.setdefault("callback_url", callback_url)
        return await create_payin_order(**kwargs)

    try:
        discovery = await discover_payin_plan(
            fiat_amount=quote,
            sub_token=sub_token,
            user_id=int(operator_tg_id or 0),
            create_payin_fn=_create,
            cancel_payin_fn=cancel_order_merchant,
            generate_order_id_fn=generate_local_order_id,
        )
    except Exception:
        logger.warning("manual merchant probe failed amount=%s", quote, exc_info=True)
        return _failed("Мерчант не ответил. Попробуйте другой источник.")

    bill = get_bill_from_response(discovery.probe_response or {})
    if discovery.plan.mode == "reject" or not bill:
        return _failed(discovery.plan.message or "Мерчант не выдал реквизит на эту сумму.")

    code = new_ticket_code()
    await save_ticket(
        code=code,
        source=SOURCE_MERCHANT,
        sub_token=discovery.plan.resolved_sub_token or sub_token,
        amount_rub=quote,
        bill=bill,
        merchant_order_id=extract_merchant_uuid(discovery.probe_response),
        operator_tg_id=operator_tg_id,
    )
    return IssueResult(
        ok=True,
        code=code,
        source=SOURCE_MERCHANT,
        bill=bill,
        pay_rub=Decimal(quote),
    )


async def issue_from_reki_bot(
    *,
    amount_rub,
    sub_token: str,
    operator_tg_id: int | None = None,
) -> IssueResult:
    """Просит реквизит у стороннего бота той же командой, что внештатники."""
    from services.reki_request import request_ready, request_requisite

    if not request_ready():
        return _failed("Сессия реки-бота не настроена.")

    try:
        issued = await request_requisite(amount_rub, sub_token)
    except Exception:
        logger.warning("manual reki request failed amount=%s", amount_rub, exc_info=True)
        return _failed("Реки-бот не ответил. Напишите сумму ещё раз.")

    if issued is None:
        return _failed("Реки-бот не выдал реквизит на эту сумму.")

    bill = {
        "bank": issued.bank or "",
        "reciver": issued.requisite,
        "fio": issued.holder or "",
    }
    message_id = getattr(issued, "message_id", None)
    if isinstance(message_id, int) and message_id > 0:
        bill["reki_message_id"] = message_id
    raw_payfast = getattr(issued, "payfast_id", None)
    payfast_id = raw_payfast.strip() if isinstance(raw_payfast, str) else ""
    payfast_id = payfast_id or None
    if payfast_id:
        bill["payfast_id"] = payfast_id
    code = new_ticket_code()
    quote = int(round(float(amount_rub)))
    await save_ticket(
        code=code,
        source=SOURCE_REKI_BOT,
        sub_token=sub_token,
        amount_rub=quote,
        bill=bill,
        merchant_order_id=payfast_id,
        operator_tg_id=operator_tg_id,
    )
    return IssueResult(
        ok=True,
        code=code,
        source=SOURCE_REKI_BOT,
        bill=bill,
        pay_rub=Decimal(quote),
    )


ISSUERS = {
    SOURCE_RAIL: issue_from_rail,
    SOURCE_MERCHANT: issue_from_merchant,
    SOURCE_REKI_BOT: issue_from_reki_bot,
}


async def issue_requisite(
    source: str,
    *,
    amount_rub,
    sub_token: str,
    operator_tg_id: int | None = None,
) -> IssueResult:
    issuer = ISSUERS.get(source)
    if issuer is None:
        return _failed("Неизвестный источник реквизита.")
    return await issuer(
        amount_rub=amount_rub,
        sub_token=sub_token,
        operator_tg_id=operator_tg_id,
    )


def _reki_message_id(ticket) -> int | None:
    raw = (getattr(ticket, "bill", None) or {}).get("reki_message_id")
    try:
        message_id = int(raw)
    except (TypeError, ValueError):
        return None
    return message_id if message_id > 0 else None


async def release_requisite(ticket) -> None:
    """Возвращает карту в пул, гасит счёт мерчанта или жмёт отмену у реки.

    Ошибка клика по реки не останавливает локальную чистку: у реки своя отмена.
    """
    if ticket.source == SOURCE_REKI_BOT:
        message_id = _reki_message_id(ticket)
        if not message_id:
            return
        try:
            from services.reki_request import cancel_reki_message

            await cancel_reki_message(message_id)
        except Exception:
            logger.warning("reki cleanup click failed code=%s", ticket.code, exc_info=True)
        return

    if ticket.source == SOURCE_RAIL:
        from services.db import get_pool
        from services.payin_requisite_rail import release_payin_allocation

        pool = await get_pool()
        async with pool.acquire() as conn:
            await release_payin_allocation(conn, ticket.code)
        return

    if ticket.source == SOURCE_MERCHANT and ticket.merchant_order_id:
        from handlers.exchange_flow import cancel_order_merchant

        await cancel_order_merchant(ticket.merchant_order_id)


CLEANUP_INTERVAL_SEC = 120


async def cleanup_stale_tickets_once() -> int:
    """Отменяет выдачи без заявки старше TTL. Возвращает число отменённых."""
    from services.manual_requisite import cancel_ticket, stale_tickets

    canceled = 0
    for ticket in await stale_tickets():
        try:
            await release_requisite(ticket)
        except Exception:
            logger.warning("manual ticket release failed code=%s", ticket.code, exc_info=True)
        closed = await cancel_ticket(ticket.code)
        if closed is not None:
            canceled += 1
            logger.info(
                "manual ticket canceled code=%s source=%s age_ttl=%s",
                ticket.code,
                ticket.source,
                True,
            )
    return canceled


async def manual_requisite_cleanup_task(*, shutdown_event=None) -> None:
    """Фоновая чистка: карта/мерчант не должны висеть без заявки."""
    import asyncio

    while shutdown_event is None or not shutdown_event.is_set():
        try:
            n = await cleanup_stale_tickets_once()
            if n:
                logger.info("manual ticket cleanup: canceled %s", n)
        except Exception:
            logger.warning("manual ticket cleanup failed", exc_info=True)
        if shutdown_event is None:
            await asyncio.sleep(CLEANUP_INTERVAL_SEC)
            continue
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CLEANUP_INTERVAL_SEC)
        except asyncio.TimeoutError:
            continue


def format_issued(ticket_code: str, source: str, sub_token: str, amount_rub, bill: dict) -> str:
    """Карточка выдачи. Источник в текст не пишем: новые выдачи только у реки."""
    del source
    import html

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
            f"🔖 Код для заявки: <code>{html.escape(ticket_code)}</code>",
            "Укажите его в /ops/create. Если не указать, выдача снимется через 30 минут.",
        ]
    )
    return "\n".join(lines)


def format_canceled(ticket_code: str) -> str:
    import html

    return (
        "❌ <b>Заявка отменена</b>\n\n"
        f"Код <code>{html.escape(ticket_code)}</code> больше не действует."
    )


async def cancel_issued_reki(ticket) -> tuple[bool, str]:
    """Жмёт отмену у реки и закрывает тикет. Неуспешный клик тикет не трогает."""
    from services.manual_requisite import STATUS_ISSUED, cancel_ticket

    if ticket is None or ticket.status != STATUS_ISSUED:
        return False, "Эта выдача уже закрыта."
    if ticket.source != SOURCE_REKI_BOT:
        return False, "Эту выдачу отсюда не отменить."
    message_id = _reki_message_id(ticket)
    if not message_id:
        return False, "Не удалось отменить заявку у реки-бота."
    try:
        from services.reki_request import cancel_reki_message

        clicked = await cancel_reki_message(message_id)
    except Exception:
        logger.warning("reki cancel failed code=%s", ticket.code, exc_info=True)
        clicked = False
    if not clicked:
        return False, "Не удалось отменить заявку у реки-бота."
    await cancel_ticket(ticket.code)
    return True, "Заявка отменена"

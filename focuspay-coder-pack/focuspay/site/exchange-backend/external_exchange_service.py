"""Общая логика создания внештатной сделки (без HTTP-зависимостей).

Используется из admin_external.py и operator_external.py.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from config import settings
from external_exchange_calc import build_markup_formula, calc_deal, normalize_markup_mode, preview_deal

logger = logging.getLogger("external_exchange_service")


def resolve_exchanger_markup(ex: dict) -> dict[str, float | str]:
    """Наценка клиенту: per-exchanger или глобальная."""
    raw_pct = ex.get("markup_pct")
    pct = float(raw_pct) if raw_pct is not None else float(settings.ext_markup_pct)
    raw_mode = ex.get("markup_mode")
    mode = normalize_markup_mode(
        str(raw_mode) if raw_mode else settings.ext_markup_mode
    )
    return {"markup_pct": pct, "markup_mode": mode}


def resolve_exchanger_markup_pct(ex: dict) -> float:
    return float(resolve_exchanger_markup(ex)["markup_pct"])


def _row(r) -> dict:
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


async def get_exchanger_active(conn, exchanger_id: int) -> dict | None:
    """Вернуть активного внештатника или None."""
    row = await conn.fetchrow(
        "SELECT * FROM external_exchangers WHERE id = $1 AND is_active = TRUE",
        exchanger_id,
    )
    return _row(row) if row else None


async def _credit_ledger(
    conn,
    *,
    exchanger_id: int,
    deal_id: int,
    principal_usdt: float,
) -> None:
    """Записать principal в external_ledger (вызывается внутри транзакции)."""
    await conn.execute(
        """
        INSERT INTO external_ledger (exchanger_id, type, amount_usd, deal_id, note)
        VALUES ($1, 'principal', $2, $3, 'Сделка: основная сумма')
        ON CONFLICT (deal_id) WHERE type = 'principal' AND deal_id IS NOT NULL
        DO NOTHING
        """,
        exchanger_id,
        principal_usdt,
        deal_id,
    )


async def create_external_deal(
    conn,
    *,
    exchanger_id: int,
    amount_rub: float,
    crypto: str,
    note: str | None,
    created_by: str,
    usdt_rate_rub: float | None = None,
    pending: bool = False,
    operator_id: int | None = None,
    operator_percent: float = 0.0,
    markup_pct: float | None = None,
    markup_mode: str | None = None,
    client_is_new: bool = True,
    payout_on_credit: bool = False,
    payout_wallet: str | None = None,
) -> dict[str, Any]:
    """Создать сделку.

    amount_rub — ввод внештатника (база или оборот — по markup_mode).

    pending=False (admin): статус 'confirmed', леджер кредитуется сразу.
    pending=True (operator): статус 'awaiting_receipt', леджер НЕ кредитуется — только после confirm.

    Возвращает dict сделки с полями total_credit_usdt и exchanger_name.
    Raises ValueError при невалидных данных.
    Raises RuntimeError если курс недоступен.
    """
    ex = await get_exchanger_active(conn, exchanger_id)
    if ex is None:
        raise ValueError("Внештатник не найден или неактивен")

    if usdt_rate_rub is None:
        from routers.public import get_exchanger_rates_cached

        rates = await get_exchanger_rates_cached()
        usdt_rate_rub = float(rates.get("usdt") or 0)

    if usdt_rate_rub <= 0:
        raise RuntimeError("Курс USDT/RUB недоступен. Попробуйте позже.")

    markup = resolve_exchanger_markup(ex)
    effective_markup = float(markup_pct) if markup_pct is not None else float(markup["markup_pct"])
    effective_mode = normalize_markup_mode(
        markup_mode if markup_mode is not None else str(markup["markup_mode"])
    )

    calc = calc_deal(
        amount_rub,
        usdt_rate_rub,
        markup_pct=effective_markup,
        markup_mode=effective_mode,
        card_fee_pct=settings.ext_card_fee_pct,
        receive_fee_usd=settings.ext_receive_fee_usd,
        operator_percent=operator_percent,
    )

    deal_status = "awaiting_receipt" if pending else "confirmed"
    wallet_clean = (payout_wallet or "").strip() or None
    want_payout = bool(payout_on_credit) and bool(wallet_clean)

    async with conn.transaction():
        deal_row = await conn.fetchrow(
            """
            INSERT INTO external_deals (
                exchanger_id, amount_rub, crypto,
                markup_pct, markup_mode, card_fee_pct, usdt_rate_rub,
                client_pays_rub, payfast_fee_rub, net_profit_rub,
                principal_usdt, reward_usdt,
                receive_fee_usd, house_profit_usd,
                operator_id, operator_earnings_rub,
                note, created_by, status, client_is_new,
                payout_on_credit, payout_wallet
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
            RETURNING *
            """,
            exchanger_id,
            calc.amount_rub,
            crypto,
            calc.markup_pct,
            calc.markup_mode,
            calc.card_fee_pct,
            calc.usdt_rate_rub,
            calc.client_pays_rub,
            calc.payfast_fee_rub,
            calc.net_profit_rub,
            calc.principal_usdt,
            calc.reward_usdt,
            calc.receive_fee_usd,
            calc.house_profit_usd,
            operator_id,
            calc.operator_earnings_rub,
            note,
            created_by,
            deal_status,
            bool(client_is_new),
            want_payout,
            wallet_clean if want_payout else None,
        )
        deal_id = int(deal_row["id"])

        if not pending:
            await _credit_ledger(
                conn,
                exchanger_id=exchanger_id,
                deal_id=deal_id,
                principal_usdt=calc.principal_usdt,
            )
            if operator_id and calc.operator_earnings_rub > 0:
                from operator_payroll_pool import accrue_external_deal

                await accrue_external_deal(
                    conn,
                    deal_id=deal_id,
                    operator_id=operator_id,
                    earnings_rub=calc.operator_earnings_rub,
                )
            else:
                from external_deal_shift_payroll import accrue_shift_external_deal

                await accrue_shift_external_deal(
                    conn,
                    deal_id=deal_id,
                    net_profit_rub=calc.net_profit_rub,
                )

    result = _row(deal_row)
    result["total_credit_usdt"] = calc.total_credit_usdt
    result["exchanger_name"] = ex["name"]
    result["markup_pct"] = effective_markup
    result["markup_mode"] = effective_mode
    result["input_rub"] = calc.input_rub
    return result


async def confirm_external_deal(
    conn,
    deal_id: int,
    confirmed_by: str,
) -> dict[str, Any]:
    """Подтвердить сделку: обновить статус → 'confirmed', записать в леджер.

    Raises ValueError если сделка не найдена или статус не допускает confirm.
    """
    already_confirmed = False
    principal_usdt = 0.0
    ex_row = None
    async with conn.transaction():
        deal_row = await conn.fetchrow(
            "SELECT * FROM external_deals WHERE id = $1 FOR UPDATE",
            deal_id,
        )
        if not deal_row:
            raise ValueError("Сделка не найдена")
        status = str(deal_row["status"])
        ex_row = await conn.fetchrow(
            "SELECT * FROM external_exchangers WHERE id = $1",
            int(deal_row["exchanger_id"]),
        )
        if status == "confirmed":
            already_confirmed = True
        else:
            has_merchant = bool(deal_row.get("merchant_order_id") or deal_row.get("payment_snapshot"))
            if status == "pending":
                pass
            elif status == "awaiting_receipt" and not has_merchant:
                pass
            else:
                raise ValueError(
                    f"Сделка в статусе '{status}' — подтверждение невозможно"
                )
            if not ex_row:
                raise ValueError("Внештатник не найден")

            await conn.execute(
                "UPDATE external_deals SET status = 'confirmed' WHERE id = $1",
                deal_id,
            )

            principal_usdt = float(deal_row["principal_usdt"])
            await _credit_ledger(
                conn,
                exchanger_id=int(deal_row["exchanger_id"]),
                deal_id=deal_id,
                principal_usdt=principal_usdt,
            )

            operator_id = deal_row.get("operator_id")
            earnings_rub = float(deal_row.get("operator_earnings_rub") or 0)
            if operator_id and earnings_rub > 0:
                from operator_payroll_pool import accrue_external_deal

                await accrue_external_deal(
                    conn,
                    deal_id=deal_id,
                    operator_id=int(operator_id),
                    earnings_rub=earnings_rub,
                )
            else:
                from external_deal_shift_payroll import accrue_shift_external_deal

                await accrue_shift_external_deal(
                    conn,
                    deal_id=deal_id,
                    net_profit_rub=float(deal_row["net_profit_rub"] or 0),
                )

    principal_usdt = float(deal_row["principal_usdt"])
    result = _row(deal_row)
    result["status"] = "confirmed"
    result["total_credit_usdt"] = principal_usdt
    result["exchanger_name"] = ex_row["name"] if ex_row else ""
    result["confirmed_by"] = confirmed_by
    if already_confirmed:
        result["already_confirmed"] = True
    else:
        try:
            from exchanger_bot_handlers import notify_deal_credited

            await notify_deal_credited({**result, "created_by_tg_id": deal_row.get("created_by_tg_id")})
        except Exception:
            logger.exception("exchanger bot credit notify failed deal=%s", deal_id)
        try:
            from exchanger_deal_callback import schedule_exchanger_deal_callback

            schedule_exchanger_deal_callback({**result, "callback_url": deal_row.get("callback_url")}, "credited")
        except Exception:
            logger.exception("exchanger credited callback failed deal=%s", deal_id)

    try:
        from external_exchange_payout import maybe_create_payout_on_credit

        payout_info = await maybe_create_payout_on_credit(
            conn,
            deal_row,
            confirmed_by=confirmed_by,
            exchanger_name=str(result.get("exchanger_name") or ""),
        )
        result.update(payout_info)
        if payout_info.get("payout_id"):
            result["payout_id"] = payout_info["payout_id"]
    except Exception:
        logger.exception("auto payout on credit failed deal=%s", deal_id)
        result["credit_payout_status"] = "skipped_error"
        result["credit_payout_detail"] = "не удалось создать заявку на вывод"
    return result


async def cancel_external_deal(conn, deal_id: int) -> dict[str, Any]:
    """Отменить сделку (awaiting_receipt, до отправки чека в мерчант)."""
    row = await conn.fetchrow(
        "SELECT * FROM external_deals WHERE id = $1",
        deal_id,
    )
    if not row:
        raise ValueError("Сделка не найдена")
    if row["status"] != "awaiting_receipt":
        raise ValueError(
            f"Сделка в статусе '{row['status']}' — отмена невозможна"
        )
    if row.get("receipt_submitted_at"):
        raise ValueError("Чек уже отправлен — отмена невозможна")
    await conn.execute(
        "UPDATE external_deals SET status = 'cancelled' WHERE id = $1",
        deal_id,
    )
    result = _row(row)
    result["status"] = "cancelled"
    try:
        from exchanger_deal_callback import schedule_exchanger_deal_callback

        schedule_exchanger_deal_callback(result, "cancelled")
    except Exception:
        logger.exception("exchanger cancelled callback failed deal=%s", deal_id)
    return result


async def search_exchangers(conn, q: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Поиск активных внештатников по имени или контакту."""
    term = q.strip()
    if not term:
        return []
    rows = await conn.fetch(
        """
        SELECT id, name, contact, net_percent, note
        FROM external_exchangers
        WHERE is_active = TRUE
          AND (name ILIKE $1 OR contact ILIKE $1)
        ORDER BY name
        LIMIT $2
        """,
        f"%{term}%",
        limit,
    )
    return [dict(r) for r in rows]

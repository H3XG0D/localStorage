"""Заявки на вывод баланса внештатника."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from config import settings
from external_exchange_calc import calc_payout_with_crypto, preview_payout

# Комиссия вывода по монете (USD). Не путать с наценкой сделки.
WITHDRAW_FEE_USD: dict[str, float] = {
    "usdt": 3.0,
    "btc": 2.0,
    "ltc": 2.0,
    "trx": 2.0,
}


def withdraw_fee_usd(crypto: str | None = None) -> float:
    c = (crypto or "usdt").split("_")[0].lower().strip()
    if c in WITHDRAW_FEE_USD:
        return WITHDRAW_FEE_USD[c]
    return float(settings.ext_withdraw_fee_usd)


def withdraw_fees_map() -> dict[str, float]:
    return dict(WITHDRAW_FEE_USD)


def min_payout_gross_usd(crypto: str | None = None) -> float:
    """Минимальная сумма списания: чуть больше комиссии выбранной монеты."""
    return round(withdraw_fee_usd(crypto) + 0.01, 2)


def _row(r) -> dict:
    d = dict(r)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


async def ledger_balance_usd(conn, exchanger_id: int) -> float:
    val = await conn.fetchval(
        "SELECT COALESCE(SUM(amount_usd), 0) FROM external_ledger WHERE exchanger_id = $1",
        exchanger_id,
    )
    return round(float(val or 0), 6)


async def pending_payout_gross_usd(conn, exchanger_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(gross_usd), 0)
        FROM external_payouts
        WHERE exchanger_id = $1 AND status = 'pending'
        """,
        exchanger_id,
    )
    return round(float(val or 0), 6)


async def has_pending_payout(conn, exchanger_id: int) -> bool:
    val = await conn.fetchval(
        """
        SELECT 1 FROM external_payouts
        WHERE exchanger_id = $1 AND status = 'pending'
        LIMIT 1
        """,
        exchanger_id,
    )
    return bool(val)


async def available_balance_usd(conn, exchanger_id: int) -> float:
    balance = await ledger_balance_usd(conn, exchanger_id)
    pending = await pending_payout_gross_usd(conn, exchanger_id)
    return round(max(0.0, balance - pending), 6)


async def payout_balance_info(conn, exchanger_id: int) -> dict[str, Any]:
    balance = await ledger_balance_usd(conn, exchanger_id)
    pending = await pending_payout_gross_usd(conn, exchanger_id)
    available = round(max(0.0, balance - pending), 6)
    return {
        "balance_usd": balance,
        "available_usd": available,
        "pending_payout_gross_usd": pending,
        "has_pending_payout": pending > 0,
        "payout_threshold_usd": min_payout_gross_usd("usdt"),
        "withdraw_fee_usd": withdraw_fee_usd("usdt"),
        "withdraw_fees": withdraw_fees_map(),
    }


async def preview_exchanger_payout(
    conn,
    exchanger_id: int,
    gross_usd: float,
    crypto: str,
    market_rub: dict[str, float],
) -> dict[str, Any]:
    info = await payout_balance_info(conn, exchanger_id)
    available = float(info["available_usd"])
    fee_usd = withdraw_fee_usd(crypto)
    min_gross = min_payout_gross_usd(crypto)

    if available <= fee_usd:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств: комиссия ${fee_usd:.2f}, минимум к выводу ${min_gross:.2f}",
        )
    if gross_usd > available + 0.000001:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств: доступно ${available:.2f}, запрошено ${gross_usd:.2f}",
        )

    preview = preview_payout(
        gross_usd,
        crypto,
        market_rub,
        fee_usd=fee_usd,
        payout_threshold_usd=min_gross,
    )
    if not preview:
        raise HTTPException(status_code=400, detail="Не удалось рассчитать вывод")
    return {
        **info,
        **preview,
        "withdraw_fee_usd": fee_usd,
        "payout_threshold_usd": min_gross,
    }


async def create_payout_request(
    conn,
    exchanger_id: int,
    *,
    gross_usd: float,
    crypto: str,
    wallet: str,
    market_rub: dict[str, float],
    created_by: str,
    deal_id: int | None = None,
) -> dict[str, Any]:
    if await has_pending_payout(conn, exchanger_id):
        raise HTTPException(status_code=409, detail="Заявка на вывод уже в обработке")

    preview = await preview_exchanger_payout(
        conn, exchanger_id, gross_usd, crypto, market_rub
    )
    wallet_clean = wallet.strip()
    if len(wallet_clean) < 8:
        raise HTTPException(status_code=400, detail="Укажите корректный адрес кошелька")

    note = f"Кошелёк: {wallet_clean}"
    if deal_id:
        note = f"{note}\nСделка #{int(deal_id)}"

    async with conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO external_payouts (
                exchanger_id, gross_usd, fee_usd, net_usd,
                crypto, crypto_amount, crypto_rate_usd,
                tx_hash, status, note, created_by
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,NULL,'pending',$8,$9)
            RETURNING *
            """,
            exchanger_id,
            preview["gross_usd"],
            preview["fee_usd"],
            preview["net_usd"],
            crypto,
            preview["crypto_amount"],
            preview["crypto_rate_usd"],
            note,
            created_by,
        )
    return _row(row)


async def create_rub_payout_and_push_doliv(
    conn,
    exchanger_id: int,
    *,
    amount_rub: float,
    pay_method: str,
    requisites: dict,
    created_by: str,
) -> dict[str, Any]:
    """Зафиксировать RUB-вывод внештатника и отправить PayoutJob в Doliv (если bridge включён)."""
    del conn
    import doliv_bridge

    job = await doliv_bridge.create_payout_job(
        amount_rub=amount_rub,
        pay_method=pay_method if pay_method in ("sbp", "c2c") else "sbp",
        requisites=requisites,
        source="freelancer",
        external_ref=f"ext-{exchanger_id}-{created_by}",
    )
    return {
        "exchanger_id": exchanger_id,
        "amount_rub": amount_rub,
        "doliv_job": job,
        "bridge_enabled": doliv_bridge.bridge_enabled(),
    }


async def list_exchanger_payouts(
    conn,
    exchanger_id: int,
    *,
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[dict], int]:
    rows = await conn.fetch(
        """
        SELECT * FROM external_payouts
        WHERE exchanger_id = $1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        exchanger_id,
        limit,
        offset,
    )
    total = int(
        await conn.fetchval(
            "SELECT COUNT(*) FROM external_payouts WHERE exchanger_id = $1",
            exchanger_id,
        )
        or 0
    )
    return [_row(r) for r in rows], total


async def update_pending_payout_fee(
    conn,
    payout_id: int,
    *,
    fee_usd: float,
    market_rub: dict[str, float],
    updated_by: str,
) -> dict[str, Any]:
    """Пересчитать комиссию/на руки/крипту у pending-заявки на вывод."""
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM external_payouts WHERE id = $1 FOR UPDATE",
            payout_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if str(row["status"]) != "pending":
            raise HTTPException(status_code=400, detail="Заявка уже обработана")

        gross = float(row["gross_usd"])
        crypto = str(row["crypto"] or "usdt")
        try:
            pc = calc_payout_with_crypto(
                gross,
                fee_usd=float(fee_usd),
                crypto=crypto,
                market_rub=market_rub,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        old_fee = float(row["fee_usd"] or 0)
        note = str(row["note"] or "")
        by = (updated_by or "admin").strip() or "admin"
        fee_note = f"[fee ${old_fee:.2f}→${pc.fee_usd:.2f} by {by}]"
        if fee_note not in note:
            note = f"{note} {fee_note}".strip() if note else fee_note

        updated = await conn.fetchrow(
            """
            UPDATE external_payouts
            SET fee_usd = $2,
                net_usd = $3,
                crypto_amount = $4,
                crypto_rate_usd = $5,
                note = $6
            WHERE id = $1
            RETURNING *
            """,
            payout_id,
            pc.fee_usd,
            pc.net_usd,
            pc.crypto_amount,
            pc.crypto_rate_usd,
            note,
        )
    return _row(updated)


async def complete_pending_payout(
    conn,
    payout_id: int,
    *,
    tx_hash: str | None,
    completed_by: str,
    fee_usd: float | None = None,
    market_rub: dict[str, float] | None = None,
) -> dict[str, Any]:
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM external_payouts WHERE id = $1 FOR UPDATE",
            payout_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if str(row["status"]) != "pending":
            raise HTTPException(status_code=400, detail="Заявка уже обработана")

        exchanger_id = int(row["exchanger_id"])
        gross = float(row["gross_usd"])
        balance = await ledger_balance_usd(conn, exchanger_id)
        if gross > balance + 0.000001:
            raise HTTPException(
                status_code=400,
                detail=f"Недостаточно баланса для выплаты: ${balance:.2f}",
            )

        fee = float(row["fee_usd"] or 0)
        net = float(row["net_usd"] or 0)
        crypto_amount = row["crypto_amount"]
        crypto_rate_usd = row["crypto_rate_usd"]
        if fee_usd is not None:
            if not market_rub:
                raise HTTPException(status_code=503, detail="Курс недоступен")
            try:
                pc = calc_payout_with_crypto(
                    gross,
                    fee_usd=float(fee_usd),
                    crypto=str(row["crypto"] or "usdt"),
                    market_rub=market_rub,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            fee = pc.fee_usd
            net = pc.net_usd
            crypto_amount = pc.crypto_amount
            crypto_rate_usd = pc.crypto_rate_usd

        updated = await conn.fetchrow(
            """
            UPDATE external_payouts
            SET status = 'paid',
                tx_hash = COALESCE($2, tx_hash),
                fee_usd = $3,
                net_usd = $4,
                crypto_amount = $5,
                crypto_rate_usd = $6
            WHERE id = $1
            RETURNING *
            """,
            payout_id,
            (tx_hash or "").strip() or None,
            fee,
            net,
            crypto_amount,
            crypto_rate_usd,
        )

        await conn.execute(
            """
            INSERT INTO external_ledger (exchanger_id, type, amount_usd, payout_id, note)
            VALUES ($1, 'payout', $2, $3, $4)
            """,
            exchanger_id,
            -abs(gross),
            payout_id,
            f"Вывод: ${net:.2f} на руки, комиссия ${fee:.2f} · {completed_by}",
        )

    return _row(updated)


def _deal_get(deal, key: str, default=None):
    if isinstance(deal, dict):
        return deal.get(key, default)
    getter = getattr(deal, "get", None)
    if callable(getter):
        return getter(key, default)
    try:
        return deal[key]
    except (KeyError, TypeError, IndexError):
        return default


async def _market_rates() -> dict[str, float]:
    from routers.public import get_exchanger_rates_cached

    return await get_exchanger_rates_cached()


async def maybe_create_payout_on_credit(
    conn,
    deal,
    *,
    confirmed_by: str,
    exchanger_name: str | None = None,
) -> dict[str, Any]:
    """После зачисления: заявка на вывод, если внештатник выбрал «сразу в крипте».

    Кредит уже должен быть в леджере. Ошибки не откатывают сделку —
    сумма остаётся на балансе, оператору уходит причина.
    """
    if not bool(_deal_get(deal, "payout_on_credit")):
        return {"credit_payout_status": "skipped_no_intent"}

    existing = _deal_get(deal, "payout_id")
    if existing:
        return {
            "credit_payout_status": "skipped_already",
            "payout_id": int(existing),
        }

    wallet = str(_deal_get(deal, "payout_wallet") or "").strip()
    if len(wallet) < 8:
        detail = "не указан кошелёк"
        await _notify_credit_payout_skipped(deal, detail)
        return {"credit_payout_status": "skipped_no_wallet", "credit_payout_detail": detail}

    crypto = str(_deal_get(deal, "crypto") or "usdt").lower().strip()
    if crypto not in WITHDRAW_FEE_USD:
        crypto = "usdt"
    gross = float(_deal_get(deal, "principal_usdt") or 0)
    fee = withdraw_fee_usd(crypto)
    deal_id = int(_deal_get(deal, "id") or 0)
    exchanger_id = int(_deal_get(deal, "exchanger_id") or 0)

    if gross <= fee:
        detail = f"зачисление ${gross:.2f} не покрывает комиссию ${fee:.2f}"
        await _notify_credit_payout_skipped(deal, detail)
        return {"credit_payout_status": "skipped_too_small", "credit_payout_detail": detail}

    if await has_pending_payout(conn, exchanger_id):
        detail = "уже есть заявка на вывод в обработке"
        await _notify_credit_payout_skipped(deal, detail)
        return {"credit_payout_status": "skipped_pending", "credit_payout_detail": detail}

    try:
        rates = await _market_rates()
    except Exception:
        rates = {}
    if float(rates.get("usdt") or 0) <= 0:
        detail = "курс недоступен"
        await _notify_credit_payout_skipped(deal, detail)
        return {"credit_payout_status": "skipped_no_rate", "credit_payout_detail": detail}

    created_by = (confirmed_by or "").strip() or str(_deal_get(deal, "created_by") or "deal")
    try:
        payout = await create_payout_request(
            conn,
            exchanger_id,
            gross_usd=gross,
            crypto=crypto,
            wallet=wallet,
            market_rub=rates,
            created_by=created_by,
            deal_id=deal_id,
        )
    except HTTPException as exc:
        detail = str(exc.detail) if exc.detail else "ошибка заявки"
        await _notify_credit_payout_skipped(deal, detail)
        return {
            "credit_payout_status": "skipped_error",
            "credit_payout_detail": detail,
        }

    payout_id = int(payout["id"])
    await conn.execute(
        "UPDATE external_deals SET payout_id = $1 WHERE id = $2",
        payout_id,
        deal_id,
    )

    username = str(_deal_get(deal, "created_by") or "")
    if username.startswith("ex:"):
        username = username[3:]
    await _notify_credit_payout_created(
        payout,
        deal=deal,
        exchanger_name=exchanger_name,
        username=username,
        market_rub=rates,
        conn=conn,
    )
    return {
        "credit_payout_status": "created",
        "payout_id": payout_id,
        "credit_payout": payout,
    }


async def _notify_credit_payout_skipped(deal, detail: str) -> None:
    try:
        from external_payout_notify import notify_ops_external_deals

        deal_id = int(_deal_get(deal, "id") or 0)
        crypto = str(_deal_get(deal, "crypto") or "usdt").upper()
        await notify_ops_external_deals(
            f"⚠️ Кабинет · сделка #{deal_id} · автовывод {crypto} не создан\n"
            f"{detail}. Сумма осталась на балансе."
        )
    except Exception:
        return


async def _notify_credit_payout_created(
    payout: dict,
    *,
    deal,
    exchanger_name: str | None,
    username: str | None,
    market_rub: dict[str, float],
    conn,
) -> None:
    import html

    from external_payout_notify import (
        notify_admin_external_payout_requested,
        notify_ops_external_deals,
    )

    deal_id = int(_deal_get(deal, "id") or 0)
    crypto = str(payout.get("crypto") or "usdt").upper()
    net = float(payout.get("crypto_amount") or 0)
    fee = float(payout.get("fee_usd") or 0)
    name = html.escape(str(exchanger_name or ""))
    try:
        await notify_ops_external_deals(
            f"💸 Кабинет · автовывод после сделки #{deal_id} · заявка #{payout['id']} · "
            f"<b>{name}</b> · ${float(payout.get('gross_usd') or 0):,.2f} → {net:.6f} {crypto} "
            f"(комиссия ${fee:.0f})"
        )
        msg_id = await notify_admin_external_payout_requested(
            payout,
            exchanger_name=exchanger_name,
            username=username,
            market_rub=market_rub,
        )
    except Exception:
        return
    if msg_id:
        await conn.execute(
            "UPDATE external_payouts SET admin_message_id = $1 WHERE id = $2",
            int(msg_id),
            int(payout["id"]),
        )
        payout["admin_message_id"] = int(msg_id)

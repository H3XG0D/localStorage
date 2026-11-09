"""Подтверждение выплаты крипты по BUY-заявке (COMPLETED → PAID) с tx hash."""
from __future__ import annotations

from services.https_fetch import https_read_json_async

import asyncio
import html
import logging
import re
from typing import Any

logger = logging.getLogger("buy_payout")

MIN_TX_HASH_LEN = 8
_TX_RE = re.compile(r"^[a-fA-F0-9]{8,128}$|^[a-zA-Z0-9]{8,128}$")


def normalize_tx_hash(raw: str) -> str | None:
    t = (raw or "").strip()
    if t.startswith("http"):
        t = t.rstrip("/").split("/")[-1]
    t = t.split("?")[0]
    if len(t) < MIN_TX_HASH_LEN:
        return None
    if not _TX_RE.match(t):
        return None
    return t


def buyer_wallet(order: dict) -> str:
    return (order.get("wallet_address") or order.get("requisites") or "").strip()


def build_explorer_url(crypto: str, tx_hash: str) -> str:
    c = (crypto or "").lower().split("_")[0]
    h = tx_hash.strip()
    if c == "btc":
        return f"https://mempool.space/tx/{h}"
    if c == "ltc":
        return f"https://blockchair.com/litecoin/transaction/{h}"
    if c == "trx":
        return f"https://tronscan.org/#/transaction/{h}"
    if c == "usdt":
        net = (crypto or "").lower()
        if "trc" in net or "trc20" in net:
            return f"https://tronscan.org/#/transaction/{h}"
        if "erc" in net or "erc20" in net:
            return f"https://etherscan.io/tx/{h}"
        if "bep" in net or "bep20" in net:
            return f"https://bscscan.com/tx/{h}"
        return f"https://tronscan.org/#/transaction/{h}"
    return f"https://blockchair.com/search?q={h}"


def format_paid_user_message(
    order: dict,
    explorer_url: str,
    *,
    cashback_applied: float = 0,
    cashback_accrued: float = 0,
    overpay_credit: float = 0,
) -> str:
    oid = html.escape(str(order.get("order_id", "")))
    crypto = html.escape(str(order.get("crypto", "")).upper())
    amount = order.get("crypto_amount")
    wallet = html.escape(buyer_wallet(order))
    url = html.escape(explorer_url)
    amount_s = f"{float(amount):g}" if amount is not None else "—"
    lines = [
        "✅ <b>Выплачено</b>\n",
        f"🆔 Заявка: <code>{oid}</code>",
        f"💎 Сумма: <b>{amount_s}</b> {crypto}",
    ]
    if wallet:
        lines.append(f"📬 Кошелёк: <code>{wallet}</code>")
    applied = max(0.0, float(cashback_applied or 0))
    accrued = max(0.0, float(cashback_accrued or 0))
    overpay = max(0.0, float(overpay_credit or 0))
    if applied > 0:
        lines.append(f"🏷 С баланса списано: <b>{applied:,.2f}</b> ₽".replace(",", " "))
    if accrued > 0 and (order.get("direction") or "").lower() == "buy":
        lines.append(f"🎁 Кешбэк на баланс: <b>+{accrued:,.2f}</b> ₽".replace(",", " "))
    if overpay > 0 and (order.get("direction") or "").lower() == "buy":
        lines.append(f"💰 Дополнительный баланс за переплату: <b>+{overpay:,.2f}</b> ₽".replace(",", " "))
    if explorer_url and explorer_url.strip() not in ("", "#"):
        lines.append("")
        lines.append(f'🔗 <a href="{url}">Открыть транзакцию</a>')
    return "\n".join(lines)


def format_paid_chat_message(
    order: dict,
    explorer_url: str,
    *,
    cashback_applied: float = 0,
    cashback_accrued: float = 0,
    overpay_credit: float = 0,
) -> str:
    """Plain-text копия для Business-чата и web-чата (URL кликабелен без HTML)."""
    oid = str(order.get("order_id", "")).strip()
    crypto = str(order.get("crypto", "")).upper()
    amount = order.get("crypto_amount")
    wallet = buyer_wallet(order)
    amount_s = f"{float(amount):g}" if amount is not None else "—"
    lines = [
        "✅ Выплачено",
        "",
        f"🆔 Заявка: {oid}",
        f"💎 Сумма: {amount_s} {crypto}",
    ]
    if wallet:
        lines.append(f"📬 Кошелёк: {wallet}")
    applied = max(0.0, float(cashback_applied or 0))
    accrued = max(0.0, float(cashback_accrued or 0))
    overpay = max(0.0, float(overpay_credit or 0))
    if applied > 0:
        lines.append(f"🏷 С баланса списано: {applied:,.2f} ₽".replace(",", " "))
    if accrued > 0 and (order.get("direction") or "").lower() == "buy":
        lines.append(f"🎁 Кешбэк на баланс: +{accrued:,.2f} ₽".replace(",", " "))
    if overpay > 0 and (order.get("direction") or "").lower() == "buy":
        lines.append(f"💰 Дополнительный баланс за переплату: +{overpay:,.2f} ₽".replace(",", " "))
    if explorer_url and explorer_url.strip() not in ("", "#"):
        lines.append("")
        lines.append(f"🔗 Открыть транзакцию: {explorer_url.strip()}")
    return "\n".join(lines)


async def order_cashback_notify_info(order: dict) -> dict[str, float]:
    """Суммы кешбэка для финального сообщения (после PAID и начисления)."""
    order_id = str(order.get("order_id") or "").strip()
    if not order_id:
        return {"applied": 0.0, "accrued": 0.0, "overpay_credit": 0.0}
    applied = max(0.0, float(order.get("cashback_applied_rub") or 0))
    accrued = 0.0
    overpay_credit = 0.0
    from services.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT type, amount_rub
            FROM user_cashback_ledger
            WHERE order_id = ANY($1::varchar[])
              AND type = ANY($2::varchar[])
            """,
            [order_id, f"{order_id}:overpay"],
            ["accrual", "overpay_credit"],
        )
    for row in rows:
        if row["type"] == "accrual":
            accrued = max(0.0, float(row["amount_rub"] or 0))
        elif row["type"] == "overpay_credit":
            overpay_credit = max(0.0, float(row["amount_rub"] or 0))
    return {"applied": applied, "accrued": accrued, "overpay_credit": overpay_credit}


async def notify_buyer_paid(order: dict, explorer_url: str, *, bot=None) -> None:
    user_id = order.get("user_id")
    if not user_id:
        return
    cb = await order_cashback_notify_info(order)
    text = format_paid_user_message(
        order,
        explorer_url,
        cashback_applied=float(cb["applied"] or 0),
        cashback_accrued=float(cb["accrued"] or 0),
        overpay_credit=float(cb["overpay_credit"] or 0),
    )
    paid_sent = False
    if bot:
        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            paid_sent = True
        except Exception as e:
            logger.warning("notify buyer paid (bot): %s", e)
    if not paid_sent:
        try:
            import json
            import urllib.request

            from services import config_rates as cfg

            token = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
            if not token:
                logger.error("notify buyer paid: TELEGRAM_BOT_TOKEN not set")
                return
            payload = json.dumps(
                {
                    "chat_id": int(user_id),
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            body = await https_read_json_async(req, timeout=15)
            if not body.get("ok"):
                logger.error("notify buyer paid telegram: %s", body)
                return
        except Exception as e:
            logger.error("notify buyer paid (http): %s", e)
            return

    try:
        from services.marketing_messages import send_post_paid_marketing

        await send_post_paid_marketing(int(user_id), bot=bot)
    except Exception as e:
        logger.warning("post-paid marketing: %s", e)

    try:
        from services.marketing_messages import send_post_paid_focus_lucky

        await send_post_paid_focus_lucky(int(user_id), bot=bot)
    except Exception as e:
        logger.warning("post-paid focus lucky: %s", e)

    try:
        from services.marketing_messages import send_post_paid_review_invite

        await send_post_paid_review_invite(
            int(user_id),
            bot=bot,
            order_id=str(order.get("order_id") or ""),
        )
    except Exception as e:
        logger.warning("post-paid review invite: %s", e)

    try:
        from services.marketing_messages import send_post_paid_focusbet

        await send_post_paid_focusbet(int(user_id), bot=bot)
    except Exception as e:
        logger.warning("post-paid focusbet: %s", e)


async def _run_paid_notifications(order: dict, explorer_url: str, bot=None) -> None:
    try:
        await notify_buyer_paid(order, explorer_url, bot=bot)
    except Exception as e:
        logger.warning("notify buyer paid failed order=%s: %s", order.get("order_id"), e)
    try:
        from services.buyer_payout_notify import deliver_buy_payout_to_client_chat

        await deliver_buy_payout_to_client_chat(order, explorer_url)
    except Exception as e:
        logger.warning(
            "buy payout chat notify failed order=%s: %s",
            order.get("order_id"),
            e,
        )
    try:
        from services.order_ops_notify import notify_ops_order

        await notify_ops_order("paid", order, bot=None)
    except Exception as e:
        logger.warning("ops notify paid: %s", e)


def schedule_paid_notifications(order: dict, explorer_url: str, bot=None) -> None:
    """Не держать HTTP-ответ оператора на Telegram (иначе ~60с и обрыв nginx)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("paid notify skipped — no event loop order=%s", order.get("order_id"))
        return
    loop.create_task(_run_paid_notifications(dict(order), explorer_url, bot=bot))


async def confirm_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
    bot=None,
    force: bool = False,
) -> tuple[bool, str | None, dict | None]:
    """
    COMPLETED → PAID с записью tx hash.
    Returns (ok, error_code, order_dict).
    error_code: already_paid | not_found | invalid_tx | wrong_status | not_buy | payfast_*

    force=True — пропустить проверку Payfast (status_check/recheck). Финансовые
    ограничения (crypto_exceeds_paid) остаются активными.
    """
    from services.db import get_order, get_pool, transition_buy_payout_to_paid_in_tx

    normalized = normalize_tx_hash(tx_hash)
    if not normalized:
        return False, "invalid_tx", None

    order_pre = await get_order(order_id.strip())
    if order_pre and str(order_pre.get("status") or "").upper() == "PAID":
        existing = str(order_pre.get("payout_tx_hash") or "").strip()
        if existing and existing.lower() == normalized.lower():
            return True, None, dict(order_pre)
        return False, "already_paid", dict(order_pre)
    if order_pre:
        from services.payin_requisite_rail import is_payin_order
        from services.payment_snapshot import reki_payfast_id

        if force:
            logger.warning(
                "FORCE payout order=%s actor=%s — Payfast check bypassed",
                order_id,
                actor,
            )
        elif is_payin_order(order_pre) or reki_payfast_id(order_pre):
            logger.info("requisite payin payout skips payfast order=%s", order_id)
        else:
            from services.payfast_payin_guard import verify_payfast_ready_for_payout

            ok_pf, pf_err, _ = await verify_payfast_ready_for_payout(
                dict(order_pre), require_uuid=True
            )
            if not ok_pf:
                logger.error(
                    "payout blocked payfast order=%s reason=%s",
                    order_id,
                    pf_err,
                )
                return False, pf_err, dict(order_pre)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ok, err, order_out = await transition_buy_payout_to_paid_in_tx(
                conn,
                order_id.strip(),
                payout_tx_hash=normalized,
                payout_confirmed_by=actor,
                operator_id=operator_id,
            )
    if not ok:
        if err in ("crypto_exceeds_paid", "amount_mismatch"):
            logger.error(
                "payout blocked order=%s reason=%s",
                order_id,
                err,
            )
        return False, err, order_out
    explorer = build_explorer_url(str(order_out.get("crypto", "")), normalized)
    if str((order_pre or {}).get("status") or "").upper() != "PAID":
        schedule_paid_notifications(order_out, explorer, bot=bot)
    from services.partner_tracking import schedule_partner_exchange

    schedule_partner_exchange(dict(order_out))
    return True, None, order_out


async def confirm_manual_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
    bot=None,
) -> tuple[bool, str | None, dict | None]:
    """
    OPERATOR_PENDING → PAID с записью tx hash (ручная BUY-заявка).
    Returns (ok, error_code, order_dict).
    """
    from services.db import get_order, get_pool, transition_manual_buy_payout_to_paid_in_tx

    normalized = normalize_tx_hash(tx_hash)
    if not normalized:
        return False, "invalid_tx", None

    order_pre = await get_order(order_id.strip())
    if not order_pre:
        return False, "not_found", None
    was_paid = str(order_pre.get("status") or "").upper() == "PAID"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ok, err, order_out = await transition_manual_buy_payout_to_paid_in_tx(
                conn,
                order_id.strip(),
                payout_tx_hash=normalized,
                payout_confirmed_by=actor,
                operator_id=operator_id,
            )
    if not ok:
        return False, err, order_out

    if not was_paid:
        explorer = build_explorer_url(str(order_out.get("crypto", "")), normalized)
        schedule_paid_notifications(order_out, explorer, bot=bot)
        try:
            from services.stale_payin_hold import close_open_payins_superseded_by_paid

            await close_open_payins_superseded_by_paid(order_out, bot=bot)
        except Exception:
            logger.exception(
                "close superseded payins after manual paid failed order=%s",
                order_id,
            )
    from services.partner_tracking import schedule_partner_exchange

    schedule_partner_exchange(dict(order_out))
    return True, None, order_out


async def confirm_awaiting_check_buy_payout(
    order_id: str,
    *,
    tx_hash: str,
    actor: str,
    operator_id: int | None = None,
    bot=None,
) -> tuple[bool, str | None, dict | None]:
    """
    AWAITING_CHECK → PAID с записью tx hash (админская BUY-заявка).
    Returns (ok, error_code, order_dict).
    """
    from services.db import (
        get_order,
        get_pool,
        transition_awaiting_check_buy_payout_to_paid_in_tx,
    )

    normalized = normalize_tx_hash(tx_hash)
    if not normalized:
        return False, "invalid_tx", None

    order_pre = await get_order(order_id.strip())
    if not order_pre:
        return False, "not_found", None
    was_paid = str(order_pre.get("status") or "").upper() == "PAID"

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ok, err, order_out = await transition_awaiting_check_buy_payout_to_paid_in_tx(
                conn,
                order_id.strip(),
                payout_tx_hash=normalized,
                payout_confirmed_by=actor,
                operator_id=operator_id,
            )
    if not ok:
        return False, err, order_out

    if not was_paid:
        explorer = build_explorer_url(str(order_out.get("crypto", "")), normalized)
        schedule_paid_notifications(order_out, explorer, bot=bot)
    from services.partner_tracking import schedule_partner_exchange

    schedule_partner_exchange(dict(order_out))
    return True, None, order_out

"""Заявки партнёров на вывод баланса."""
from __future__ import annotations

import html
import logging

import asyncpg

from config import settings
from crypto_network_fee import (
    format_crypto_withdraw_limits,
    min_crypto_amount_rub,
    payout_from_fee,
    resolve_usdt_rub,
    withdraw_fee_rub,
)
from db import get_pool
from partner_commission import get_campaign_available_balance, get_campaign_balance

logger = logging.getLogger("partner_withdraw")

ALLOWED_CRYPTOS = frozenset({"usdt", "trx", "ltc", "btc"})


def _method_label(wd: dict) -> str:
    if (wd.get("method") or "").lower() == "card":
        return "💳 Карта / СБП"
    crypto = html.escape((wd.get("crypto") or "")).upper()
    net = html.escape((wd.get("network") or "")).upper()
    return f"🪙 Крипта: {crypto} {net}".strip()


async def has_pending_withdrawal(conn, campaign_id: int) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1 FROM partner_withdrawals
            WHERE campaign_id = $1
              AND status IN ('pending', 'reserved', 'sending')
            LIMIT 1
            """,
            campaign_id,
        )
    )


async def create_partner_withdrawal(
    *,
    campaign_id: int,
    partner_account_id: int,
    amount_rub: float,
    method: str,
    requisites: str,
    crypto: str | None = None,
    network: str | None = None,
) -> dict:
    amount = round(float(amount_rub), 2)
    if amount <= 0:
        raise ValueError("Укажите сумму больше нуля")

    method = method.lower().strip()
    req = (requisites or "").strip()
    if len(req) < 5:
        raise ValueError("Укажите реквизиты для выплаты")

    if method == "card":
        min_card = int(settings.partner_min_withdraw_card_rub)
        if amount < min_card:
            raise ValueError(f"Минимум для карты: {min_card:,.0f} ₽".replace(",", " "))
        network_fee = withdraw_fee_rub("card", None, usdt_rub=None)
    elif method == "crypto":
        c = (crypto or "").lower().strip()
        if c not in ALLOWED_CRYPTOS:
            raise ValueError("Доступно: USDT, TRX, LTC, BTC")
        min_rub = await min_crypto_amount_rub(c)
        if amount < min_rub - 0.01:
            raise ValueError(
                f"Минимум для крипты: ~{min_rub:,.0f} ₽ "
                f"({format_crypto_withdraw_limits(c)} в {c.upper()})"
            )
        if c == "usdt":
            n = (network or "").lower().strip()
            if n not in ("trc20", "erc20"):
                raise ValueError("Для USDT укажите сеть TRC20 или ERC20")
            network = n
        else:
            network = None
        crypto = c
        network_fee = withdraw_fee_rub(
            "crypto", c, usdt_rub=await resolve_usdt_rub()
        )
    else:
        raise ValueError("Выберите способ: карта или крипта")
    payout_rub = payout_from_fee(amount, network_fee)
    if payout_rub <= 0:
        raise ValueError(
            f"Сумма слишком мала: комиссия {network_fee:,.2f} ₽. "
            "Увеличьте сумму вывода."
        )

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock($1)",
                    campaign_id,
                )
                if await has_pending_withdrawal(conn, campaign_id):
                    raise ValueError("У вас уже есть заявка на вывод в обработке")

                # Если у партнёра привязан Telegram — учитываем единый счёт,
                # иначе можно вывести одни и те же деньги дважды: через unified
                # (user_referral_withdrawals) и через partner-only путь.
                tg_row = await conn.fetchrow(
                    "SELECT telegram_user_id FROM partner_accounts WHERE id = $1",
                    partner_account_id,
                )
                tg_id = tg_row["telegram_user_id"] if tg_row else None
                unified_pending = 0.0
                if tg_id:
                    # Сериализуемся с unified-путём (он лочит referrer_user_id).
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock($1)", int(tg_id)
                    )
                    if await conn.fetchval(
                        """
                        SELECT 1 FROM user_referral_withdrawals
                        WHERE referrer_user_id = $1
                          AND status IN ('pending', 'reserved', 'sending')
                        LIMIT 1
                        """,
                        int(tg_id),
                    ):
                        raise ValueError(
                            "У вас уже есть заявка на вывод в обработке"
                        )
                    unified_pending = float(
                        await conn.fetchval(
                            """
                            SELECT COALESCE(SUM(amount_rub), 0)::float
                            FROM user_referral_withdrawals
                            WHERE referrer_user_id = $1 AND status = 'pending'
                            """,
                            int(tg_id),
                        )
                        or 0
                    )

                available = await get_campaign_available_balance(conn, campaign_id)
                available -= unified_pending
                # Запертый отыгрышем casino-депозит недоступен и на партнёрском выводе.
                if tg_id is not None:
                    from casino_wagering import locked_by_wagering

                    available -= float(await locked_by_wagering(conn, int(tg_id)))
                if amount > available + 0.01:
                    raise ValueError(
                        f"Недостаточно средств. Доступно: {available:,.2f} ₽"
                    )

                row = await conn.fetchrow(
                    """
                    INSERT INTO partner_withdrawals (
                        campaign_id, partner_account_id, amount_rub,
                        method, requisites, crypto, network, status,
                        network_fee_rub, payout_amount_rub
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, $9)
                    RETURNING *
                    """,
                    campaign_id,
                    partner_account_id,
                    amount,
                    method,
                    req,
                    crypto,
                    network,
                    network_fee,
                    payout_rub,
                )
        return dict(row)
    except asyncpg.UniqueViolationError:
        raise ValueError("У вас уже есть заявка на вывод в обработке") from None


def withdrawal_out(row: dict) -> dict:
    r = dict(row)
    for key in ("created_at", "processed_at"):
        val = r.get(key)
        if val and hasattr(val, "isoformat"):
            r[key] = val.isoformat()
    r["amount_rub"] = float(r["amount_rub"])
    r["network_fee_rub"] = float(r.get("network_fee_rub") or 0)
    r["payout_amount_rub"] = float(
        r.get("payout_amount_rub")
        if r.get("payout_amount_rub") is not None
        else payout_from_fee(r["amount_rub"], r["network_fee_rub"])
    )
    return r


def format_partner_withdrawal_admin_message(wd: dict, *, username: str | None) -> str:
    uname = html.escape(
        f"@{username}" if username else f"campaign #{wd['campaign_id']}"
    )
    requisites = html.escape(str(wd.get("requisites") or ""))
    site = settings.public_site_url.rstrip("/")
    lines = [
        f"💸 <b>Заявка на вывод партнёра</b> #{wd['id']}\n",
        f"👤 Партнёр: {uname}",
        f"💰 Сумма: <b>{float(wd['amount_rub']):,.2f} ₽</b>",
        f"💸 Комиссия: <b>{float(wd.get('network_fee_rub') or 0):,.2f} ₽</b>",
        f"✅ К выплате: <b>{float(wd.get('payout_amount_rub') or wd['amount_rub']):,.2f} ₽</b>",
        _method_label(wd),
        f"📝 Реквизиты:\n<code>{requisites}</code>",
        f'🌐 <a href="{site}/x8/partners/{wd["campaign_id"]}">Кабинет админа</a>',
    ]
    tx = wd.get("payout_tx_hash")
    if tx:
        lines.append(f"🔗 Tx: <code>{html.escape(str(tx))}</code>")
    return "\n".join(lines)


async def process_partner_withdrawal_paid(
    withdrawal_id: int,
    *,
    admin_web_user_id: int | None = None,
    payout_tx_hash: str | None = None,
) -> tuple[dict | None, str | None]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            wd = await conn.fetchrow(
                """
                SELECT w.*, pa.username
                FROM partner_withdrawals w
                JOIN partner_accounts pa ON pa.id = w.partner_account_id
                WHERE w.id = $1
                FOR UPDATE OF w
                """,
                withdrawal_id,
            )
            if not wd or wd["status"] != "pending":
                return None, None

            exists = await conn.fetchval(
                """
                SELECT 1 FROM partner_ledger
                WHERE withdrawal_id = $1
                """,
                withdrawal_id,
            )
            if exists:
                return None, "already_paid"

            balance = await get_campaign_balance(conn, wd["campaign_id"])
            pending_others = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM partner_withdrawals
                WHERE campaign_id = $1 AND status = 'pending' AND id != $2
                """,
                wd["campaign_id"],
                withdrawal_id,
            )
            # Учитываем pending единого счёта (TG партнёра), чтобы не выплатить
            # дважды деньги, уже зарезервированные unified-выводом.
            tg_id = await conn.fetchval(
                "SELECT telegram_user_id FROM partner_accounts WHERE id = $1",
                wd["partner_account_id"],
            )
            unified_pending = 0.0
            if tg_id:
                unified_pending = float(
                    await conn.fetchval(
                        """
                        SELECT COALESCE(SUM(amount_rub), 0)::float
                        FROM user_referral_withdrawals
                        WHERE referrer_user_id = $1 AND status = 'pending'
                        """,
                        int(tg_id),
                    )
                    or 0
                )
            available = balance - float(pending_others or 0) - unified_pending
            # Запертый отыгрышем casino-депозит недоступен и на партнёрском выводе.
            if tg_id:
                from casino_wagering import locked_by_wagering

                available -= float(await locked_by_wagering(conn, int(tg_id)))
            amount = float(wd["amount_rub"])
            if amount > available + 0.01:
                return None, "insufficient_balance"

            note = (
                f"Вывод #{withdrawal_id}: {_method_label(dict(wd))} — "
                f"{wd['requisites'][:120]}"
            )
            await conn.fetchrow(
                """
                INSERT INTO partner_ledger (
                    campaign_id, type, amount_rub, note,
                    withdrawal_id, created_by_web_user_id
                )
                VALUES ($1, 'payout', $2, $3, $4, $5)
                RETURNING id
                """,
                wd["campaign_id"],
                -round(amount, 2),
                note,
                withdrawal_id,
                admin_web_user_id,
            )
            row = await conn.fetchrow(
                """
                UPDATE partner_withdrawals
                SET status = 'paid',
                    processed_at = now(),
                    payout_tx_hash = $2,
                    processed_by_web_user_id = $3
                WHERE id = $1
                RETURNING *
                """,
                withdrawal_id,
                payout_tx_hash,
                admin_web_user_id,
            )
            out = dict(row)
            out["username"] = wd["username"]
            return out, None


async def reject_partner_withdrawal(
    withdrawal_id: int,
    *,
    admin_web_user_id: int | None = None,
    reason: str | None = None,
) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE partner_withdrawals
            SET status = 'rejected',
                processed_at = now(),
                processed_by_web_user_id = $2,
                reject_reason = $3
            WHERE id = $1 AND status = 'pending'
            RETURNING *
            """,
            withdrawal_id,
            admin_web_user_id,
            reason,
        )
    return dict(row) if row else None


async def notify_partner_withdrawal_status(wd: dict, *, paid: bool) -> None:
    from partner_telegram_notify import send_partner_telegram_dm

    pool = await get_pool()
    async with pool.acquire() as conn:
        tg_id = await conn.fetchval(
            """
            SELECT telegram_user_id FROM partner_accounts
            WHERE id = $1
            """,
            wd["partner_account_id"],
        )
    if not tg_id:
        return

    wid = int(wd["id"])
    amount = float(wd["amount_rub"])
    if paid:
        text = (
            f"✅ Заявка на вывод #{wid} на сумму <b>{amount:,.2f} ₽</b> выполнена."
        )
        tx = wd.get("payout_tx_hash")
        if tx and (wd.get("method") or "").lower() == "crypto":
            try:
                import os
                import sys

                root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
                if root not in sys.path:
                    sys.path.insert(0, root)
                from services.buy_payout import build_explorer_url

                c = (wd.get("crypto") or "").lower()
                n = (wd.get("network") or "").lower()
                key = f"{c}_{n}" if n else c
                url = build_explorer_url(key, tx)
                if url:
                    text += f'\n🔗 <a href="{url}">Транзакция</a>'
            except Exception:
                logger.debug("ignored non-fatal error", exc_info=True)
    else:
        reason = wd.get("reject_reason") or "обратитесь в поддержку"
        text = (
            f"❌ Заявка на вывод #{wid} на сумму <b>{amount:,.2f} ₽</b> отклонена.\n"
            f"{html.escape(str(reason))}"
        )
    await send_partner_telegram_dm(int(tg_id), text)

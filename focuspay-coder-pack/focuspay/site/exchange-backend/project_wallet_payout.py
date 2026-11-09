"""Ручная заявка: выплата крипты с кошелька проекта вместо кошелька оператора.

Оператор не задаёт ни сумму в крипте (её считает сервер), ни момент отправки без
2FA. Окно подтверждения и отправка связаны подписанным токеном: отправляется
ровно то, что было показано. Каждая отправка пишется на смену оператора —
рубли пришли на его карту, он их должен проекту.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from auto_settings import (
    manual_payout_wallet,
    manual_wallet_payout_max_rub,
    manual_wallet_payout_operator_daily_rub,
)
from config import settings

logger = logging.getLogger("project_wallet_payout")

PROJECT_COINS = ("btc", "ltc")
PREVIEW_TTL_SEC = 120
RATE_DRIFT_MAX = 0.01
TOTP_FAIL_LIMIT = 3
TOTP_LOCK_SEC = 15 * 60
REQUEST_KIND = "manual_buy"
# Дневной потолок оператора общий: выплата по заявке и размен с горячего кошелька.
CAP_KINDS = (REQUEST_KIND, "swap_send")


def next_project_send_request_id(order_id: str, previous: list[dict]) -> str:
    """Новый номер, если прошлая попытка только отказ. Любая другая запись — стоп.

    Подписант помнит отказ по request_id навсегда, в том числе отказ автопилота
    на `order:{id}`. Повтор после такого отказа идёт с суффиксом.
    """
    for row in previous:
        status = str(row.get("status") or "")
        txid = str(row.get("txid") or "").strip()
        if status not in ("failed", "requeued") or txid:
            raise WalletPayoutError(
                409,
                "already_sent",
                "По заявке уже есть отправка с кошелька проекта — дождитесь проверки админом",
            )
    base = f"order:{order_id}"
    if not previous:
        return base
    return f"{base}-r{len(previous)}"

_totp_fails: dict[int, list[float]] = {}


class WalletPayoutError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def hard_failures(checks: list[Check]) -> list[Check]:
    """Адрес другого клиента оператор может подтвердить. Остальное блокирует."""
    return [c for c in checks if not c.ok and c.key != "address_other_client"]


def coin_of(crypto: Any) -> str:
    return str(crypto or "").split("_")[0].strip().lower()


def project_mode_for(crypto: Any) -> bool:
    return manual_payout_wallet() == "project" and coin_of(crypto) in PROJECT_COINS


# ------------------------------------------------------------------ token


def _secret() -> bytes:
    key = (settings.secret_key or "").encode()
    if not key:
        raise WalletPayoutError(503, "not_configured", "Сервер не настроен (secret_key)")
    return hashlib.sha256(b"project-wallet-preview:" + key).digest()


def fingerprint(fields: dict[str, Any]) -> str:
    canon = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


def make_preview_token(
    *,
    operator_id: int,
    fp: str,
    address: str,
    crypto_amount: float,
    amount_rub: float,
    base_rate: float,
) -> str:
    payload = {
        "op": int(operator_id),
        "fp": fp,
        "addr": address,
        "amt": f"{Decimal(str(crypto_amount)):.8f}",
        "rub": round(float(amount_rub), 2),
        "rate": float(base_rate),
        "exp": int(time.time()) + PREVIEW_TTL_SEC,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def read_preview_token(token: str, *, operator_id: int, fp: str) -> dict[str, Any]:
    try:
        raw, sig = str(token or "").rsplit(".", 1)
    except ValueError:
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново") from None
    expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise WalletPayoutError(400, "bad_token", "Откройте окно подтверждения заново")
    payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    if int(payload.get("op") or 0) != int(operator_id):
        raise WalletPayoutError(403, "bad_token", "Окно подтверждения открыто другим оператором")
    if int(payload.get("exp") or 0) < time.time():
        raise WalletPayoutError(409, "token_expired", "Окно устарело — откройте подтверждение заново")
    if payload.get("fp") != fp:
        raise WalletPayoutError(
            409, "data_changed", "Данные заявки изменились после подтверждения — проверьте и откройте окно заново"
        )
    return payload


def same_amount(a: float, b: str | float) -> bool:
    return f"{Decimal(str(a)):.8f}" == f"{Decimal(str(b)):.8f}"


def rate_close(market: float, pinned: float) -> bool:
    if pinned <= 0:
        return False
    return abs(market - pinned) / pinned <= RATE_DRIFT_MAX


# ------------------------------------------------------------------- 2FA


def _locked_until(operator_id: int) -> float:
    now = time.time()
    fails = [t for t in _totp_fails.get(operator_id, []) if t > now - TOTP_LOCK_SEC]
    _totp_fails[operator_id] = fails
    if len(fails) >= TOTP_FAIL_LIMIT:
        return fails[-TOTP_FAIL_LIMIT] + TOTP_LOCK_SEC
    return 0.0


def ensure_not_locked(operator_id: int) -> None:
    until = _locked_until(operator_id)
    if until > time.time():
        mins = max(1, int((until - time.time()) // 60) + 1)
        raise WalletPayoutError(
            429, "totp_locked", f"Слишком много неверных кодов. Отправка заблокирована на {mins} мин."
        )


def _matching_step(secret: str, code: str) -> int | None:
    from totp_auth import TOTP_DIGITS, TOTP_INTERVAL, TOTP_WINDOW, _hotp

    code = str(code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    step = int(time.time()) // TOTP_INTERVAL
    for offset in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        if str(_hotp(secret, step + offset)).zfill(TOTP_DIGITS) == code:
            return step + offset
    return None


async def consume_totp(conn, operator_id: int, code: str) -> None:
    """Проверяет код и «сжигает» его шаг: повтор того же кода не пройдёт."""
    ensure_not_locked(operator_id)
    row = await conn.fetchrow(
        "SELECT totp_secret, totp_enabled FROM operator_accounts WHERE id = $1",
        int(operator_id),
    )
    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        raise WalletPayoutError(403, "totp_missing", "У оператора не включена 2FA")
    step = _matching_step(row["totp_secret"], code)
    claimed = None
    if step is not None:
        claimed = await conn.fetchval(
            """
            UPDATE operator_accounts SET totp_last_step = $2
            WHERE id = $1 AND (totp_last_step IS NULL OR totp_last_step < $2)
            RETURNING id
            """,
            int(operator_id),
            step,
        )
    if claimed:
        _totp_fails.pop(operator_id, None)
        return
    _totp_fails.setdefault(operator_id, []).append(time.time())
    if _locked_until(operator_id) > time.time():
        await notify_admin(
            f"⚠️ Оператор #{operator_id}: {TOTP_FAIL_LIMIT} неверных кода 2FA при отправке "
            "с кошелька проекта. Отправка заблокирована на 15 минут."
        )
    reason = "Код уже использован — дождитесь нового" if step is not None else "Неверный код 2FA"
    raise WalletPayoutError(401, "totp_invalid", reason)


# --------------------------------------------------------------- checks


@dataclass
class Check:
    key: str
    ok: bool
    detail: str = ""

    def out(self) -> dict[str, Any]:
        return {"key": self.key, "ok": self.ok, "detail": self.detail}


async def address_checks(conn, *, user_id: int, address: str) -> tuple[list[Check], int]:
    addr = (address or "").strip()
    if not addr:
        return [Check("address", False, "Не указан кошелёк клиента")], 0
    sent_before = int(
        await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM orders
            WHERE user_id = $1 AND lower(direction) = 'buy' AND status = 'PAID'
              AND (wallet_address = $2 OR requisites = $2)
            """,
            int(user_id),
            addr,
        )
        or 0
    )
    other_client = await conn.fetchval(
        """
        SELECT user_id FROM orders
        WHERE user_id <> $1 AND lower(direction) = 'buy' AND status = 'PAID'
          AND (wallet_address = $2 OR requisites = $2)
        LIMIT 1
        """,
        int(user_id),
        addr,
    )
    operator_owned = await conn.fetchval(
        """
        SELECT oa.id FROM operator_accounts oa
        WHERE oa.telegram_user_id IS NOT NULL AND (
            EXISTS (
                SELECT 1 FROM orders o
                WHERE o.user_id = oa.telegram_user_id
                  AND (o.wallet_address = $1 OR o.requisites = $1)
            )
            OR EXISTS (
                SELECT 1 FROM user_referral_withdrawals w
                WHERE w.referrer_user_id = oa.telegram_user_id AND w.requisites = $1
            )
        )
        LIMIT 1
        """,
        addr,
    )
    own_wallet = addr.lower() in {a.strip().lower() for a in await own_addresses() if a}
    checks = [
        Check("address_other_client", other_client is None, "" if other_client is None else "адрес другого клиента"),
        Check("address_operator", operator_owned is None, "" if operator_owned is None else "адрес оператора"),
        Check("address_own", not own_wallet, "" if not own_wallet else "это наш адрес"),
    ]
    return checks, sent_before


async def own_addresses() -> list[str]:
    """Адреса проекта: отправка на них — либо ошибка, либо попытка вывести через нас."""
    from project_wallet_archive import addresses_from_signer_payload
    from runtime_settings import get_settings_sync
    from signer_client import fetch_signer_deposit_addresses, signer_configured

    out = [str(get_settings_sync().get("sell_deposit_address_btc") or "")]
    if signer_configured():
        try:
            dep = await fetch_signer_deposit_addresses()
            out += addresses_from_signer_payload(dep)
        except Exception:
            logger.warning("deposit addresses unavailable", exc_info=True)
    return out


async def operator_sent_today_rub(conn, operator_id: int) -> float:
    val = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount_rub), 0)::float
        FROM payout_requests
        WHERE kind = ANY($2::text[]) AND operator_id = $1
          AND status IN ('queued', 'sent', 'confirmed')
          AND created_at >= date_trunc('day', now())
        """,
        int(operator_id),
        list(CAP_KINDS),
    )
    return float(val or 0)


async def limit_checks(conn, *, operator_id: int, amount_rub: float) -> tuple[list[Check], dict]:
    from auto_payout_worker import daily_cap_room

    per = manual_wallet_payout_max_rub()
    daily = manual_wallet_payout_operator_daily_rub()
    used = await operator_sent_today_rub(conn, operator_id)
    room = await daily_cap_room(conn)
    op_left = max(0.0, daily - used)
    checks = [
        Check("limit_per_payout", per <= 0 or amount_rub <= per + 0.01, f"{amount_rub:,.0f} / {per:,.0f} ₽".replace(",", " ")),
        Check("limit_operator_day", amount_rub <= op_left + 0.01, f"осталось {op_left:,.0f} ₽".replace(",", " ")),
        Check("limit_wallet_day", amount_rub <= room + 0.01, f"осталось {room:,.0f} ₽".replace(",", " ")),
    ]
    return checks, {"operator_left_rub": op_left, "wallet_day_left_rub": room, "per_payout_max_rub": per}


async def wallet_checks(conn, *, coin: str, crypto_amount: float, rate_rub: float) -> tuple[list[Check], dict]:
    from auto_payout_guard import signer_circuit_closed
    from signer_client import fetch_signer_balances, fetch_signer_fee_estimate, fetch_signer_health

    circuit = await signer_circuit_closed(conn)
    health = await fetch_signer_health()
    node = ((health.get("nodes") or {}).get(coin)) or {}
    bal = await fetch_signer_balances()
    from hot_wallet_topups import effective_spendable, pending_unconfirmed

    coin_row = ((bal.get("coins") or {}).get(coin)) or {}
    spendable = effective_spendable(coin_row)
    pending = pending_unconfirmed(coin_row)
    fee_info = await fetch_signer_fee_estimate(coin)
    fee = float(fee_info.get("fee") or 0) if fee_info.get("ok") else 0.0
    need = crypto_amount + fee
    balance_detail = f"{spendable:.8f} {coin.upper()}"
    if pending > 0:
        balance_detail += f", ещё {pending:.8f} ждёт подтверждения"
    dry_run = bool(health.get("dry_run"))
    node_ready = bool(node.get("ok")) and not node.get("syncing")
    checks = [
        Check("signer", bool(circuit) and health.get("http_status") == 200, "" if circuit else "кошелёк не на связи"),
        Check("live", not dry_run, "" if not dry_run else "кошелёк в тестовом режиме — реальной отправки не будет"),
        Check("node", node_ready, "" if node_ready else "нода синхронизируется"),
        Check("balance", spendable + 1e-12 >= need, balance_detail),
    ]
    info = {
        "pending_crypto": round(pending, 8),
        "pending_covers": spendable + pending + 1e-12 >= need,
        "fee_crypto": round(fee, 8),
        "fee_rub": round(fee * rate_rub, 2),
        "fee_sat_vb": fee_info.get("feerate_sat_vb"),
        "fee_estimated": bool(fee_info.get("estimated")),
        "balance_crypto": spendable,
        "balance_after_crypto": round(max(0.0, spendable - need), 8),
        "dry_run": dry_run,
    }
    return checks, info


async def run_checks(
    conn,
    *,
    operator_id: int,
    user_id: int,
    coin: str,
    address: str,
    crypto_amount: float,
    amount_rub: float,
    rate_rub: float,
) -> tuple[list[Check], dict[str, Any]]:
    addr_c, sent_before = await address_checks(conn, user_id=user_id, address=address)
    lim_c, lim_info = await limit_checks(conn, operator_id=operator_id, amount_rub=amount_rub)
    wal_c, wal_info = await wallet_checks(conn, coin=coin, crypto_amount=crypto_amount, rate_rub=rate_rub)
    return addr_c + lim_c + wal_c, {"sent_before": sent_before, **lim_info, **wal_info}


async def build_preview(
    conn,
    *,
    operator_id: int,
    fp: str,
    user_id: int,
    crypto: str,
    address: str,
    crypto_amount: float,
    amount_rub: float,
    base_rate: float,
) -> dict[str, Any]:
    coin = coin_of(crypto)
    checks, info = await run_checks(
        conn,
        operator_id=operator_id,
        user_id=user_id,
        coin=coin,
        address=address,
        crypto_amount=crypto_amount,
        amount_rub=amount_rub,
        rate_rub=base_rate,
    )
    hard = hard_failures(checks)
    ok = not hard
    token = None
    if ok:
        token = make_preview_token(
            operator_id=operator_id,
            fp=fp,
            address=address,
            crypto_amount=crypto_amount,
            amount_rub=amount_rub,
            base_rate=base_rate,
        )
    return {
        "ok": ok,
        "preview_token": token,
        "expires_in": PREVIEW_TTL_SEC,
        "coin": coin,
        "address": address,
        "crypto_amount": float(f"{Decimal(str(crypto_amount)):.8f}"),
        "amount_rub": round(float(amount_rub), 2),
        "market_rate": round(float(base_rate), 2),
        "checks": [c.out() for c in checks],
        **info,
    }


_op_locks: dict[int, asyncio.Lock] = {}


def operator_lock(operator_id: int) -> asyncio.Lock:
    """Одна отправка за раз на оператора: лимиты не обойти параллельными кликами."""
    return _op_locks.setdefault(int(operator_id), asyncio.Lock())


async def authorize(
    conn,
    *,
    operator_id: int,
    token: str,
    fp: str,
    totp_code: str,
    user_id: int,
    crypto: str,
    address: str,
    allow_other_client: bool = False,
) -> dict[str, Any]:
    """Токен окна → повторные проверки → 2FA. Возвращает подписанный payload."""
    ensure_not_locked(operator_id)
    payload = read_preview_token(token, operator_id=operator_id, fp=fp)
    if str(payload.get("addr") or "") != address:
        raise WalletPayoutError(409, "data_changed", "Адрес изменился — откройте окно подтверждения заново")
    checks, _info = await run_checks(
        conn,
        operator_id=operator_id,
        user_id=user_id,
        coin=coin_of(crypto),
        address=address,
        crypto_amount=float(payload["amt"]),
        amount_rub=float(payload["rub"]),
        rate_rub=float(payload["rate"]),
    )
    failed = hard_failures(checks)
    other_client = next((c for c in checks if c.key == "address_other_client" and not c.ok), None)
    if other_client and not allow_other_client:
        failed.append(other_client)
    if failed:
        raise WalletPayoutError(
            409,
            "checks_failed",
            "Проверка не прошла: " + ", ".join(f"{c.key} {c.detail}".strip() for c in failed),
        )
    await consume_totp(conn, operator_id, totp_code)
    if other_client and allow_other_client:
        await notify_admin(
            f"Оператор #{operator_id} подтвердил отправку на адрес другого клиента "
            f"<code>{address}</code>, user <code>{user_id}</code>."
        )
    return payload


# ----------------------------------------------------------------- send


async def notify_admin(text: str) -> None:
    try:
        from telegram_notify import send_admin_message

        await send_admin_message(text)
    except Exception:
        logger.warning("admin notify failed: %s", text, exc_info=True)


async def send_from_project_wallet(
    *,
    order_id: str,
    user_id: int,
    coin: str,
    address: str,
    crypto_amount: float,
    amount_rub: float,
    operator_id: int,
) -> tuple[str, dict[str, Any]]:
    """accepted|rejected|unknown. Запись в payout_requests — до отправки.

    Подписант запоминает отказ навсегда, поэтому повторная попытка после отказа
    идёт с новым request_id. Если прошлая отправка не завершилась отказом —
    повтор запрещён: крипта могла уйти.
    """
    from auto_payout_audit_log import audit_payout_event
    from auto_payout_worker import _enqueue_payout_request, _mark_request
    from db import get_pool
    from signer_client import submit_signer_payout

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"pw:{order_id}")
            prev = await conn.fetch(
                "SELECT request_id, status, txid FROM payout_requests WHERE ref_id = $1",
                order_id,
            )
            request_id = next_project_send_request_id(order_id, [dict(row) for row in prev])
            await _enqueue_payout_request(
                conn,
                request_id=request_id,
                kind=REQUEST_KIND,
                ref_id=order_id,
                user_id=int(user_id),
                coin=coin,
                address=address,
                amount_crypto=crypto_amount,
                amount_rub=round(amount_rub, 2),
            )
            await conn.execute(
                "UPDATE payout_requests SET operator_id = $2 WHERE request_id = $1",
                request_id,
                int(operator_id),
            )
    await audit_payout_event(request_id, "manual_wallet_send", {"operator_id": operator_id})
    st, resp = await submit_signer_payout(
        {
            "request_id": request_id,
            "coin": coin,
            "address": address,
            "amount": crypto_amount,
            "amount_rub": round(amount_rub, 2),
            "order_ref": order_id,
            "kind": REQUEST_KIND,
        }
    )
    await audit_payout_event(request_id, f"signer_{st}", resp)
    if st == "duplicate":
        st = "accepted" if resp.get("txid") else "unknown"
    async with pool.acquire() as conn:
        if st == "accepted":
            await _mark_request(conn, request_id, "sent", str(resp.get("txid") or ""))
        elif st == "rejected":
            await _mark_request(conn, request_id, "failed")
            await conn.execute(
                "UPDATE payout_requests SET reject_reason = $2 WHERE request_id = $1",
                request_id,
                str(resp.get("reason") or resp.get("error") or "rejected")[:200],
            )
        else:
            await conn.execute(
                "UPDATE payout_requests SET reject_reason = 'signer_unknown', updated_at = now() WHERE request_id = $1",
                request_id,
            )
    resp["request_id"] = request_id
    return st, resp


async def mark_confirmed(request_id: str) -> None:
    from auto_payout_worker import _mark_request
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await _mark_request(conn, request_id, "confirmed")


async def record_shift_recon(
    *, order_id: str, operator_id: int, amount_rub: float, coin: str, txid: str
) -> None:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        shift_id = await conn.fetchval(
            "SELECT id FROM operator_shifts WHERE operator_id = $1 AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            int(operator_id),
        )
        await conn.execute(
            """
            INSERT INTO auto_recon_entries (
                shift_id, order_id, amount_rub, coin, txid, note, operator_id, kind
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'project_wallet_payout')
            """,
            shift_id,
            order_id,
            round(float(amount_rub), 2),
            coin,
            txid,
            "Крипта с кошелька проекта; рубли на карте оператора",
            int(operator_id),
        )

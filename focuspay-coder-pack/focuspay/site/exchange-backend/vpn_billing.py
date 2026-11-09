"""FocusVPN billing: tariffs, gates, purchase/trial saga and reconciliation.

FocusPay owns money, prices and gates; the FocusVPN control plane (CP) owns days.
Order of a purchase:
  1. lock user, check gate, insert vpn_purchases(held), hold unified balance;
  2. CP grant (idempotent by purchase id: same id never extends twice);
  3. confirm hold -> spend, status paid.
A purchase is released only when CP definitively refuses (4xx). Network errors
leave it held; the reconcile loop retries the grant until it resolves.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import aiohttp

from casino_finance import confirm_unified_hold, money, release_unified_hold, reserve_unified_funds

logger = logging.getLogger(__name__)

SETTINGS_KEY = "vpn_billing"
# Separate from vpn_billing: save_settings replaces that whole object.
TRUSTED_KEY = "vpn_trusted_ids"
RECONCILE_AFTER_SEC = 120
RECONCILE_INTERVAL_SEC = 60
CP_TIMEOUT_SEC = 10

DEFAULT_SETTINGS: dict[str, Any] = {
    "plans": [
        {"code": "week", "title": "Неделя", "days": 7, "price_rub": "300.00"},
        {"code": "month", "title": "Месяц", "days": 30, "price_rub": "990.00"},
        {"code": "q3", "title": "3 месяца", "days": 90, "price_rub": "2490.00"},
    ],
    # One extra phone for its own term. Missing key fills these; an empty list turns the offer off.
    "device_addons": [
        {"code": "week", "title": "Неделя", "days": 7, "price_rub": "300.00"},
        {"code": "month", "title": "Месяц", "days": 30, "price_rub": "990.00"},
        {"code": "q3", "title": "3 месяца", "days": 90, "price_rub": "2490.00"},
    ],
    # Trial is open to everyone; buying unlocks after N completed exchanges.
    "trial": {"enabled": True, "days": 1, "min_exchanges": 0},
    "purchase_min_exchanges": 10,
    # Referrers with this many invited people may buy without the exchange count.
    "purchase_min_invited": 30,
    "app_url": "https://focuspay.org/vpn.apk",
    # Review bonus on the FocusPay balance. Text, then text plus a screenshot of the app.
    "review_bonus_text_rub": 25,
    "review_bonus_photo_rub": 50,
}


class GateError(Exception):
    def __init__(self, need: int, have: int, invited_need: int = 0, invited_have: int = 0):
        super().__init__(
            f"Need {need} completed exchanges or {invited_need} invited; have {have} exchanges and {invited_have} invited"
        )
        self.need = need
        self.have = have
        self.invited_need = invited_need
        self.invited_have = invited_have


class BillingError(Exception):
    """Business refusal shown to the user (unknown plan, no funds, trial used)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CPError(Exception):
    def __init__(self, status: int | None, detail: str):
        super().__init__(f"cp {status}: {detail}")
        self.status = status
        self.detail = detail

    @property
    def definitive(self) -> bool:
        """CP rejected the request before applying it; safe to release money."""
        return self.status is not None and 400 <= self.status < 500 and self.status not in (401, 403, 408, 429)


# --- settings -----------------------------------------------------------------


def _catalog(items: Any, *, noun: str, allow_empty: bool) -> list[dict[str, Any]]:
    if not isinstance(items, list) or (not items and not allow_empty):
        raise ValueError(f"at least one {noun} is required")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in items:
        if not isinstance(p, dict):
            raise ValueError(f"invalid {noun}")
        code = str(p.get("code", "")).strip().lower()
        if not code or not code.replace("_", "").isalnum() or len(code) > 32:
            raise ValueError(f"invalid {noun} code: {code!r}")
        if code == "trial":
            raise ValueError(f"{noun} code 'trial' is reserved")
        if code in seen:
            raise ValueError(f"duplicate {noun} code: {code}")
        seen.add(code)
        days = int(p.get("days", 0))
        if not 1 <= days <= 365:
            raise ValueError(f"{noun} {code}: days must be 1..365")
        price = money(p.get("price_rub", 0))
        if price <= 0:
            raise ValueError(f"{noun} {code}: price must be > 0")
        title = str(p.get("title") or code).strip()[:64]
        out.append({"code": code, "title": title, "days": days, "price_rub": str(price)})
    return out


def validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("settings must be an object")
    plans = _catalog(raw.get("plans"), noun="plan", allow_empty=False)
    if "device_addons" not in raw:
        addons_in: Any = DEFAULT_SETTINGS["device_addons"]
    else:
        addons_in = raw.get("device_addons") or []
    device_addons = _catalog(addons_in, noun="device addon", allow_empty=True)

    trial_in = raw.get("trial") or {}
    trial_days = int(trial_in.get("days", 1))
    if not 1 <= trial_days <= 30:
        raise ValueError("trial days must be 1..30")
    # *_min_deposits are the pre-exchange-gate keys; still read so saved settings keep working.
    trial_min = int(trial_in.get("min_exchanges", trial_in.get("min_deposits", 0)))
    purchase_min = int(raw.get("purchase_min_exchanges", raw.get("purchase_min_deposits", 0)))
    if "purchase_min_invited" not in raw:
        invited_min = int(DEFAULT_SETTINGS["purchase_min_invited"])
    else:
        invited_min = int(raw.get("purchase_min_invited") or 0)
    if trial_min < 0 or purchase_min < 0 or invited_min < 0:
        raise ValueError("min_exchanges must be >= 0")
    app_url = str(raw.get("app_url") or "").strip()
    if app_url and not app_url.startswith(("https://", "http://")):
        raise ValueError("app_url must be an http(s) link")
    return {
        "plans": plans,
        "device_addons": device_addons,
        "trial": {"enabled": bool(trial_in.get("enabled", False)), "days": trial_days, "min_exchanges": trial_min},
        "purchase_min_exchanges": purchase_min,
        "purchase_min_invited": invited_min,
        "app_url": app_url[:500],
        "review_bonus_text_rub": _review_bonus_rub(raw, "review_bonus_text_rub", 25),
        "review_bonus_photo_rub": _review_bonus_rub(raw, "review_bonus_photo_rub", 50),
    }


def _review_bonus_rub(raw: dict[str, Any], key: str, default: int) -> int:
    """Whole rubles. A missing key keeps the default so older saved settings still load."""
    if key not in raw or raw.get(key) in (None, ""):
        return default
    try:
        val = int(raw[key])
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a whole number of rubles") from None
    if isinstance(raw[key], float) and not float(raw[key]).is_integer():
        raise ValueError(f"{key} must be a whole number of rubles")
    if not 1 <= val <= 100_000:
        raise ValueError(f"{key} must be 1..100000")
    return val


async def load_settings(conn) -> dict[str, Any]:
    row = await conn.fetchrow("SELECT value FROM app_settings WHERE key = $1", SETTINGS_KEY)
    if not row:
        return validate_settings(DEFAULT_SETTINGS)
    val = row["value"]
    raw = json.loads(val) if isinstance(val, str) else dict(val)
    try:
        return validate_settings(raw)
    except ValueError:
        logger.exception("vpn_billing settings invalid in DB; using defaults")
        return validate_settings(DEFAULT_SETTINGS)


async def save_settings(conn, raw: dict[str, Any]) -> dict[str, Any]:
    clean = validate_settings(raw)
    await conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ($1, $2::jsonb, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        SETTINGS_KEY,
        json.dumps(clean),
    )
    return clean


def find_plan(cfg: dict[str, Any], code: str) -> dict[str, Any] | None:
    code = (code or "").strip().lower()
    return next((p for p in cfg["plans"] if p["code"] == code), None)


def find_addon(cfg: dict[str, Any], code: str) -> dict[str, Any] | None:
    code = (code or "").strip().lower()
    return next((p for p in cfg.get("device_addons") or [] if p["code"] == code), None)


def _paid_kind(kind: str) -> bool:
    """Subscription purchases and extra-device seats both spend the balance."""
    return kind in ("paid", "device")


# --- gate ---------------------------------------------------------------------


def _allowlist() -> set[int]:
    out: set[int] = set()
    raw = os.environ.get("VPN_GATE_ALLOWLIST") or os.environ.get("VPN_DEPOSIT_GATE_ALLOWLIST", "")
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def parse_trusted_ids(raw: Any) -> list[int]:
    """JSON array of Telegram ids. Duplicates collapse; order is sorted."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        raise ValueError("trusted ids must be a list")
    seen: set[int] = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError("trusted id must be a telegram id")
        seen.add(item)
    return sorted(seen)


async def load_trusted_ids(conn) -> set[int]:
    row = await conn.fetchrow("SELECT value FROM app_settings WHERE key = $1", TRUSTED_KEY)
    if not row or row["value"] in (None, ""):
        return set()
    val = row["value"]
    try:
        return set(parse_trusted_ids(val))
    except (TypeError, ValueError):
        logger.exception("vpn_trusted_ids invalid in DB; treating as empty")
        return set()


async def set_trusted(conn, telegram_id: int, trusted: bool) -> dict[str, Any]:
    """Mark or clear one account. Repeating the same flag does not change the list."""
    telegram_id = int(telegram_id)
    if telegram_id <= 0 or not isinstance(trusted, bool):
        raise ValueError("telegram_id and trusted flag required")
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", TRUSTED_KEY)
        ids = await load_trusted_ids(conn)
        if trusted:
            ids.add(telegram_id)
        else:
            ids.discard(telegram_id)
        stored = sorted(ids)
        await conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            TRUSTED_KEY,
            json.dumps(stored),
        )
    return {"telegram_id": telegram_id, "trusted": telegram_id in stored}


async def exchange_count(conn, telegram_id: int) -> int:
    """Completed FocusPay exchanges (same count as the cashback tiers)."""
    from cashback_tier import count_completed_exchanges

    return await count_completed_exchanges(conn, telegram_id)


async def _require_purchase_gate(conn, cfg: dict[str, Any], telegram_id: int) -> None:
    have = await exchange_count(conn, telegram_id)
    invited = await invited_count(conn, telegram_id)
    need = int(cfg["purchase_min_exchanges"])
    need_invited = int(cfg["purchase_min_invited"])
    trusted_ids = await load_trusted_ids(conn)
    if not purchase_allowed(have, invited, telegram_id, need, need_invited, trusted_ids):
        raise GateError(need, have, need_invited, invited)


async def invited_count(conn, telegram_id: int) -> int:
    """People this Telegram account invited (user referral attributions)."""
    return int(
        await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM user_referral_attributions
            WHERE referrer_user_id = $1
            """,
            int(telegram_id),
        )
        or 0
    )


def gate_ok(count: int, telegram_id: int, need: int, trusted_ids: set[int] | None = None) -> bool:
    return (
        need <= 0
        or count >= need
        or telegram_id in _allowlist()
        or telegram_id in (trusted_ids or ())
    )


def purchase_allowed(
    exchanges: int,
    invited: int,
    telegram_id: int,
    need_exchanges: int,
    need_invited: int,
    trusted_ids: set[int] | None = None,
) -> bool:
    """Buy after enough exchanges, enough invites, or a trusted-account flag."""
    if telegram_id in _allowlist() or telegram_id in (trusted_ids or ()) or need_exchanges <= 0:
        return True
    if exchanges >= need_exchanges:
        return True
    return need_invited > 0 and invited >= need_invited


async def lock_user(conn, telegram_id: int) -> None:
    # asyncpg takes the type from $1::text and then rejects an int. Bind text.
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('vpn_billing:' || $1))",
        str(int(telegram_id)),
    )


# --- control plane client -----------------------------------------------------


def _cp_conf() -> tuple[str, str]:
    from config import settings

    base = (settings.focusvpn_api_base or "http://127.0.0.1:18080").rstrip("/")
    return base, settings.focusvpn_internal_token or ""


async def cp_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Call CP. Returns parsed JSON, None on 404, raises CPError otherwise."""
    base, token = _cp_conf()
    if not token:
        raise CPError(None, "FOCUSVPN_INTERNAL_TOKEN is not set")
    timeout = aiohttp.ClientTimeout(total=CP_TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, f"{base}{path}", json=body, headers={"X-Internal-Token": token}
            ) as resp:
                text = await resp.text()
                if resp.status == 404:
                    return None
                if resp.status >= 400:
                    raise CPError(resp.status, text[:300])
                return json.loads(text) if text else {}
    except CPError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise CPError(None, type(exc).__name__) from exc


async def cp_grant(row: dict[str, Any]) -> dict[str, Any]:
    out = await cp_request(
        "POST",
        "/v1/internal/billing/grant",
        {
            "external_id": str(row["id"]),
            "telegram_id": int(row["telegram_id"]),
            "kind": row["kind"],
            "plan_code": row["plan_code"],
            "days": int(row["days"]),
            "amount_rub": str(money(row["price_rub"])),
        },
    )
    if out is None:
        raise CPError(404, "grant endpoint not found")
    return out


async def cp_get_grant(purchase_id: str) -> dict[str, Any] | None:
    return await cp_request("GET", f"/v1/internal/billing/grants/{purchase_id}")


async def cp_status(telegram_id: int) -> dict[str, Any] | None:
    try:
        return await cp_request("GET", f"/v1/internal/billing/status?telegram_id={int(telegram_id)}")
    except CPError:
        return None


# --- saga ---------------------------------------------------------------------


@dataclass
class Outcome:
    purchase_id: str
    status: str  # paid | pending | released | failed
    kind: str
    plan_code: str
    days: int
    price_rub: Decimal
    ends_at: str | None = None
    error: str | None = None
    replay: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "purchase_id": self.purchase_id,
            "status": self.status,
            "kind": self.kind,
            "plan_code": self.plan_code,
            "days": self.days,
            "price_rub": float(self.price_rub),
            "ends_at": self.ends_at,
            "error": self.error,
            "replay": self.replay,
        }


def _outcome(row, *, replay: bool = False) -> Outcome:
    status = row["status"]
    public = {"held": "pending", "granted": "pending"}.get(status, status)
    ends = row["cp_ends_at"]
    return Outcome(
        purchase_id=str(row["id"]),
        status=public,
        kind=row["kind"],
        plan_code=row["plan_code"],
        days=int(row["days"]),
        price_rub=money(row["price_rub"]),
        ends_at=ends.isoformat() if hasattr(ends, "isoformat") else ends,
        error=row["error"],
        replay=replay,
    )


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value)).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


_ROW = "id, telegram_id, kind, plan_code, days, price_rub, status, order_ref, cp_ends_at, error"


async def _get_by_idem(conn, idem_key: str):
    return await conn.fetchrow(f"SELECT {_ROW} FROM vpn_purchases WHERE idem_key = $1", idem_key)


async def start_purchase(conn, *, telegram_id: int, plan_code: str, idem_key: str):
    """Step 1 in one DB transaction. Returns (row, replayed)."""
    async with conn.transaction():
        await lock_user(conn, telegram_id)
        prior = await _get_by_idem(conn, idem_key)
        if prior:
            return prior, True
        cfg = await load_settings(conn)
        plan = find_plan(cfg, plan_code)
        if plan is None:
            raise BillingError("unknown_plan", f"unknown plan {plan_code!r}")
        await _require_purchase_gate(conn, cfg, telegram_id)
        pid = uuid.uuid4()
        order_ref = f"vpn-{pid}"
        price = money(plan["price_rub"])
        row = await conn.fetchrow(
            f"""
            INSERT INTO vpn_purchases (id, telegram_id, kind, plan_code, days, price_rub, status, idem_key, order_ref)
            VALUES ($1, $2, 'paid', $3, $4, $5, 'held', $6, $7)
            RETURNING {_ROW}
            """,
            pid, telegram_id, plan["code"], int(plan["days"]), price, idem_key, order_ref,
        )
        try:
            await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=price)
        except ValueError as exc:
            raise BillingError("insufficient_funds", "insufficient balance") from exc
        return row, False


async def start_device_purchase(conn, *, telegram_id: int, plan_code: str, idem_key: str):
    """Hold the balance for one extra device seat. Does not check the subscription."""
    async with conn.transaction():
        await lock_user(conn, telegram_id)
        prior = await _get_by_idem(conn, idem_key)
        if prior:
            return prior, True
        cfg = await load_settings(conn)
        addon = find_addon(cfg, plan_code)
        if addon is None:
            raise BillingError("unknown_plan", f"unknown device addon {plan_code!r}")
        await _require_purchase_gate(conn, cfg, telegram_id)
        pid = uuid.uuid4()
        order_ref = f"vpn-{pid}"
        price = money(addon["price_rub"])
        row = await conn.fetchrow(
            f"""
            INSERT INTO vpn_purchases (id, telegram_id, kind, plan_code, days, price_rub, status, idem_key, order_ref)
            VALUES ($1, $2, 'device', $3, $4, $5, 'held', $6, $7)
            RETURNING {_ROW}
            """,
            pid, telegram_id, addon["code"], int(addon["days"]), price, idem_key, order_ref,
        )
        try:
            await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=price)
        except ValueError as exc:
            raise BillingError("insufficient_funds", "insufficient balance") from exc
        return row, False


async def start_trial(conn, *, telegram_id: int, idem_key: str):
    async with conn.transaction():
        await lock_user(conn, telegram_id)
        prior = await _get_by_idem(conn, idem_key)
        if prior:
            return prior, True
        cfg = await load_settings(conn)
        trial = cfg["trial"]
        if not trial["enabled"]:
            raise BillingError("trial_disabled", "trial is disabled")
        used = await conn.fetchval(
            """
            SELECT 1 FROM vpn_purchases
            WHERE telegram_id = $1 AND kind = 'trial' AND status IN ('held', 'granted', 'paid')
            """,
            telegram_id,
        )
        if used:
            raise BillingError("trial_used", "trial already used")
        dep = await exchange_count(conn, telegram_id)
        need = int(trial["min_exchanges"])
        if not gate_ok(dep, telegram_id, need, await load_trusted_ids(conn)):
            raise GateError(need, dep)
        pid = uuid.uuid4()
        row = await conn.fetchrow(
            f"""
            INSERT INTO vpn_purchases (id, telegram_id, kind, plan_code, days, price_rub, status, idem_key, order_ref)
            VALUES ($1, $2, 'trial', 'trial', $3, 0, 'held', $4, $5)
            RETURNING {_ROW}
            """,
            pid, telegram_id, int(trial["days"]), idem_key, f"vpn-{pid}",
        )
        return row, False


def vpn_ledger_order_id(purchase_id) -> str:
    """Shared idempotency key for cashback and referral rows of one purchase."""
    return f"vpn:{purchase_id}"


def _insert_landed(status: str | None) -> bool:
    """asyncpg returns 'INSERT 0 1' for a new row and 'INSERT 0 0' on conflict."""
    parts = str(status or "").split()
    return len(parts) >= 3 and parts[0] == "INSERT" and parts[-1] == "1"


def vpn_referral_notice_text(*, amount, percent: float, price) -> str:
    paid = f"{price:.2f}".replace(".", ",")
    credited = f"{amount:.2f}".replace(".", ",")
    return (
        "👥 <b>Друг оплатил VPN</b>\n"
        f"На реферальный баланс: <b>{credited} ₽</b> ({percent:g}% от {paid} ₽)."
    )


async def _notify_vpn_referrer(notice: dict) -> None:
    """Best-effort DM from the FocusPay bot. A Telegram failure must not undo the purchase."""
    try:
        from telegram_notify import send_user_message

        await send_user_message(
            int(notice["referrer_id"]),
            vpn_referral_notice_text(
                amount=notice["amount_rub"],
                percent=float(notice["percent"]),
                price=notice["price_rub"],
            ),
        )
    except Exception:
        logger.exception("vpn referral notify failed for %s", notice.get("referrer_id"))


async def accrue_vpn_rewards(conn, row) -> dict | None:
    """Credit the buyer cashback and the referrer their existing ladder share.

    Cashback uses the exchange ladder (base 5%, +2% per 5 completed exchanges, cap 15%).
    The referrer uses the global partner ladder already shown in the cabinet
    (base 5%, +5% per 5 invited people, cap 20%) with no per-person rate.
    Both rows share order_id vpn:{purchase} so a retried confirm cannot double-pay.
    Trial and a zero price accrue nothing. A self-referral accrues cashback only.
    """
    price = money(row["price_rub"])
    if not _paid_kind(row["kind"]) or price <= 0:
        return None
    buyer = int(row["telegram_id"])
    order_id = vpn_ledger_order_id(row["id"])

    from cashback_tier import count_completed_exchanges, percent_for_completed_count

    completed = await count_completed_exchanges(conn, buyer)
    cashback_pct = float(percent_for_completed_count(completed))
    cashback = money(price * Decimal(str(cashback_pct)) / Decimal("100"))
    if cashback > 0:
        await conn.execute(
            """
            INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
            VALUES ($1, 'accrual', $2, $3, $4)
            ON CONFLICT (order_id) DO NOTHING
            """,
            buyer,
            cashback,
            order_id,
            f"Кешбэк {cashback_pct:g}% от VPN {price:.2f} ₽",
        )

    referrer = await conn.fetchval(
        """
        SELECT referrer_user_id FROM user_referral_attributions
        WHERE user_id = $1
        """,
        buyer,
    )
    if referrer is None:
        return None
    referrer_id = int(referrer)
    if referrer_id == buyer:
        return None

    from partner_tier import partner_effective_percent
    import runtime_settings

    invited = await conn.fetchval(
        """
        SELECT COUNT(*)::int FROM user_referral_attributions
        WHERE referrer_user_id = $1
        """,
        referrer_id,
    )
    referral_pct = float(partner_effective_percent(int(invited or 0), **runtime_settings.partner_tier_global()))
    referral = money(price * Decimal(str(referral_pct)) / Decimal("100"))
    if referral <= 0:
        return None
    status = await conn.execute(
        """
        INSERT INTO user_referral_ledger (
            referrer_user_id, type, amount_rub, order_id, note
        )
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        """,
        referrer_id,
        referral,
        order_id,
        f"{referral_pct:g}% от VPN {price:.2f} ₽, покупка {row['id']}",
    )
    if not _insert_landed(status):
        return None
    return {
        "referrer_id": referrer_id,
        "amount_rub": referral,
        "percent": referral_pct,
        "price_rub": price,
    }


async def _lock_row(conn, purchase_id):
    return await conn.fetchrow(f"SELECT {_ROW} FROM vpn_purchases WHERE id = $1 FOR UPDATE", purchase_id)


async def finalize_granted(conn, purchase_id, ends_at: datetime | None):
    """Step 3: CP has the days; turn the hold into a spend."""
    notice = None
    async with conn.transaction():
        row = await _lock_row(conn, purchase_id)
        if row is None or row["status"] not in ("held", "granted"):
            return row
        price = money(row["price_rub"])
        if _paid_kind(row["kind"]) and price > 0:
            note = "vpn_device" if row["kind"] == "device" else "vpn_sub"
            await confirm_unified_hold(
                conn,
                user_id=int(row["telegram_id"]),
                order_ref=row["order_ref"],
                amount_rub=price,
                note=f"{note}:{row['id']}",
            )
            notice = await accrue_vpn_rewards(conn, row)
        row = await conn.fetchrow(
            f"""
            UPDATE vpn_purchases
            SET status = 'paid', paid_at = now(), updated_at = now(), error = NULL,
                cp_ends_at = COALESCE($2::timestamptz, cp_ends_at)
            WHERE id = $1
            RETURNING {_ROW}
            """,
            purchase_id, ends_at,
        )
    if notice:
        try:
            await _notify_vpn_referrer(notice)
        except Exception:
            logger.exception("vpn referral notify failed for %s", notice.get("referrer_id"))
    return row


async def _mark_granted(conn, purchase_id, ends_at: datetime | None) -> None:
    await conn.execute(
        """
        UPDATE vpn_purchases SET status = 'granted', cp_ends_at = $2::timestamptz, updated_at = now()
        WHERE id = $1 AND status = 'held'
        """,
        purchase_id, ends_at,
    )


async def refuse(conn, purchase_id, error: str):
    """CP definitively refused: return money (paid) or mark trial failed."""
    async with conn.transaction():
        row = await _lock_row(conn, purchase_id)
        if row is None or row["status"] != "held":
            return row
        price = money(row["price_rub"])
        if _paid_kind(row["kind"]) and price > 0:
            note = "vpn_device_release" if row["kind"] == "device" else "vpn_release"
            await release_unified_hold(
                conn,
                user_id=int(row["telegram_id"]),
                order_ref=row["order_ref"],
                amount_rub=price,
                note=f"{note}:{row['id']}",
            )
        status = "released" if _paid_kind(row["kind"]) else "failed"
        return await conn.fetchrow(
            f"""
            UPDATE vpn_purchases SET status = $2, error = $3, updated_at = now()
            WHERE id = $1 RETURNING {_ROW}
            """,
            purchase_id, status, error[:500],
        )


async def _note_attempt(conn, purchase_id, error: str) -> None:
    await conn.execute(
        "UPDATE vpn_purchases SET attempts = attempts + 1, error = $2, updated_at = now() WHERE id = $1",
        purchase_id, error[:500],
    )


async def drive(conn, row) -> Outcome:
    """Steps 2-3 for a held/granted row. Safe to repeat (CP grant is idempotent)."""
    pid = row["id"]
    if row["status"] == "held":
        try:
            res = await cp_grant(row)
        except CPError as exc:
            if exc.definitive:
                row = await refuse(conn, pid, exc.detail)
            else:
                await _note_attempt(conn, pid, str(exc))
                row = await conn.fetchrow(f"SELECT {_ROW} FROM vpn_purchases WHERE id = $1", pid)
            return _outcome(row)
        ends_at = _ts(res.get("ends_at"))
        await _mark_granted(conn, pid, ends_at)
    else:
        ends_at = None
    try:
        row = await finalize_granted(conn, pid, ends_at)
    except Exception as exc:
        logger.exception("vpn confirm failed for %s", pid)
        await _note_attempt(conn, pid, f"confirm: {type(exc).__name__}")
        row = await conn.fetchrow(f"SELECT {_ROW} FROM vpn_purchases WHERE id = $1", pid)
    return _outcome(row)


async def purchase(conn, *, telegram_id: int, plan_code: str, idem_key: str) -> Outcome:
    row, replay = await start_purchase(conn, telegram_id=telegram_id, plan_code=plan_code, idem_key=idem_key)
    if replay and row["status"] not in ("held", "granted"):
        return _outcome(row, replay=True)
    out = await drive(conn, row)
    out.replay = replay
    return out


async def purchase_device(conn, *, telegram_id: int, plan_code: str, idem_key: str) -> Outcome:
    """Buy one extra device seat. A repeat of idem_key does not charge again.

    The seat's clock starts at grant time and does not move the subscription end.
    No live subscription means the money is never held.
    """
    prior = await _get_by_idem(conn, idem_key)
    if prior is None:
        cp = await cp_status(telegram_id)
        if not cp or not cp.get("has_live"):
            raise BillingError("subscription_required", "live subscription required")
    row, replay = await start_device_purchase(conn, telegram_id=telegram_id, plan_code=plan_code, idem_key=idem_key)
    if replay and row["status"] not in ("held", "granted"):
        return _outcome(row, replay=True)
    out = await drive(conn, row)
    out.replay = replay
    return out


async def trial(conn, *, telegram_id: int, idem_key: str) -> Outcome:
    row, replay = await start_trial(conn, telegram_id=telegram_id, idem_key=idem_key)
    if replay and row["status"] not in ("held", "granted"):
        return _outcome(row, replay=True)
    out = await drive(conn, row)
    out.replay = replay
    return out


async def reconcile_once(conn, *, older_than_sec: int = RECONCILE_AFTER_SEC, limit: int = 50) -> int:
    rows = await conn.fetch(
        f"""
        SELECT {_ROW} FROM vpn_purchases
        WHERE status IN ('held', 'granted') AND updated_at < now() - ($1::int * interval '1 second')
        ORDER BY updated_at LIMIT $2
        """,
        older_than_sec, limit,
    )
    done = 0
    for row in rows:
        out = await drive(conn, row)
        if out.status != "pending":
            done += 1
            logger.info("vpn reconcile %s -> %s", out.purchase_id, out.status)
    return done


async def reconcile_loop() -> None:
    from db import get_pool

    await asyncio.sleep(30)
    while True:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await reconcile_once(conn)
        except Exception:
            logger.exception("vpn reconcile tick failed")
        await asyncio.sleep(RECONCILE_INTERVAL_SEC)


def plan_cards(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plans with price per day and discount against the most expensive day rate."""
    rates = [money(p["price_rub"]) / int(p["days"]) for p in plans]
    top = max(rates) if rates else Decimal(0)
    out = []
    for p, rate in zip(plans, rates):
        discount = int(((top - rate) / top * 100).quantize(Decimal(1))) if top > 0 else 0
        out.append({
            **p,
            "price_rub": float(money(p["price_rub"])),
            "per_day_rub": float(rate.quantize(Decimal("0.01"))),
            "discount_pct": discount,
        })
    return out


async def trial_used(conn, telegram_id: int) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1 FROM vpn_purchases
            WHERE telegram_id = $1 AND kind = 'trial' AND status IN ('held', 'granted', 'paid')
            """,
            telegram_id,
        )
    )


async def user_status(conn, telegram_id: int) -> dict[str, Any]:
    from user_unified_balance import unified_available

    cfg = await load_settings(conn)
    have = await exchange_count(conn, telegram_id)
    invited = await invited_count(conn, telegram_id)
    avail = money(await unified_available(conn, telegram_id))
    used = await trial_used(conn, telegram_id)
    purchase_need = int(cfg["purchase_min_exchanges"])
    invited_need = int(cfg["purchase_min_invited"])
    trial_need = int(cfg["trial"]["min_exchanges"])
    trusted_ids = await load_trusted_ids(conn)
    trusted = telegram_id in trusted_ids
    purchase_open = purchase_allowed(have, invited, telegram_id, purchase_need, invited_need, trusted_ids)
    return {
        "telegram_id": telegram_id,
        "available_rub": float(avail),
        "exchanges": {"have": have, "need": purchase_need},
        "invited": {"have": invited, "need": invited_need},
        "purchase_open": purchase_open,
        "trusted": trusted,
        "trial": {
            "enabled": cfg["trial"]["enabled"],
            "days": cfg["trial"]["days"],
            "min_exchanges": trial_need,
            "used": used,
        },
        "trial_available": cfg["trial"]["enabled"] and not used and gate_ok(have, telegram_id, trial_need, trusted_ids),
        "plans": plan_cards(cfg["plans"]),
        "device_addons": plan_cards(cfg["device_addons"]),
        "app_url": cfg["app_url"],
    }


def public_progress(status: dict[str, Any]) -> dict[str, Any]:
    """Buyer card for the exchange Mini App. Counts stay the ones user_status already computed."""
    plans = []
    for plan in status.get("plans") or []:
        if not isinstance(plan, dict):
            continue
        plans.append({"title": plan.get("title"), "price_rub": plan.get("price_rub")})
    return {
        "exchanges": status.get("exchanges") or {"have": 0, "need": 0},
        "invited": status.get("invited") or {"have": 0, "need": 0},
        "purchase_open": bool(status.get("purchase_open")),
        "trusted": bool(status.get("trusted")),
        "trial_available": bool(status.get("trial_available")),
        "plans": plans,
    }


def devices_limit_view(cp: dict[str, Any] | None) -> dict[str, Any]:
    """CP status -> seats the bot can show. Slots stay listed after the subscription ends."""
    if not cp:
        return {"max_devices": 0, "base_devices": 0, "extra_slots": []}
    slots = []
    for slot in cp.get("extra_slots") or []:
        if not isinstance(slot, dict):
            continue
        slots.append({"plan_code": slot.get("plan_code"), "ends_at": slot.get("ends_at")})
    return {
        "max_devices": int(cp.get("max_devices") or 0),
        "base_devices": int(cp.get("base_devices") or 0),
        "extra_slots": slots,
    }


def subscription_view(cp: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """CP status -> what the bot shows. days_left rounds up (5.2 days -> 6)."""
    from datetime import timezone

    now = now or datetime.now(timezone.utc)
    if not cp or not cp.get("has_live"):
        return {"active": False, "plan": None, "status": None, "ends_at": None, "days_left": 0}
    ends = _ts(cp.get("ends_at"))
    left = 0
    if ends:
        secs = (ends - now).total_seconds()
        left = max(0, int(-(-secs // 86400)))
    return {
        "active": bool(ends and ends > now),
        "plan": cp.get("plan_code"),
        "status": cp.get("status"),
        "ends_at": ends.isoformat() if ends else None,
        "days_left": left,
    }


# --- reminders ----------------------------------------------------------------

# "soon" fires within 6 h of the end (a 1-day trial must not warn right after start);
# "ended" covers the day after the end.
REMIND_SOON_SEC = 6 * 3600
REMIND_ENDED_SEC = 24 * 3600


def reminder_kind(ends_at: datetime, now: datetime) -> str:
    return "ended" if ends_at <= now else "soon"


async def due_reminders(conn, now: datetime | None = None) -> list[dict[str, Any]]:
    """Subscriptions ending within 6 h (or ended within a day) not yet reminded."""
    from datetime import timedelta, timezone

    now = now or datetime.now(timezone.utc)
    frm = (now - timedelta(seconds=REMIND_ENDED_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = (now + timedelta(seconds=REMIND_SOON_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = await cp_request("GET", f"/v1/internal/billing/ending?from={frm}&to={to}")
    out: list[dict[str, Any]] = []
    for sub in (res or {}).get("subscriptions") or []:
        ends = _ts(sub.get("ends_at"))
        tg = int(sub.get("telegram_id") or 0)
        if not ends or tg <= 0:
            continue
        kind = reminder_kind(ends, now)
        sent = await conn.fetchval(
            "SELECT 1 FROM vpn_notifications WHERE telegram_id = $1 AND kind = $2 AND ends_at = $3",
            tg, kind, ends,
        )
        if sent:
            continue
        out.append({
            "telegram_id": tg,
            "kind": kind,
            "plan_code": sub.get("plan_code"),
            "status": sub.get("status"),
            "ends_at": ends.isoformat(),
        })
    return out


async def mark_reminded(conn, telegram_id: int, kind: str, ends_at: datetime) -> bool:
    """Record a sent reminder. False if it was already recorded (another sender won)."""
    if kind not in ("soon", "ended"):
        raise ValueError("kind must be soon|ended")
    row = await conn.fetchrow(
        """
        INSERT INTO vpn_notifications (telegram_id, kind, ends_at) VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING RETURNING telegram_id
        """,
        telegram_id, kind, ends_at,
    )
    return row is not None

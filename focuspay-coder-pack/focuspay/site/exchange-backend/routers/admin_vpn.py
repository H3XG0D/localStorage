"""Admin VPN: report, tariffs/trial settings, purchases, reconciliation with the CP."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import vpn_billing
from auth import get_current_admin
from casino_finance import money
from db import get_pool

router = APIRouter()

RECON_WINDOW_DAYS = 30
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,32}")


def user_query(raw: str) -> tuple[str, str]:
    """Split a search box into a Telegram id or a username without @."""
    text = (raw or "").strip()
    if text.startswith("@"):
        text = text[1:].strip()
    if not text or len(text) > 64:
        raise ValueError("Введите Telegram ID или @username")
    if text.isdigit():
        if int(text) <= 0:
            raise ValueError("Введите Telegram ID или @username")
        return "id", text
    if not _USERNAME.fullmatch(text):
        raise ValueError("Введите Telegram ID или @username")
    return "username", text


async def resolve_telegram_user(conn, raw: str) -> dict[str, Any]:
    """Find a FocusPay Telegram account by id or username."""
    kind, value = user_query(raw)
    if kind == "id":
        row = await conn.fetchrow(
            "SELECT user_id, username, first_name FROM bot_users WHERE user_id = $1",
            int(value),
        )
        return {
            "telegram_id": int(value),
            "username": row["username"] if row else None,
            "first_name": row["first_name"] if row else None,
        }
    rows = await conn.fetch(
        """
        SELECT user_id, username, first_name FROM bot_users
        WHERE LOWER(username) = LOWER($1)
        LIMIT 2
        """,
        value,
    )
    if not rows:
        raise LookupError("missing")
    if len(rows) > 1:
        raise LookupError("ambiguous")
    row = rows[0]
    return {
        "telegram_id": int(row["user_id"]),
        "username": row["username"],
        "first_name": row["first_name"],
    }


async def _cp_or_502(path: str) -> dict[str, Any]:
    try:
        out = await vpn_billing.cp_request("GET", path)
    except vpn_billing.CPError as exc:
        raise HTTPException(status_code=502, detail=f"vpn control plane: {exc.detail}") from exc
    if out is None:
        raise HTTPException(status_code=502, detail="vpn control plane: not found")
    return out


async def _sales(conn) -> dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT kind, plan_code,
               COUNT(*) FILTER (WHERE paid_at > now() - interval '1 day')::int AS n_1d,
               COUNT(*) FILTER (WHERE paid_at > now() - interval '7 days')::int AS n_7d,
               COUNT(*) FILTER (WHERE paid_at > now() - interval '30 days')::int AS n_30d,
               COALESCE(SUM(price_rub) FILTER (WHERE paid_at > now() - interval '1 day'), 0) AS rub_1d,
               COALESCE(SUM(price_rub) FILTER (WHERE paid_at > now() - interval '7 days'), 0) AS rub_7d,
               COALESCE(SUM(price_rub) FILTER (WHERE paid_at > now() - interval '30 days'), 0) AS rub_30d
        FROM vpn_purchases
        WHERE status = 'paid' AND kind IN ('paid', 'device') AND paid_at > now() - interval '30 days'
        GROUP BY kind, plan_code ORDER BY kind, plan_code
        """
    )
    by_plan = [
        {
            "kind": r["kind"],
            "plan_code": r["plan_code"],
            "count_1d": r["n_1d"], "count_7d": r["n_7d"], "count_30d": r["n_30d"],
            "revenue_rub_1d": float(money(r["rub_1d"])),
            "revenue_rub_7d": float(money(r["rub_7d"])),
            "revenue_rub_30d": float(money(r["rub_30d"])),
        }
        for r in rows
    ]
    totals = {
        k: round(sum(p[k] for p in by_plan), 2)
        for k in ("revenue_rub_1d", "revenue_rub_7d", "revenue_rub_30d", "count_1d", "count_7d", "count_30d")
    }
    trials = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE status = 'paid' AND created_at > now() - interval '30 days')::int AS trials_30d,
          COUNT(*) FILTER (WHERE status = 'paid')::int AS trials_all
        FROM vpn_purchases WHERE kind = 'trial'
        """
    )
    converted = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT t.telegram_id)::int
        FROM vpn_purchases t
        JOIN vpn_purchases p ON p.telegram_id = t.telegram_id
             AND p.kind = 'paid' AND p.status = 'paid' AND p.paid_at > t.created_at
        WHERE t.kind = 'trial' AND t.status = 'paid'
        """
    )
    held = await conn.fetchrow(
        """
        SELECT COUNT(*)::int AS n, COALESCE(SUM(price_rub), 0) AS rub
        FROM vpn_purchases WHERE status IN ('held', 'granted')
        """
    )
    trials_all = int(trials["trials_all"] or 0)
    daily = await _daily(conn)
    return {
        "daily": daily,
        "by_plan": by_plan,
        "totals": totals,
        "trials_30d": int(trials["trials_30d"] or 0),
        "trials_all": trials_all,
        "trial_converted": int(converted or 0),
        "trial_conversion_pct": round(100.0 * int(converted or 0) / trials_all, 1) if trials_all else 0.0,
        "open_count": int(held["n"] or 0),
        "open_rub": float(money(held["rub"])),
    }


async def _daily(conn, days: int = 30) -> list[dict[str, Any]]:
    """One point per UTC day, oldest first, zeros included (chart needs a full axis)."""
    rows = await conn.fetch(
        """
        SELECT d::date AS day,
               COALESCE(SUM(p.price_rub) FILTER (WHERE p.kind IN ('paid', 'device')), 0) AS rub,
               COUNT(p.id) FILTER (WHERE p.kind IN ('paid', 'device'))::int AS purchases,
               COUNT(p.id) FILTER (WHERE p.kind = 'trial')::int AS trials
        FROM generate_series((now() AT TIME ZONE 'UTC')::date - ($1::int - 1), (now() AT TIME ZONE 'UTC')::date, interval '1 day') AS d
        LEFT JOIN vpn_purchases p
               ON p.status = 'paid' AND (p.paid_at AT TIME ZONE 'UTC')::date = d::date
        GROUP BY d ORDER BY d
        """,
        days,
    )
    return [
        {"date": r["day"].isoformat(), "revenue_rub": float(money(r["rub"])), "purchases": r["purchases"], "trials": r["trials"]}
        for r in rows
    ]


@router.get("/vpn/summary")
async def vpn_summary(_admin=Depends(get_current_admin)):
    report: dict[str, Any]
    try:
        report = await _cp_or_502("/v1/internal/reports/summary")
        report["cp_error"] = None
    except HTTPException as exc:
        report = {"cp_error": exc.detail}
    pool = await get_pool()
    async with pool.acquire() as conn:
        report["sales"] = await _sales(conn)
    report["wallet_spend_rub_30d"] = report["sales"]["totals"]["revenue_rub_30d"]
    return report


@router.get("/vpn/settings")
async def vpn_settings_get(_admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {"settings": await vpn_billing.load_settings(conn)}


@router.put("/vpn/settings")
async def vpn_settings_put(payload: dict[str, Any] = Body(...), _admin=Depends(get_current_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            clean = await vpn_billing.save_settings(conn, payload.get("settings", payload))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"settings": clean}


@router.get("/vpn/purchases")
async def vpn_purchases(
    status: str | None = Query(None, pattern="^(held|granted|paid|released|failed)$"),
    kind: str | None = Query(None, pattern="^(paid|trial|device)$"),
    telegram_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin=Depends(get_current_admin),
):
    where, args = [], []
    for col, val in (("status", status), ("kind", kind), ("telegram_id", telegram_id)):
        if val is not None:
            args.append(val)
            where.append(f"{col} = ${len(args)}")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*)::int FROM vpn_purchases {clause}", *args)
        rows = await conn.fetch(
            f"""
            SELECT id, telegram_id, kind, plan_code, days, price_rub, status, cp_ends_at, error,
                   attempts, created_at, updated_at, paid_at
            FROM vpn_purchases {clause}
            ORDER BY created_at DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
            """,
            *args, limit, offset,
        )
    items = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["price_rub"] = float(money(d["price_rub"]))
        for k in ("cp_ends_at", "created_at", "updated_at", "paid_at"):
            d[k] = d[k].isoformat() if d[k] else None
        items.append(d)
    return {"total": int(total or 0), "items": items}


def reconcile_rows(fp_rows: list[dict[str, Any]], cp_grants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Diff FocusPay purchases against CP grants. Pure for tests."""
    cp = {g["external_id"]: g for g in cp_grants}
    fp = {str(r["id"]): r for r in fp_rows}
    issues: list[dict[str, Any]] = []
    for pid, r in fp.items():
        g = cp.get(pid)
        if r["status"] == "paid" and g is None:
            issues.append({"purchase_id": pid, "issue": "paid_without_grant", "telegram_id": r["telegram_id"]})
        elif r["status"] in ("released", "failed") and g is not None:
            issues.append({"purchase_id": pid, "issue": "grant_without_payment", "telegram_id": r["telegram_id"]})
        elif g is not None:
            want = int(money(r["price_rub"]) * 100) if r["kind"] in ("paid", "device") else 0
            if int(g.get("amount_kopecks") or 0) != want or int(g.get("days") or 0) != int(r["days"]):
                issues.append({"purchase_id": pid, "issue": "amount_or_days_mismatch", "telegram_id": r["telegram_id"],
                               "fp_kopecks": want, "cp_kopecks": g.get("amount_kopecks"),
                               "fp_days": r["days"], "cp_days": g.get("days")})
            elif r["status"] in ("held", "granted"):
                issues.append({"purchase_id": pid, "issue": "granted_not_confirmed", "telegram_id": r["telegram_id"]})
        elif r["status"] in ("held", "granted"):
            issues.append({"purchase_id": pid, "issue": "pending", "telegram_id": r["telegram_id"]})
    for pid, g in cp.items():
        if pid not in fp:
            issues.append({"purchase_id": pid, "issue": "grant_unknown_to_focuspay",
                           "telegram_id": g.get("telegram_id"), "created_at": g.get("created_at")})
    return issues


@router.get("/vpn/reconciliation")
async def vpn_reconciliation(_admin=Depends(get_current_admin)):
    since = datetime.now(timezone.utc) - timedelta(days=RECON_WINDOW_DAYS)
    # One extra day so a purchase at the edge of the window still finds its grant.
    # Subtract in Python: `$1 - interval` makes Postgres infer $1 as interval, and
    # `timestamptz >= interval` is a 500 (UndefinedFunctionError).
    lookup_since = since - timedelta(days=1)
    # CP window is wider than FocusPay's so a purchase at the edge always finds its grant;
    # grants older than the FocusPay window are then ignored.
    cp_since = (since - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cp = await _cp_or_502(f"/v1/internal/billing/grants?since={cp_since}&limit=5000")
    grants = cp.get("grants") or []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, telegram_id, kind, days, price_rub, status, created_at
            FROM vpn_purchases WHERE created_at >= $1
            """,
            lookup_since,
        )
    fp_rows = [dict(r) for r in rows]
    fp_since = lookup_since.isoformat()
    issues = [
        i for i in reconcile_rows(fp_rows, grants)
        if i["issue"] != "grant_unknown_to_focuspay" or str(i.get("created_at") or "") >= fp_since[:19]
    ]
    in_window = [r for r in fp_rows if r["created_at"] >= since]
    paid_rub = sum(
        (money(r["price_rub"]) for r in in_window if r["status"] == "paid" and r["kind"] in ("paid", "device")), Decimal("0")
    )
    cp_rub = Decimal(sum(
        int(g.get("amount_kopecks") or 0) for g in grants if str(g.get("created_at") or "") >= since.isoformat()[:19]
    )) / 100
    return {
        "window_days": RECON_WINDOW_DAYS,
        "focuspay_paid_rub": float(money(paid_rub)),
        "cp_granted_rub": float(money(cp_rub)),
        "focuspay_count": len(in_window),
        "issues": issues,
        "ok": not [i for i in issues if i["issue"] != "pending"],
    }


@router.get("/vpn/resolve")
async def vpn_resolve(q: str = Query(..., min_length=1, max_length=64), _admin=Depends(get_current_admin)):
    """Telegram id, or @username, to the account id the rest of the VPN card uses."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await resolve_telegram_user(conn, q)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LookupError as exc:
            if str(exc) == "ambiguous":
                raise HTTPException(status_code=409, detail="Несколько аккаунтов с таким юзернеймом — введите Telegram ID") from exc
            raise HTTPException(status_code=404, detail="Пользователь не найден") from exc


@router.get("/vpn/user/{telegram_id}")
async def vpn_user(telegram_id: int, _admin=Depends(get_current_admin)):
    """Everything about one VPN user: gate, subscription, devices, purchases."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await vpn_billing.user_status(conn, telegram_id)
        profile = await conn.fetchrow(
            "SELECT username, first_name FROM bot_users WHERE user_id = $1",
            telegram_id,
        )
        rows = await conn.fetch(
            """
            SELECT id, kind, plan_code, days, price_rub, status, cp_ends_at, error, created_at, paid_at
            FROM vpn_purchases WHERE telegram_id = $1 ORDER BY created_at DESC LIMIT 50
            """,
            telegram_id,
        )
    cp_error = None
    devices: list[dict[str, Any]] = []
    try:
        sub = vpn_billing.subscription_view(await vpn_billing.cp_status(telegram_id))
        got = await vpn_billing.cp_request("GET", f"/v1/internal/telegram/devices?telegram_id={int(telegram_id)}")
        devices = (got or {}).get("devices") or []
    except vpn_billing.CPError as exc:
        sub, cp_error = vpn_billing.subscription_view(None), exc.detail
    purchases = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["price_rub"] = float(money(d["price_rub"]))
        for k in ("cp_ends_at", "created_at", "paid_at"):
            d[k] = d[k].isoformat() if d[k] else None
        purchases.append(d)
    return {
        **status,
        "username": profile["username"] if profile else None,
        "first_name": profile["first_name"] if profile else None,
        "subscription": sub,
        "devices": devices,
        "purchases": purchases,
        "cp_error": cp_error,
    }


@router.post("/vpn/user/{telegram_id}/trusted")
async def vpn_user_set_trusted(telegram_id: int, payload: dict[str, Any] = Body(...), _admin=Depends(get_current_admin)):
    """Open or close tariff purchase without the exchange and invite counts."""
    trusted = payload.get("trusted")
    if not isinstance(trusted, bool) or telegram_id <= 0:
        raise HTTPException(status_code=400, detail="trusted must be true or false")
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await vpn_billing.set_trusted(conn, telegram_id, trusted)


@router.post("/vpn/user/{telegram_id}/devices/{device_id}/revoke")
async def vpn_user_revoke_device(telegram_id: int, device_id: str, _admin=Depends(get_current_admin)):
    try:
        out = await vpn_billing.cp_request(
            "POST", "/v1/internal/telegram/devices/revoke", {"telegram_id": int(telegram_id), "device_id": device_id}
        )
    except vpn_billing.CPError as exc:
        raise HTTPException(status_code=502, detail=f"vpn control plane: {exc.detail}") from exc
    if out is None:
        raise HTTPException(status_code=404, detail="device not found")
    return {"ok": True}

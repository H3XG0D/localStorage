"""Админка: просмотр security_access_log и снятие IP-бана."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin
from db import get_pool
from ip_blocklist import ban_ip, get_ban, list_bans, unban_ip

logger = logging.getLogger("admin_security")

router = APIRouter()


class BanBody(BaseModel):
    ip: str
    duration_sec: int = Field(3600, ge=60, le=86400 * 7)
    reason: str = "manual_admin"


class UnbanBody(BaseModel):
    ip: Optional[str] = None
    event_id: Optional[str] = None


def _row_out(r) -> dict:
    d = dict(r)
    return {
        "id": d["id"],
        "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        "ip_address": str(d["ip_address"]).split("/")[0] if d.get("ip_address") else None,
        "method": d.get("method"),
        "path": d.get("path"),
        "status_code": d.get("status_code"),
        "latency_ms": d.get("latency_ms"),
        "zone": d.get("zone"),
        "user_id": d.get("user_id"),
        "operator_id": d.get("operator_id"),
        "scope": d.get("scope"),
        "country_code": d.get("country_code"),
        "city": d.get("city"),
        "user_agent": d.get("user_agent"),
        "threat_type": d.get("threat_type"),
        "threat_score": d.get("threat_score"),
        "extra": d.get("extra"),
    }


@router.get("/security/events")
async def list_security_events(
    ip: Optional[str] = Query(None),
    threat_type: Optional[str] = Query(None),
    zone: Optional[str] = Query(None),
    threats_only: bool = Query(False),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin=Depends(get_current_admin),
):
    conditions = ["1=1"]
    params: list = []
    idx = 1

    if ip:
        conditions.append(f"ip_address = ${idx}::inet")
        params.append(ip.strip())
        idx += 1
    if threat_type:
        conditions.append(f"threat_type = ${idx}")
        params.append(threat_type.strip())
        idx += 1
    if zone:
        conditions.append(f"zone = ${idx}")
        params.append(zone.strip())
        idx += 1
    if threats_only:
        conditions.append("threat_type IS NOT NULL")
    if date_from:
        conditions.append(f"created_at::date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"created_at::date <= ${idx}")
        params.append(date_to)
        idx += 1

    where = " AND ".join(conditions)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT * FROM security_access_log
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*)::int FROM security_access_log WHERE {where}",
            *params,
        )
    return {
        "events": [_row_out(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/security/events/stats")
async def security_events_stats(
    hours: int = Query(24, ge=1, le=168),
    _admin=Depends(get_current_admin),
):
    pool = await get_pool()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with pool.acquire() as conn:
        by_threat = await conn.fetch(
            """
            SELECT threat_type, COUNT(*)::int AS cnt
            FROM security_access_log
            WHERE created_at >= $1 AND threat_type IS NOT NULL
            GROUP BY threat_type
            ORDER BY cnt DESC
            """,
            since,
        )
        top_ips = await conn.fetch(
            """
            SELECT host(ip_address)::text AS ip, COUNT(*)::int AS cnt,
                   MAX(threat_type) FILTER (WHERE threat_type IS NOT NULL) AS last_threat
            FROM security_access_log
            WHERE created_at >= $1
            GROUP BY ip_address
            ORDER BY cnt DESC
            LIMIT 20
            """,
            since,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*)::int FROM security_access_log WHERE created_at >= $1",
            since,
        )
        threats = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM security_access_log
            WHERE created_at >= $1 AND threat_type IS NOT NULL
            """,
            since,
        )
    return {
        "since": since.isoformat(),
        "total_requests": total,
        "threat_events": threats,
        "by_threat_type": [
            {"threat_type": r["threat_type"], "count": r["cnt"]} for r in by_threat
        ],
        "top_ips": [
            {
                "ip": r["ip"],
                "count": r["cnt"],
                "last_threat": r["last_threat"],
            }
            for r in top_ips
        ],
    }


async def _ip_from_event(event_id: str) -> str | None:
    eid = (event_id or "").strip()
    if not eid:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT host(ip_address)::text AS ip
            FROM security_access_log
            WHERE id::text = $1
               OR extra->>'request_id' = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            eid,
        )
    if not row or not row["ip"]:
        return None
    return str(row["ip"])


def _unban_result(ip: str, admin: dict) -> dict:
    result = unban_ip(ip)
    logger.warning(
        "security unban ip=%s was_banned=%s by_admin=%s",
        result.get("ip"),
        result.get("was_banned"),
        admin.get("id") or admin.get("username"),
    )
    return result


@router.get("/security/bans")
async def security_list_bans(_admin=Depends(get_current_admin)):
    return {"items": list_bans()}


@router.post("/security/bans")
async def security_ban_ip(body: BanBody, admin=Depends(get_current_admin)):
    ip = (body.ip or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="ip required")
    ban_ip(ip, duration_sec=body.duration_sec, reason=(body.reason or "manual_admin")[:80])
    logger.warning("security ban ip=%s by_admin=%s", ip, admin.get("id") or admin.get("username"))
    info = get_ban(ip) or {"ip": ip, "ttl_sec": body.duration_sec, "reason": body.reason}
    return {"ok": True, **info}


@router.post("/security/unban")
async def security_unban(body: UnbanBody, admin=Depends(get_current_admin)):
    ip = (body.ip or "").strip()
    event_id = (body.event_id or "").strip()
    if not ip and event_id:
        ip = await _ip_from_event(event_id) or ""
        if not ip:
            raise HTTPException(status_code=404, detail="Event not found")
    if not ip:
        raise HTTPException(status_code=400, detail="ip or event_id required")
    return _unban_result(ip, admin)


@router.delete("/security/bans/{ip:path}")
async def security_unban_path(ip: str, admin=Depends(get_current_admin)):
    ip = (ip or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="ip required")
    return _unban_result(ip, admin)

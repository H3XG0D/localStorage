"""Middleware: лог всех /api запросов с IP, гео и детекцией угроз."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from client_ip import get_client_ip
from config import settings
from geoip_lookup import lookup_geo
from security_access_log import (
    insert_access_log,
    parse_auth_header,
    path_to_zone,
)
from security_alerts import send_security_alert
from ip_blocklist import maybe_ban_for_threat
from security_threats import evaluate_threat

logger = logging.getLogger("access_log")

_pending_tasks: set[asyncio.Task] = set()
_MAX_PENDING = 200


def _write_file_log(entry: dict) -> None:
    path = (settings.security_log_file or "").strip()
    if not path:
        return
    try:
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.debug("security file log: %s", e)


async def _process_access(
    *,
    ip: str | None,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    user_agent: str | None,
    authorization: str | None,
    request_id: str | None = None,
) -> None:
    if not ip:
        return
    country, city = lookup_geo(ip)
    scope, user_id, operator_id = parse_auth_header(authorization)
    zone = path_to_zone(path)
    threat_type, threat_score = evaluate_threat(
        ip=ip,
        method=method,
        path=path,
        status_code=status_code,
        zone=zone,
        scope=scope,
        user_agent=user_agent,
    )
    await insert_access_log(
        ip=ip,
        method=method,
        path=path,
        status_code=status_code,
        latency_ms=latency_ms,
        zone=zone,
        user_agent=user_agent,
        scope=scope,
        user_id=user_id,
        operator_id=operator_id,
        country_code=country,
        city=city,
        threat_type=threat_type,
        threat_score=threat_score,
        extra={"request_id": request_id} if request_id else None,
    )
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ip": ip,
        "method": method,
        "path": path,
        "status": status_code,
        "latency_ms": latency_ms,
        "zone": zone,
        "city": city,
        "country": country,
        "threat": threat_type,
        "request_id": request_id,
    }
    _write_file_log(entry)
    if threat_type:
        maybe_ban_for_threat(ip, threat_type, threat_score)
        # Сканеры на мусорных путях с 404 — только в лог БД, без Telegram-спама
        if threat_type == "internal_probe":
            return
        if not (threat_type == "scanner" and status_code == 404):
            send_security_alert(
                threat_type=threat_type,
                ip=ip,
                path=path,
                method=method,
                status_code=status_code,
                city=city,
                country_code=country,
                zone=zone,
                user_agent=user_agent,
                request_id=request_id,
            )


def _schedule(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if len(_pending_tasks) >= _MAX_PENDING:
        logger.warning("access log queue full, dropping event")
        return
    task = loop.create_task(coro)
    _pending_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _pending_tasks.discard(t)
        if not t.cancelled() and t.exception():
            logger.warning("access log task failed: %s", t.exception())

    task.add_done_callback(_done)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        request_id = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-Id"] = request_id
        ip = get_client_ip(request)
        _schedule(
            _process_access(
                ip=ip,
                method=request.method,
                path=path,
                status_code=response.status_code,
                latency_ms=latency_ms,
                user_agent=request.headers.get("user-agent"),
                authorization=request.headers.get("authorization"),
                request_id=request_id,
            )
        )
        return response

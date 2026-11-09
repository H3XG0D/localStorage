"""HTTPS-only urllib helper (Bandit B310).

Callers must pass a Request or URL; non-https schemes are rejected before urlopen.
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from urllib.parse import urlparse
from urllib.request import Request

_ALLOWED_SCHEMES = frozenset({"https"})


def https_urlopen(req: Request | str, timeout: float = 15):
    url = req.get_full_url() if isinstance(req, Request) else str(req)
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("refusing non-https URL")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310


def https_read_json(req: Request | str, timeout: float = 15):
    with https_urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


async def https_read_json_async(req: Request | str, timeout: float = 15):
    return await asyncio.to_thread(https_read_json, req, timeout)

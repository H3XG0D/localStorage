"""Tor .onion request helpers (v3 hostname, cookie/CORS/site-config)."""
from __future__ import annotations

import re

from fastapi import Request

from config import settings

# Tor v3: 56 chars of base32 (a-z2-7) + .onion
_ONION_HOST_RE = re.compile(r"^[a-z2-7]{56}\.onion$", re.IGNORECASE)
_ONION_ORIGIN_RE = re.compile(
    r"^https?://[a-z2-7]{56}\.onion(?::\d+)?$",
    re.IGNORECASE,
)

# Starlette CORSMiddleware allow_origin_regex
ONION_ORIGIN_REGEX = r"https?://[a-z2-7]{56}\.onion"


def hostname_from_host_header(host: str | None) -> str:
    raw = (host or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")]
    return raw.split("/", 1)[0].split(":", 1)[0]


def is_onion_host(host: str | None) -> bool:
    return bool(_ONION_HOST_RE.fullmatch(hostname_from_host_header(host)))


def request_is_onion(request: Request | None) -> bool:
    if request is None:
        return False
    host = request.headers.get("host") or (request.url.hostname or "")
    return is_onion_host(host)


def normalize_onion_origin(raw: str | None) -> str:
    """Canonical http://<v3>.onion or empty. Tor already encrypts the circuit."""
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    value = value.rstrip("/")
    if not _ONION_ORIGIN_RE.fullmatch(value):
        return ""
    host = hostname_from_host_header(value.split("://", 1)[1])
    return f"http://{host}"


def public_onion_url() -> str:
    return normalize_onion_origin(getattr(settings, "public_onion_url", "") or "")


def doliv_onion_url() -> str:
    return normalize_onion_origin(getattr(settings, "doliv_onion_url", "") or "")

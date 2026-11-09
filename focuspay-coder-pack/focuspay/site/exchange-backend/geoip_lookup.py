"""GeoIP: MaxMind GeoLite2-City.mmdb, иначе HTTP fallback (ip-api.com)."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger("geoip")

_reader = None
_reader_tried = False


def _is_public_ip(ip: str) -> bool:
    """Без stdlib ipaddress (на сервере operator.py перекрывает модуль operator)."""
    s = (ip or "").strip()
    if not s or ":" in s:
        return bool(s)
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        o = [int(p) for p in parts]
    except ValueError:
        return False
    if o[0] == 10:
        return False
    if o[0] == 127:
        return False
    if o[0] == 192 and o[1] == 168:
        return False
    if o[0] == 172 and 16 <= o[1] <= 31:
        return False
    return True


def _get_reader():
    global _reader, _reader_tried
    if _reader_tried:
        return _reader
    _reader_tried = True
    from config import settings

    path = (settings.geoip_city_db_path or "").strip()
    if not path or not Path(path).is_file():
        if path:
            logger.warning("GeoIP database not found: %s (using HTTP fallback)", path)
        return None
    try:
        import geoip2.database

        _reader = geoip2.database.Reader(path)
        logger.info("GeoIP reader loaded: %s", path)
    except Exception as e:
        logger.warning("GeoIP init failed: %s", e)
        _reader = None
    return _reader


def _lookup_mmdb(ip: str) -> tuple[Optional[str], Optional[str]]:
    reader = _get_reader()
    if not reader:
        return None, None
    try:
        rec = reader.city(ip)
        country = (rec.country.iso_code or "").upper() or None
        city = rec.city.name or None
        return country, city
    except Exception:
        return None, None


def _lookup_http(ip: str) -> tuple[Optional[str], Optional[str]]:
    if not _is_public_ip(ip):
        return None, "локальный"
    try:
        import requests

        resp = requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,countryCode,city"},
            timeout=2,
        )
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        if data.get("status") != "success":
            return None, None
        country = (data.get("countryCode") or "").upper() or None
        city = data.get("city") or None
        return country, city
    except Exception as e:
        logger.debug("geoip http fallback %s: %s", ip, e)
        return None, None


@lru_cache(maxsize=8192)
def lookup_geo(ip: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (country_code, city) or (None, None)."""
    if not ip:
        return None, None
    ip = ip.strip()
    country, city = _lookup_mmdb(ip)
    if country or city:
        return country, city
    return _lookup_http(ip)


def format_geo(ip: str, country: str | None, city: str | None) -> str:
    """Строка для Telegram: IP + город/страна."""
    ip_s = ip or "?"
    if city and country:
        return f"{ip_s} · {city}, {country}"
    if city:
        return f"{ip_s} · {city}"
    if country:
        return f"{ip_s} · {country}"
    if not _is_public_ip(ip_s):
        return f"{ip_s} · локальный"
    return ip_s

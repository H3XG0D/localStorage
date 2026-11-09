"""Multi-merchant payin registry: priority-ordered failover 1→2→3."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("merchants.registry")


@dataclass
class Merchant:
    id: str
    name: str
    kind: str = "payfast"
    base_url: str = ""
    api_key: str = ""
    secret: str = ""
    callback_url: str = ""
    default_sub_token: str = "SBPRUB"
    priority: int = 100
    enabled: bool = True
    timeout_sec: float = 12.0
    sub_tokens: tuple[str, ...] = ()


def _parse_merchants_json(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(data, dict):
        data = data.get("merchants", [])
    return data if isinstance(data, list) else []


def _legacy_merchant() -> Merchant | None:
    try:
        from config import settings
    except Exception:
        return None
    base = (getattr(settings, "merchant_base_url", "") or "").rstrip("/")
    if not base:
        return None
    return Merchant(
        id=(getattr(settings, "merchant_id", "") or "payfast").strip() or "payfast",
        name="payfast (legacy)",
        kind="payfast",
        base_url=base,
        api_key=getattr(settings, "merchant_api_key", "") or "",
        secret=getattr(settings, "merchant_secret_key", "") or "",
        callback_url=getattr(settings, "merchant_callback_url", "") or "",
        default_sub_token=getattr(settings, "merchant_default_sub_token", "") or "SBPRUB",
        priority=100,
        enabled=True,
    )


def load_merchants(*, explicit_json: str | None = None) -> list[Merchant]:
    raw = explicit_json if explicit_json is not None else os.getenv("MERCHANTS_JSON", "")
    merchants: list[Merchant] = []
    for i, item in enumerate(_parse_merchants_json(raw or "")):
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_url") or "").rstrip("/")
        if not base:
            continue
        merchants.append(Merchant(
            id=str(item.get("id") or f"merchant_{i}").strip(),
            name=str(item.get("name") or item.get("id") or f"merchant_{i}"),
            kind=str(item.get("kind") or "payfast").strip() or "payfast",
            base_url=base,
            api_key=str(item.get("api_key") or ""),
            secret=str(item.get("secret") or ""),
            callback_url=str(item.get("callback_url") or ""),
            default_sub_token=str(item.get("default_sub_token") or "SBPRUB"),
            priority=int(item.get("priority", 100 + i)),
            enabled=bool(item.get("enabled", True)),
            timeout_sec=float(item.get("timeout_sec") or 12.0),
            sub_tokens=tuple(s.upper() for s in (item.get("sub_tokens") or []) if str(s).strip()),
        ))
    if not merchants:
        legacy = _legacy_merchant()
        if legacy:
            merchants = [legacy]
    merchants.sort(key=lambda m: (m.priority, m.id))
    return merchants


def enabled_merchants(merchants: list[Merchant] | None = None) -> list[Merchant]:
    if merchants is None:
        return load_merchants()
    return sorted(
        (m for m in merchants if m.enabled and m.base_url),
        key=lambda m: (m.priority, m.id),
    )

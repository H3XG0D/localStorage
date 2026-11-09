"""Лимиты, которые основной сервер подтягивает из админки.

Env (`signer.env`) — стартовые значения и запасной рубеж после рестарта,
пока API ещё не успел синхронизировать. Админка может поднять потолки без SSH.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger("focuspay-signer.policy")

_lock = threading.Lock()
_overrides: dict[str, float] = {}

_KEYS = ("max_tx_btc", "max_tx_ltc", "daily_cap_btc", "daily_cap_ltc")


def _path() -> Path:
    return Path(settings.audit_path).parent / "policy_overrides.json"


def load() -> None:
    global _overrides
    path = _path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("policy overrides read failed")
        return
    if not isinstance(raw, dict):
        return
    cleaned: dict[str, float] = {}
    for key in _KEYS:
        try:
            val = float(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
        if val > 0:
            cleaned[key] = val
    with _lock:
        _overrides = cleaned
    if cleaned:
        logger.info("policy overrides loaded %s", cleaned)


def save(patch: dict[str, Any]) -> dict[str, float]:
    """Обновить и сохранить переданные потолки. Пустые/нулевые ключи игнорируются."""
    global _overrides
    cleaned: dict[str, float] = {}
    for key in _KEYS:
        if key not in patch:
            continue
        try:
            val = float(patch[key])
        except (TypeError, ValueError):
            continue
        if val > 0:
            cleaned[key] = val
    with _lock:
        next_map = dict(_overrides)
        next_map.update(cleaned)
        _overrides = next_map
        to_write = dict(_overrides)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_write, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot()


def snapshot() -> dict[str, float]:
    with _lock:
        ov = dict(_overrides)
    return {
        "max_tx_btc": float(ov.get("max_tx_btc") or settings.max_tx_btc),
        "max_tx_ltc": float(ov.get("max_tx_ltc") or settings.max_tx_ltc),
        "daily_cap_btc": float(ov.get("daily_cap_btc") or settings.daily_cap_btc),
        "daily_cap_ltc": float(ov.get("daily_cap_ltc") or settings.daily_cap_ltc),
        "env_max_tx_btc": float(settings.max_tx_btc),
        "env_max_tx_ltc": float(settings.max_tx_ltc),
        "env_daily_cap_btc": float(settings.daily_cap_btc),
        "env_daily_cap_ltc": float(settings.daily_cap_ltc),
    }


def max_tx(coin: str) -> float:
    c = coin.lower()
    key = f"max_tx_{c}"
    with _lock:
        if key in _overrides:
            return float(_overrides[key])
    if c == "btc":
        return float(settings.max_tx_btc)
    if c == "ltc":
        return float(settings.max_tx_ltc)
    return 0.0


def daily_cap(coin: str) -> float:
    c = coin.lower()
    key = f"daily_cap_{c}"
    with _lock:
        if key in _overrides:
            return float(_overrides[key])
    if c == "btc":
        return float(settings.daily_cap_btc)
    if c == "ltc":
        return float(settings.daily_cap_ltc)
    return 0.0

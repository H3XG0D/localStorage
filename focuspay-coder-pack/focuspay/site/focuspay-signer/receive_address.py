"""Следующий свободный адрес пополнения горячего кошелька.

Все выданные адреса живут в одном кошельке ноды. Баланс и sendtoaddress
видят выходы со всех сразу: сменённый адрес продолжает принимать, монеты
с него тратятся вместе с остальными.
"""
from __future__ import annotations

import asyncio

import store
import wallet_rpc

_COINS = ("btc", "ltc")
_locks: dict[str, asyncio.Lock] = {}


def needs_fresh_address(received: float) -> bool:
    """Адрес использован, если на него уже приходила любая сумма."""
    try:
        amount = float(received)
    except (TypeError, ValueError):
        return False
    return amount > 0


def _coin_lock(coin: str) -> asyncio.Lock:
    lock = _locks.get(coin)
    if lock is None:
        lock = asyncio.Lock()
        _locks[coin] = lock
    return lock


async def ensure_receive_address(coin: str, *, force: bool = False) -> tuple[str | None, bool]:
    """Возвращает (текущий адрес, сменился ли он в этом вызове).

    force выдаёт следующий адрес, даже если на текущий ещё ничего не приходило.
    """
    name = (coin or "").strip().lower()
    if name not in _COINS:
        raise ValueError("unsupported_coin")
    async with _coin_lock(name):
        current = store.deposit_address(name)
        if not current:
            minted = await wallet_rpc.new_deposit_address(name)
            saved = store.install_deposit_address(name, minted)
            return saved, True
        if not force:
            received = await wallet_rpc.address_received(name, current)
            if not needs_fresh_address(received):
                return current, False
        minted = await wallet_rpc.new_deposit_address(name)
        if minted == current:
            return current, False
        saved = store.install_deposit_address(name, minted)
        return saved, saved != current

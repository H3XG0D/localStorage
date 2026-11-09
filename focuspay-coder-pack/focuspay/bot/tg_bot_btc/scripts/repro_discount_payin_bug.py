#!/usr/bin/env python3
"""Repro: скидка ломает повторное создание payin (дубль kwarg callback_url).

НЕ шлёт запросы в Payfast. TypeError возникает на границе вызова Python
(дубль callback_url) ещё до merchant_post, поэтому HTTP не уходит.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CALL_COUNT = 0


async def fake_create_payin_order(*, order_id, user_id, fiat_amount, callback_url, sub_token=None):
    """Сигнатура как у настоящего handlers.exchange_flow.create_payin_order."""
    global CALL_COUNT
    CALL_COUNT += 1
    return {"bill": {"bank": "X", "reciver": "40817810"}}


def make_probe_payin(callback_url, *, fixed: bool):
    """Замыкание _probe_payin из exchange_enter_requisites (до/после фикса)."""

    async def _probe_payin_buggy(**kwargs):
        return await fake_create_payin_order(callback_url=callback_url, **kwargs)

    async def _probe_payin_fixed(**kwargs):
        kwargs.setdefault("callback_url", callback_url)
        return await fake_create_payin_order(**kwargs)

    return _probe_payin_fixed if fixed else _probe_payin_buggy


async def _call_reissue(create_payin_order_fn, callback_url):
    """Так вызывает create_buy_part_order ветку повторного создания после скидки."""
    return await create_payin_order_fn(
        order_id="12345678",
        user_id=42,
        fiat_amount=2664,
        callback_url=callback_url,
        sub_token="CARDRUB",
    )


async def main():
    callback_url = "https://example.org/callback"

    print(">> ДО фикса (api_response=None после скидки):")
    try:
        await _call_reissue(make_probe_payin(callback_url, fixed=False), callback_url)
        print("   (неожиданно: TypeError не возник)")
        rc = 0
    except TypeError as e:
        print(f"   !! TypeError: {e}")
        print("   !! Не ValueError -> _try_create_single_buy_order не ловит ->")
        print("   !! до exchange_text_router -> «❌ Ошибка. Нажмите ...»")
        rc = 1

    print(">> ПОСЛЕ фикса (setdefault):")
    resp = await _call_reissue(make_probe_payin(callback_url, fixed=True), callback_url)
    print(f"   OK, bill={resp.get('bill')}")
    print(f"\nИтого Payfast-запросов отправлено: {CALL_COUNT} (TypeError возникает до HTTP)")
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

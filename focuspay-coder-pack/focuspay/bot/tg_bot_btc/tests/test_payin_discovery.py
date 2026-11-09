"""Unit tests for payin_discovery.discover_payin_plan (mock merchant, no HTTP)."""
from __future__ import annotations

import asyncio

from services.payin_discovery import discover_payin_plan


def _bill_resp(bank: str = "Test") -> dict:
    return {"bill": {"bank": bank, "reciver": "40817810"}}


def _no_bill_resp() -> dict:
    return {"status_pending": "ok", "bill": None, "uuid_system": "uuid-1"}


def test_sbprub_with_bill_returns_single():
    calls: list[tuple[str, int, str]] = []

    async def create_payin_fn(*, order_id, user_id, fiat_amount, sub_token, **kwargs):
        calls.append((order_id, int(fiat_amount), sub_token))
        return _bill_resp()

    result = asyncio.run(
        discover_payin_plan(
            fiat_amount=8000,
            sub_token="SBPRUB",
            user_id=1,
            create_payin_fn=create_payin_fn,
            cancel_payin_fn=None,
            generate_order_id_fn=lambda: "oid1",
            poll_bill=False,
        )
    )

    assert result.plan.mode == "single"
    assert result.plan.has_bill is True
    assert result.probe_order_id == "oid1"
    assert len(calls) == 1
    assert calls[0][2] == "SBPRUB"


def test_cardrub_fallback_to_sbprub():
    calls: list[str] = []
    cancelled: list[str] = []

    async def create_payin_fn(*, order_id, user_id, fiat_amount, sub_token, **kwargs):
        calls.append(sub_token)
        if sub_token == "CARDRUB":
            return _no_bill_resp()
        return _bill_resp("SBP Bank")

    async def cancel_payin_fn(uuid_val: str):
        cancelled.append(uuid_val)

    result = asyncio.run(
        discover_payin_plan(
            fiat_amount=10000,
            sub_token="CARDRUB",
            user_id=42,
            create_payin_fn=create_payin_fn,
            cancel_payin_fn=cancel_payin_fn,
            generate_order_id_fn=lambda: "oid2",
            poll_bill=False,
        )
    )

    assert result.plan.mode == "single"
    assert result.plan.has_bill is True
    assert result.plan.resolved_sub_token == "SBPRUB"
    assert calls == ["CARDRUB", "SBPRUB"]
    assert cancelled == ["uuid-1"]


def test_both_without_bill_returns_operator():
    async def create_payin_fn(*, order_id, user_id, fiat_amount, sub_token, **kwargs):
        return _no_bill_resp()

    async def cancel_payin_fn(uuid_val: str):
        return None

    result = asyncio.run(
        discover_payin_plan(
            fiat_amount=8000,
            sub_token="CARDRUB",
            user_id=1,
            create_payin_fn=create_payin_fn,
            cancel_payin_fn=cancel_payin_fn,
            generate_order_id_fn=lambda: "oid3",
            poll_bill=False,
        )
    )

    assert result.plan.mode == "operator"
    assert result.plan.has_bill is False
    assert result.probe_response is None

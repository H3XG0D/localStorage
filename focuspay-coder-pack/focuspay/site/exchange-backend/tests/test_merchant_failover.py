"""Failover 1→2→3 + сквозная атрибуция merchant."""
import asyncio
import json

from merchants.client import (
    attempts_from_response,
    create_payin_routed,
    merchant_id_from_response,
)
from merchants.registry import Merchant, enabled_merchants, load_merchants
from payin_resolver import build_payin_plan, get_bill_from_response


def _bill(merchant="m1"):
    return {
        "bill": {"reciver": "card-1", "receiver": "card-1"},
        "data_order": {"uuid_system": f"uuid-{merchant}"},
        "uuid_system": f"uuid-{merchant}",
    }


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_registry_priority_and_disabled():
    ms = [
        Merchant(id="b", name="b", base_url="http://b", priority=20),
        Merchant(id="a", name="a", base_url="http://a", priority=10),
        Merchant(id="off", name="off", base_url="http://off", priority=1, enabled=False),
    ]
    assert [m.id for m in enabled_merchants(ms)] == ["a", "b"]


def test_registry_explicit_json():
    ms = load_merchants(explicit_json='[{"id": "payfast", "base_url": "http://m1", "priority": 1}, {"id": "custom_treugol", "base_url": "http://m2", "priority": 2}]')
    assert [m.id for m in enabled_merchants(ms)] == ["payfast", "custom_treugol"]


def test_failover_first_fails_second_wins(monkeypatch):
    import merchants.client as client

    async def fake_post(session, m, path, payload):
        if m.id == "m1":
            return 500, {"status_pending": "error", "error": "HTTP 500"}
        return 200, _bill(m.id)

    monkeypatch.setattr(client, "_post_to_merchant", fake_post)
    ms = [
        Merchant(id="m1", name="m1", base_url="http://m1", priority=1),
        Merchant(id="m2", name="m2", base_url="http://m2", priority=2),
    ]
    resp = _run(create_payin_routed(order_id="O1", user_id=1, fiat_amount=1000, merchants=ms))
    assert merchant_id_from_response(resp) == "m2"
    attempts = attempts_from_response(resp)
    assert [a["merchant_id"] for a in attempts] == ["m1", "m2"]
    assert attempts[0]["ok"] is False and attempts[1]["ok"] is True
    assert get_bill_from_response(resp) is not None


def test_failover_no_bill_skips_to_next(monkeypatch):
    import merchants.client as client

    async def fake_post(session, m, path, payload):
        if m.id == "m1":
            return 200, {"data_order": {}}  # без bill
        return 200, _bill(m.id)

    monkeypatch.setattr(client, "_post_to_merchant", fake_post)
    ms = [
        Merchant(id="m1", name="m1", base_url="http://m1", priority=1),
        Merchant(id="m2", name="m2", base_url="http://m2", priority=2),
    ]
    resp = _run(create_payin_routed(order_id="O2", user_id=1, fiat_amount=1000, merchants=ms))
    assert merchant_id_from_response(resp) == "m2"


def test_all_fail_returns_attempts(monkeypatch):
    import merchants.client as client

    async def fake_post(session, m, path, payload):
        return 0, {"status_pending": "error", "error": "Timeout"}

    monkeypatch.setattr(client, "_post_to_merchant", fake_post)
    ms = [Merchant(id="m1", name="m1", base_url="http://m1", priority=1)]
    resp = _run(create_payin_routed(order_id="O3", user_id=1, fiat_amount=1000, merchants=ms))
    assert merchant_id_from_response(resp) is None
    assert len(attempts_from_response(resp)) == 1
    plan = build_payin_plan(1000, "SBPRUB", api_response=None)
    assert plan.mode == "operator"  # fallback без bill сохраняется


def test_sub_token_routing_skips_unsupported(monkeypatch):
    import merchants.client as client

    seen = []

    async def fake_post(session, m, path, payload):
        seen.append(m.id)
        return 200, _bill(m.id)

    monkeypatch.setattr(client, "_post_to_merchant", fake_post)
    ms = [
        Merchant(id="m1", name="m1", base_url="http://m1", priority=1, sub_tokens=("CARDRUB",)),
        Merchant(id="m2", name="m2", base_url="http://m2", priority=2),
    ]
    resp = _run(create_payin_routed(order_id="O4", user_id=1, fiat_amount=1000,
                                    sub_token="SBPRUB", merchants=ms))
    assert merchant_id_from_response(resp) == "m2"
    assert seen == ["m2"]


def test_snapshot_carries_attribution():
    resp = dict(_bill("treugol"))
    resp["_merchant_id"] = "custom_treugol"
    resp["_merchant_attempts"] = [{"merchant_id": "payfast", "ok": False}]
    snap = {
        "bill": resp["bill"],
        "merchant_id": merchant_id_from_response(resp),
        "merchant_attempts": attempts_from_response(resp),
    }
    assert snap["merchant_id"] == "custom_treugol"
    assert json.dumps(snap)  # jsonb-serializable

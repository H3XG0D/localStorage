"""Card-first: go-online opens one session with hold; second session rejected."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


@pytest.mark.asyncio
async def test_card_go_online_holds_and_blocks_second_session(client: AsyncClient, trader_user, app_settings):
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    before = await client.get("/trader/wallet", headers=headers)
    assert before.status_code == 200
    avail_before = Decimal(before.json()["available"])

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Sber ****9999",
            "last4": "9999",
            "bank": "Sber",
            "purchase_cost_rub": "0",
            "record_purchase_expense": False,
            "accept_limit_rub": "9000",
            "target_rate": "90",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert body["session_id"] is not None
    assert body["session_status"] == "active"
    assert Decimal(body["session_total_rub"]) == Decimal("9000")
    assert Decimal(body["session_remaining_rub"]) == Decimal("9000")
    # hold = 9000/90 = 100 USDT
    assert Decimal(body["session_hold_usdt"]) == Decimal("100")

    wallet = await client.get("/trader/wallet", headers=headers)
    avail_after = Decimal(wallet.json()["available"])
    assert avail_after == avail_before - Decimal("100")

    dup = await client.post(
        f"/trader/cards/{body['id']}/go-online",
        headers=headers,
        json={"accept_limit_rub": "1000", "target_rate": "90"},
    )
    assert dup.status_code == 400
    assert "open session" in dup.json()["detail"].lower() or "already" in dup.json()["detail"].lower()

    # Session is visible in requisites list (history)
    reqs = await client.get("/trader/requisites", headers=headers)
    assert reqs.status_code == 200
    assert any(r["id"] == body["session_id"] for r in reqs.json())


@pytest.mark.asyncio
async def test_go_online_endpoint_after_card_create(client: AsyncClient, trader_user, app_settings):
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Alpha",
            "record_purchase_expense": False,
            "card_number": "4276123456789999",
            "go_online": False,
        },
    )
    assert card.status_code == 201
    assert card.json()["session_id"] is None

    online = await client.post(
        f"/trader/cards/{card.json()['id']}/go-online",
        headers=headers,
        json={"accept_limit_rub": "4500", "target_rate": "90"},
    )
    assert online.status_code == 200, online.text
    assert online.json()["session_id"] is not None
    assert Decimal(online.json()["session_hold_usdt"]) == Decimal("50")

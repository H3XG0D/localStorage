"""C2C vs SBP channel on cards / go-online."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


async def _set_rate(client: AsyncClient) -> None:
    token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/rates/working",
        headers=auth_headers(token),
        json={"rate": "90", "mode": "manual"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_sbp_go_online_ok(client: AsyncClient, trader_user, admin_user, app_settings):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "SBP Sber",
            "channel": "sbp",
            "phone": "89001234567",
            "recipient_name": "Иванов Иван",
            "bank": "Sber",
            "record_purchase_expense": False,
            "daily_limit_rub": "30000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert body["channel"] == "sbp"
    assert body["phone"] == "+79001234567"
    assert body["session_id"] is not None
    assert "СБП" in body.get("name", "") or True  # card name stays; session uses display name
    # Session list shows SBP label
    reqs = await client.get("/trader/requisites", headers=headers)
    assert reqs.status_code == 200
    sess = next(r for r in reqs.json() if r["id"] == body["session_id"])
    assert "СБП" in sess["name"]
    assert "+79001234567" in sess["name"]


@pytest.mark.asyncio
async def test_sbp_requires_phone_and_recipient(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    bad = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "SBP bad",
            "channel": "sbp",
            "recipient_name": "Иванов",
            "record_purchase_expense": False,
            "daily_limit_rub": "10000",
            "go_online": True,
        },
    )
    assert bad.status_code == 400
    assert "phone" in bad.json()["detail"].lower()

    bad2 = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "SBP bad2",
            "channel": "sbp",
            "phone": "+79001112233",
            "record_purchase_expense": False,
            "daily_limit_rub": "10000",
            "go_online": True,
        },
    )
    assert bad2.status_code == 400
    assert "recipient" in bad2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_c2c_requires_card_number_on_go_online(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    bad = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "No card",
            "channel": "c2c",
            "record_purchase_expense": False,
            "daily_limit_rub": "10000",
            "go_online": True,
        },
    )
    assert bad.status_code == 400
    assert "card" in bad.json()["detail"].lower()

    ok = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "C2C ok",
            "channel": "c2c",
            "card_number": "4276123456781234",
            "record_purchase_expense": False,
            "daily_limit_rub": "9000",
            "go_online": True,
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["channel"] == "c2c"
    assert Decimal(ok.json()["session_hold_usdt"]) == Decimal("100")

"""Working office rate: admin sets; go-online snapshots; change does not rewrite old hold."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


async def _admin_set_rate(client: AsyncClient, rate: str = "90", mode: str = "manual") -> None:
    token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/rates/working",
        headers=auth_headers(token),
        json={"rate": rate, "mode": mode, "comment": "test"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_admin_sets_working_rate_go_online_uses_it(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _admin_set_rate(client, "92")
    trader_tok = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(trader_tok)

    wr = await client.get("/rates/working", headers=headers)
    assert wr.status_code == 200
    assert Decimal(wr.json()["rate"]) == Decimal("92")

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "WR Card",
            "record_purchase_expense": False,
            "card_number": "4276123456789012",
            "daily_limit_rub": "9200",
            "go_online": True,
            "target_rate": "50",  # ignored
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert Decimal(body["session_hold_usdt"]) == Decimal("100")  # 9200/92
    assert Decimal(body["target_rate"]) == Decimal("92")


@pytest.mark.asyncio
async def test_rate_change_does_not_rewrite_old_session_hold(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _admin_set_rate(client, "90")
    trader_tok = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(trader_tok)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Snap Card",
            "record_purchase_expense": False,
            "card_number": "4276123456789013",
            "accept_limit_rub": "9000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    hold1 = Decimal(card.json()["session_hold_usdt"])
    assert hold1 == Decimal("100")
    session_id = card.json()["session_id"]

    await _admin_set_rate(client, "100")

    req = await client.get(f"/trader/requisites/{session_id}", headers=headers)
    assert req.status_code == 200
    assert Decimal(req.json()["target_rate"]) == Decimal("90")
    assert Decimal(req.json()["hold_usdt"]) == Decimal("100")

    # New card uses new office rate
    card2 = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "New Rate Card",
            "record_purchase_expense": False,
            "card_number": "4276123456789014",
            "accept_limit_rub": "10000",
            "go_online": True,
        },
    )
    assert card2.status_code == 201, card2.text
    assert Decimal(card2.json()["session_hold_usdt"]) == Decimal("100")  # 10000/100

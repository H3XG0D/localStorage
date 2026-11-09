"""Card fields: recipient, daily/max payment; zaliv rejects over max_payment."""
from decimal import Decimal
from io import BytesIO

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    """Minimal valid JPEG header."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


async def _set_rate(client: AsyncClient, rate: str = "90") -> None:
    token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/rates/working",
        headers=auth_headers(token),
        json={"rate": rate, "mode": "manual"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_card_fields_and_daily_limit_session(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Full Card",
            "bank": "Sber",
            "card_number": "4276123456789012",
            "recipient_name": "Иванов Иван",
            "purchase_cost_rub": "0",
            "record_purchase_expense": False,
            "daily_limit_rub": "50000",
            "max_payment_rub": "15000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert body["recipient_name"] == "Иванов Иван"
    assert body["card_number"] == "4276123456789012"
    assert body["last4"] == "9012"
    assert Decimal(body["daily_limit_rub"]) == Decimal("50000")
    assert Decimal(body["max_payment_rub"]) == Decimal("15000")
    assert Decimal(body["session_total_rub"]) == Decimal("50000")
    assert Decimal(body["session_hold_usdt"]) == Decimal("555.555556")


@pytest.mark.asyncio
async def test_zaliv_rejects_over_max_payment(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "MaxPay",
            "record_purchase_expense": False,
            "card_number": "4276123456788888",
            "daily_limit_rub": "100000",
            "max_payment_rub": "15000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    session_id = card.json()["session_id"]

    files = {"receipt": ("r.jpg", BytesIO(_fake_jpg()), "image/jpeg")}
    data = {"amount": "20000", "rate": "90"}
    bad = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data=data,
        files=files,
    )
    assert bad.status_code == 400
    assert "max payment" in bad.json()["detail"].lower()

    files2 = {"receipt": ("r2.jpg", BytesIO(_fake_jpg()), "image/jpeg")}
    ok = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "10000", "rate": "90"},
        files=files2,
    )
    assert ok.status_code == 201, ok.text

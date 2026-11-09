"""Payment corridors and daily-limit exhaustion."""
from decimal import Decimal
from io import BytesIO

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
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
async def test_payment_bands_and_gap_rejected(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Bands",
            "record_purchase_expense": False,
            "card_number": "4276123456787777",
            "daily_limit_rub": "100000",
            "payment_bands": [
                {"min_rub": "3000", "max_rub": "5000"},
                {"min_rub": "10000", "max_rub": "15000"},
            ],
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert body["payment_bands"]
    assert Decimal(body["min_payment_rub"]) == Decimal("3000")
    assert Decimal(body["max_payment_rub"]) == Decimal("15000")
    assert body["accepting"] is True
    session_id = body["session_id"]

    gap = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "7000", "rate": "90"},
        files={"receipt": ("r.jpg", BytesIO(_fake_jpg()), "image/jpeg")},
    )
    assert gap.status_code == 400
    assert "corridor" in gap.json()["detail"].lower()

    ok = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "4000", "rate": "90"},
        files={"receipt": ("r2.jpg", BytesIO(_fake_jpg()), "image/jpeg")},
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_daily_limit_exhausted_rejects_zaliv(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "DayCap",
            "record_purchase_expense": False,
            "card_number": "4276123456786666",
            "daily_limit_rub": "5000",
            "payment_bands": [{"min_rub": "1000", "max_rub": "5000"}],
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    session_id = card.json()["session_id"]

    fill = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "5000", "rate": "90"},
        files={"receipt": ("r.jpg", BytesIO(_fake_jpg()), "image/jpeg")},
    )
    assert fill.status_code == 201, fill.text

    cards = await client.get("/trader/cards", headers=headers)
    row = next(c for c in cards.json()["items"] if c["id"] == card.json()["id"])
    assert row["accepting"] is False
    assert Decimal(row["session_remaining_rub"]) == Decimal("0")

    more = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "1000", "rate": "90"},
        files={"receipt": ("r3.jpg", BytesIO(_fake_jpg()), "image/jpeg")},
    )
    assert more.status_code == 400
    detail = more.json()["detail"].lower()
    assert "daily" in detail or "exhausted" in detail or "remaining" in detail

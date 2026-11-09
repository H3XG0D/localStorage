"""Accepting toggle: pause does not release hold; merchant skips disabled cards."""
from decimal import Decimal
from io import BytesIO
import hashlib
import hmac
import json
import time

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


def _sign(secret: str, body: str, ts: str) -> str:
    return hmac.new(secret.encode(), (ts + body).encode(), hashlib.sha256).hexdigest()


async def _set_rate(client: AsyncClient, rate: str = "90") -> None:
    token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/rates/working",
        headers=auth_headers(token),
        json={"rate": rate, "mode": "manual"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_accepting_toggle_keeps_hold(client: AsyncClient, trader_user, admin_user, app_settings):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Toggle",
            "record_purchase_expense": False,
            "card_number": "4276123456781111",
            "daily_limit_rub": "9000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    body = card.json()
    assert body["accepting"] is True
    assert body["accepting_enabled"] is True
    assert body["not_accepting_reason"] is None
    session_id = body["session_id"]
    hold = Decimal(body["session_hold_usdt"])

    wallet = await client.get("/trader/wallet", headers=headers)
    held_on = Decimal(wallet.json()["held"])

    off = await client.post(
        f"/trader/cards/{body['id']}/accepting",
        headers=headers,
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["accepting"] is False
    assert off.json()["not_accepting_reason"] == "disabled"
    assert off.json()["session_id"] == session_id
    assert Decimal(off.json()["session_hold_usdt"]) == hold

    wallet_off = await client.get("/trader/wallet", headers=headers)
    assert Decimal(wallet_off.json()["held"]) == held_on

    on = await client.post(
        f"/trader/cards/{body['id']}/accepting",
        headers=headers,
        json={"enabled": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["accepting"] is True
    assert on.json()["session_id"] == session_id
    wallet_on = await client.get("/trader/wallet", headers=headers)
    assert Decimal(wallet_on.json()["held"]) == held_on


@pytest.mark.asyncio
async def test_received_today_and_daily_remaining(client: AsyncClient, trader_user, admin_user, app_settings):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "DayRemain",
            "record_purchase_expense": False,
            "card_number": "4276123456782222",
            "daily_limit_rub": "10000",
            "payment_bands": [{"min_rub": "1000", "max_rub": "10000"}],
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    session_id = card.json()["session_id"]
    assert Decimal(card.json()["received_today_rub"]) == Decimal("0")
    assert Decimal(card.json()["daily_remaining_rub"]) == Decimal("10000")

    zaliv = await client.post(
        f"/trader/requisites/{session_id}/zalivs",
        headers=headers,
        data={"amount": "4000", "rate": "90"},
        files={"receipt": ("r.jpg", BytesIO(_fake_jpg()), "image/jpeg")},
    )
    assert zaliv.status_code == 201, zaliv.text

    listed = await client.get("/trader/cards", headers=headers)
    row = next(c for c in listed.json()["items"] if c["id"] == card.json()["id"])
    assert Decimal(row["received_today_rub"]) == Decimal("4000")
    assert Decimal(row["daily_remaining_rub"]) == Decimal("6000")
    assert row["accepting"] is True


@pytest.mark.asyncio
async def test_bulk_disable_and_list_filter(client: AsyncClient, trader_user, admin_user, app_settings):
    await _set_rate(client)
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)
    ids = []
    for i in range(2):
        card = await client.post(
            "/trader/cards",
            headers=headers,
            json={
                "name": f"Bulk {i}",
                "record_purchase_expense": False,
                "card_number": f"42761234567833{i}{i}",
                "daily_limit_rub": "5000",
                "go_online": True,
            },
        )
        assert card.status_code == 201, card.text
        ids.append(card.json()["id"])

    bulk = await client.post(
        "/trader/cards/bulk",
        headers=headers,
        json={"ids": ids, "action": "disable"},
    )
    assert bulk.status_code == 200, bulk.text
    assert set(bulk.json()["ok"]) == set(ids)

    listed = await client.get("/trader/cards", headers=headers, params={"accepting": False})
    assert listed.status_code == 200
    got = {c["id"] for c in listed.json()["items"]}
    assert set(ids) <= got


@pytest.mark.asyncio
async def test_merchant_skips_disabled_card(client: AsyncClient, trader_user, admin_user, app_settings):
    await _set_rate(client)
    ttok = await get_token(client, "trader_test", "Traderpass12")
    atok = await get_token(client, "admin_test", "Adminpass12")

    card = await client.post(
        "/trader/cards",
        headers=auth_headers(ttok),
        json={
            "name": "SBP merchant toggle",
            "record_purchase_expense": False,
            "phone": "+79001112233",
            "channel": "sbp",
            "bank": "Сбер",
            "recipient_name": "Иван Тестов",
            "daily_limit_rub": "200000",
            "min_payment_rub": "1000",
            "max_payment_rub": "50000",
            "go_online": True,
        },
    )
    assert card.status_code == 201, card.text
    off = await client.post(
        f"/trader/cards/{card.json()['id']}/accepting",
        headers=auth_headers(ttok),
        json={"enabled": False},
    )
    assert off.status_code == 200

    partner = await client.post(
        "/admin/merchant-partners",
        headers=auth_headers(atok),
        json={"name": "lab-partner-toggle"},
    )
    assert partner.status_code == 201, partner.text
    api_key = partner.json()["api_key"]
    secret = partner.json()["secret"]

    payload = {
        "token": "P2P",
        "sub_token": "SBPRUB",
        "fingerprint": "1",
        "client_transaction_id": "merchant-toggle-1",
        "amount": 5000,
        "callback_url": "",
    }
    body = json.dumps(payload, separators=(",", ":"))
    ts = str(int(time.time()))
    created = await client.post(
        "/api_merchant/create_order_payin",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Timestamp": ts,
            "X-Signature": _sign(secret, body, ts),
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["status_pending"] == "error"
    assert "No accepting" in created.json().get("error", "")

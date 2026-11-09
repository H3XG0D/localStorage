"""Merchant HMAC payin: create → bill from trader card → get → cancel."""
import hashlib
import hmac
import json
import time

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


def _sign(secret: str, body: str, ts: str) -> str:
    return hmac.new(secret.encode(), (ts + body).encode(), hashlib.sha256).hexdigest()


async def _admin_set_rate(client: AsyncClient) -> None:
    token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/rates/working",
        headers=auth_headers(token),
        json={"rate": "90", "mode": "manual", "comment": "merchant test"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_merchant_create_get_cancel(client: AsyncClient, trader_user, admin_user, app_settings):
    await _admin_set_rate(client)
    ttok = await get_token(client, "trader_test", "Traderpass12")
    atok = await get_token(client, "admin_test", "Adminpass12")

    card = await client.post(
        "/trader/cards",
        headers=auth_headers(ttok),
        json={
            "name": "SBP merchant",
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

    partner = await client.post(
        "/admin/merchant-partners",
        headers=auth_headers(atok),
        json={"name": "lab-partner-test"},
    )
    assert partner.status_code == 201, partner.text
    api_key = partner.json()["api_key"]
    secret = partner.json()["secret"]
    assert api_key and secret

    payload = {
        "token": "P2P",
        "sub_token": "SBPRUB",
        "fingerprint": "1",
        "client_transaction_id": "merchant-test-1",
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
    data = created.json()
    assert data["status_pending"] == "ok"
    assert data["bill"]["method"] == "sbp"
    assert data["bill"]["reciver"] == "+79001112233"
    uuid_value = data["uuid"]

    get_payload = json.dumps({"uuid": uuid_value}, separators=(",", ":"))
    ts2 = str(int(time.time()))
    got = await client.post(
        "/api_merchant/get_order",
        content=get_payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Timestamp": ts2,
            "X-Signature": _sign(secret, get_payload, ts2),
        },
    )
    assert got.status_code == 200
    assert got.json()["uuid"] == uuid_value

    cancel_payload = json.dumps({"uuid": uuid_value}, separators=(",", ":"))
    ts3 = str(int(time.time()))
    cancelled = await client.post(
        "/api_merchant/cancel_order_payin",
        content=cancel_payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Timestamp": ts3,
            "X-Signature": _sign(secret, cancel_payload, ts3),
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_payin_set_check_creates_zaliv(
    client: AsyncClient, trader_user, admin_user, app_settings, monkeypatch
):
    await _admin_set_rate(client)
    ttok = await get_token(client, "trader_test", "Traderpass12")
    atok = await get_token(client, "admin_test", "Adminpass12")

    card = await client.post(
        "/trader/cards",
        headers=auth_headers(ttok),
        json={
            "name": "SBP check",
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
    session_id = card.json()["linked_requisite_id"]
    assert session_id

    partner = await client.post(
        "/admin/merchant-partners",
        headers=auth_headers(atok),
        json={"name": "lab-partner-check"},
    )
    api_key = partner.json()["api_key"]
    secret = partner.json()["secret"]

    payload = {
        "token": "P2P",
        "sub_token": "SBPRUB",
        "fingerprint": "1",
        "client_transaction_id": "merchant-check-1",
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
    uuid_value = created.json()["uuid"]

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

    async def _fake_fetch(_url: str):
        return pdf, "application/pdf"

    monkeypatch.setattr("app.services.merchant_payin.fetch_check_bytes", _fake_fetch)

    check_body = json.dumps({"uuid": uuid_value, "file": "https://example.test/check.pdf"}, separators=(",", ":"))
    ts2 = str(int(time.time()))
    checked = await client.post(
        "/api_merchant/payin_set_check",
        content=check_body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Timestamp": ts2,
            "X-Signature": _sign(secret, check_body, ts2),
        },
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["check"] == "ok"
    assert checked.json()["zaliv_id"]

    detail = await client.get(
        f"/trader/requisites/{session_id}",
        headers=auth_headers(ttok),
    )
    assert detail.status_code == 200, detail.text
    zalivs = detail.json()["zalivs"]
    assert len(zalivs) == 1
    assert zalivs[0]["amount"] in ("5000", "5000.00", 5000, "5000.0")


async def _create_sbp_card(client: AsyncClient, token: str, *, name: str, phone: str) -> dict:
    card = await client.post(
        "/trader/cards",
        headers=auth_headers(token),
        json={
            "name": name,
            "record_purchase_expense": False,
            "phone": phone,
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
    return card.json()


def _merchant_post(api_key: str, secret: str, payload: dict):
    body = json.dumps(payload, separators=(",", ":"))
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
        "X-Timestamp": ts,
        "X-Signature": _sign(secret, body, ts),
    }
    return body, headers


@pytest.mark.asyncio
async def test_payin_routes_new_vs_repeat_fingerprint(
    client: AsyncClient, trader_user, admin_user, app_settings, monkeypatch
):
    await _admin_set_rate(client)
    ttok = await get_token(client, "trader_test", "Traderpass12")
    atok = await get_token(client, "admin_test", "Adminpass12")

    regular = await _create_sbp_card(client, ttok, name="Regular pool", phone="+79001110002")
    new = await _create_sbp_card(client, ttok, name="New pool", phone="+79001110001")

    patched_new = await client.patch(
        f"/admin/cards/{new['id']}",
        headers=auth_headers(atok),
        json={"traffic_max_orders": 0},
    )
    assert patched_new.status_code == 200, patched_new.text
    assert patched_new.json()["traffic_max_orders"] == 0

    patched_reg = await client.patch(
        f"/admin/cards/{regular['id']}",
        headers=auth_headers(atok),
        json={"traffic_min_orders": 1},
    )
    assert patched_reg.status_code == 200, patched_reg.text

    partner = await client.post(
        "/admin/merchant-partners",
        headers=auth_headers(atok),
        json={"name": "lab-partner-traffic"},
    )
    assert partner.status_code == 201, partner.text
    api_key = partner.json()["api_key"]
    secret = partner.json()["secret"]

    listed = await client.get("/admin/merchant-partners", headers=auth_headers(atok))
    assert listed.status_code == 200
    assert any(p["id"] == partner.json()["id"] for p in listed.json())
    assert all(p.get("secret") in (None, "") for p in listed.json())

    payload = {
        "token": "P2P",
        "sub_token": "SBPRUB",
        "fingerprint": "fp-traffic-1",
        "client_transaction_id": "traffic-new-1",
        "amount": 5000,
        "callback_url": "",
    }
    body, headers = _merchant_post(api_key, secret, payload)
    created = await client.post("/api_merchant/create_order_payin", content=body, headers=headers)
    assert created.status_code == 200, created.text
    assert created.json()["status_pending"] == "ok"
    assert created.json()["bill"]["reciver"] == "+79001110001"
    uuid_value = created.json()["uuid"]

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"

    async def _fake_fetch(_url: str):
        return pdf, "application/pdf"

    monkeypatch.setattr("app.services.merchant_payin.fetch_check_bytes", _fake_fetch)

    check_body, check_headers = _merchant_post(
        api_key, secret,
        {"uuid": uuid_value, "file": "https://example.test/check.pdf"},
    )
    checked = await client.post("/api_merchant/payin_set_check", content=check_body, headers=check_headers)
    assert checked.status_code == 200, checked.text
    assert checked.json()["zaliv_id"]

    payload2 = {
        "token": "P2P",
        "sub_token": "SBPRUB",
        "fingerprint": "fp-traffic-1",
        "client_transaction_id": "traffic-repeat-1",
        "amount": 5000,
        "callback_url": "",
    }
    body2, headers2 = _merchant_post(api_key, secret, payload2)
    second = await client.post("/api_merchant/create_order_payin", content=body2, headers=headers2)
    assert second.status_code == 200, second.text
    assert second.json()["status_pending"] == "ok"
    assert second.json()["bill"]["reciver"] == "+79001110002"

    off = await client.patch(
        f"/admin/merchant-partners/{partner.json()['id']}",
        headers=auth_headers(atok),
        json={"is_active": False},
    )
    assert off.status_code == 200
    assert off.json()["is_active"] is False
    body3, headers3 = _merchant_post(api_key, secret, {
        **payload2,
        "client_transaction_id": "traffic-after-off",
    })
    denied = await client.post("/api_merchant/create_order_payin", content=body3, headers=headers3)
    assert denied.status_code == 401


@pytest.mark.asyncio
async def test_trader_cannot_patch_card_traffic(client: AsyncClient, trader_user, admin_user, app_settings):
    await _admin_set_rate(client)
    ttok = await get_token(client, "trader_test", "Traderpass12")
    card = await _create_sbp_card(client, ttok, name="No traffic edit", phone="+79001110009")
    resp = await client.patch(
        f"/admin/cards/{card['id']}",
        headers=auth_headers(ttok),
        json={"traffic_max_orders": 0},
    )
    assert resp.status_code == 403

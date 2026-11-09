"""Tests for /trader endpoints: requisites, zalivs, send_to_doliv, stats."""
import io
import pytest
from decimal import Decimal
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _trader_token(client: AsyncClient, trader_user) -> str:
    return await get_token(client, "trader_test", "Traderpass12")


def _fake_jpg() -> bytes:
    """Minimal valid JPEG header."""
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Requisite CRUD
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_requisite(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    resp = await client.post(
        "/trader/requisites",
        json={"name": "Test Card", "total_amount": 50000, "target_rate": 90.5},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Card"
    assert data["status"] == "active"
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_list_requisites(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    await client.post(
        "/trader/requisites",
        json={"name": "List Card", "total_amount": 10000, "target_rate": 88.0},
        headers=auth_headers(token),
    )
    resp = await client.get("/trader/requisites", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_requisite(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Detail Card", "total_amount": 30000, "target_rate": 91.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    resp = await client.get(f"/trader/requisites/{req_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == req_id
    assert data["zalivs"] == []
    assert data["zaliv_total"] == "0"


@pytest.mark.asyncio
async def test_get_requisite_not_found(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    resp = await client.get("/trader/requisites/999999", headers=auth_headers(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_requisite_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/trader/requisites",
        json={"name": "No Auth", "total_amount": 100, "target_rate": 90},
    )
    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# Zalivs
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_zaliv(client: AsyncClient, trader_user, app_settings, tmp_path):
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Zaliv Card", "total_amount": 20000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]

    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0", "profit_percent": "12"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    z = resp.json()
    assert Decimal(z["amount"]) == Decimal("5000")
    assert Decimal(z["profit_percent"]) == Decimal("12")


@pytest.mark.asyncio
async def test_add_zaliv_invalid_type(client: AsyncClient, trader_user, app_settings):
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Bad File Card", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "1000", "rate": "90.0", "profit_percent": "10"},
        files={"receipt": ("bad.exe", io.BytesIO(b"not an image"), "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "Invalid file type" in resp.json()["detail"] or "формат" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_zaliv_negative_amount(client: AsyncClient, trader_user, app_settings):
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Neg Zaliv", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "-100", "rate": "90.0", "profit_percent": "10"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_zaliv_exceeds_total_amount(client: AsyncClient, trader_user, app_settings):
    """Zaliv amount exceeding total_amount must be rejected with 400."""
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Overflow Zaliv", "total_amount": 1000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "2000", "rate": "90.0", "profit_percent": "10"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "exceeds remaining capacity" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_receipt_path_is_filename_only(client: AsyncClient, trader_user, app_settings):
    """The receipt_path in API responses must be a plain filename, not a server path."""
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Path Test", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    zaliv_resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "1000", "rate": "90.0", "profit_percent": "10"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    assert zaliv_resp.status_code == 201
    receipt_path = zaliv_resp.json()["receipt_path"]
    assert "/" not in receipt_path, f"Server path leaked: {receipt_path}"
    assert receipt_path.endswith(".jpg")


# ──────────────────────────────────────────────────────────────────────────────
# Send to doliv
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_to_doliv_no_zalivs_rejected(client: AsyncClient, trader_user):
    """Sending to doliv without any zalivs must be rejected."""
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Empty Send", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    resp = await client.post(f"/trader/requisites/{req_id}/send-to-doliv", headers=auth_headers(token))
    assert resp.status_code == 400
    assert "zaliv" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_send_to_doliv_after_zaliv(client: AsyncClient, trader_user, app_settings):
    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Send Card", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0", "profit_percent": "12"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    resp = await client.post(f"/trader/requisites/{req_id}/send-to-doliv", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["request_id"] is not None
    assert int(data["request_id"]) > 0
    assert Decimal(data["required_amount"]) == Decimal("5000")


@pytest.mark.asyncio
async def test_send_to_doliv_closed_requisite(client: AsyncClient, trader_user, db_session):
    from app.models import Requisite, RequisiteStatus
    from sqlalchemy import select

    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Closed Send", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]
    result = await db_session.execute(select(Requisite).where(Requisite.id == req_id))
    req = result.scalar_one()
    req.status = RequisiteStatus.closed
    await db_session.flush()

    resp = await client.post(f"/trader/requisites/{req_id}/send-to-doliv", headers=auth_headers(token))
    assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Trader stats
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trader_stats(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    resp = await client.get("/trader/stats", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_turnover" in data
    assert "total_profit" in data
    assert "requisites_count" in data


# ──────────────────────────────────────────────────────────────────────────────
# Doliv requests list
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trader_doliv_requests_empty(client: AsyncClient, trader_user):
    token = await _trader_token(client, trader_user)
    resp = await client.get("/trader/doliv-requests", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_add_zaliv_ignores_client_profit_percent(client: AsyncClient, trader_user, app_settings, db_session):
    """Server uses trader's fixed profit_percent, not the value sent by client."""
    from decimal import Decimal

    trader_user.profit_percent = Decimal("11")
    await db_session.flush()

    token = await _trader_token(client, trader_user)
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Fixed Profit Card", "total_amount": 20000, "target_rate": 90.0},
        headers=auth_headers(token),
    )
    req_id = create_resp.json()["id"]

    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0", "profit_percent": "99"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert Decimal(resp.json()["profit_percent"]) == Decimal("11")


@pytest.mark.asyncio
async def test_trader_settings_returns_profit_percent(client: AsyncClient, trader_user, app_settings):
    token = await _trader_token(client, trader_user)
    resp = await client.get("/trader/settings", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "profit_percent" in data
    assert Decimal(data["profit_percent"]) == Decimal("12")

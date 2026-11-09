"""Tests for /doliv endpoints: list requests, take, complete."""
import io
import pytest
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


async def _setup_pending_request(
    client: AsyncClient,
    trader_user,
    doliv_user,
    app_settings,
    total_amount: int = 10000,
    zaliv_amount: int = 5000,
) -> tuple[int, int]:
    """Create requisite, add zaliv, send to doliv. Returns (requisite_id, doliv_request_id)."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Doliv Test", "total_amount": total_amount, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]

    await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": str(zaliv_amount), "rate": "90.0", "profit_percent": "12"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )

    send_resp = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    assert send_resp.status_code == 200
    request_id = send_resp.json()["request_id"]
    return req_id, request_id


@pytest.mark.asyncio
async def test_list_doliv_requests_pending(client: AsyncClient, trader_user, doliv_user, app_settings):
    req_id, request_id = await _setup_pending_request(client, trader_user, doliv_user, app_settings)
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/doliv/requests", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert request_id in ids


@pytest.mark.asyncio
async def test_take_request(client: AsyncClient, trader_user, doliv_user, app_settings):
    req_id, request_id = await _setup_pending_request(client, trader_user, doliv_user, app_settings)
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    assert resp.json()["message"] == "Request taken"


@pytest.mark.asyncio
async def test_take_request_not_found(client: AsyncClient, doliv_user):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.post("/doliv/requests/999999/take", headers=auth_headers(doliv_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_take_request_double_take(client: AsyncClient, trader_user, doliv_user, app_settings):
    """Taking a request that's already in_progress should fail."""
    req_id, request_id = await _setup_pending_request(client, trader_user, doliv_user, app_settings)
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    first = await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    assert first.status_code == 200
    second = await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    assert second.status_code == 400
    assert "not available" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_complete_doliv(client: AsyncClient, trader_user, doliv_user, app_settings):
    req_id, request_id = await _setup_pending_request(
        client, trader_user, doliv_user, app_settings, total_amount=10000, zaliv_amount=5000
    )
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")

    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    resp = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("receipt.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["amount"]) == Decimal("5000")
    assert data["dolivshchik_name"] == "Doliv User"


@pytest.mark.asyncio
async def test_complete_doliv_wrong_user(client: AsyncClient, trader_user, doliv_user, app_settings, db_session):
    """A dolivshchik who didn't take the request cannot complete it."""
    from app.core.auth import hash_password
    from app.models import User, UserRole

    other = User(
        login="doliv_other",
        password_hash=hash_password("Otherpass12"),
        full_name="Other Doliv",
        role=UserRole.dolivshchik,
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()

    req_id, request_id = await _setup_pending_request(client, trader_user, doliv_user, app_settings)
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    other_token = await get_token(client, "doliv_other", "Otherpass12")
    resp = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_complete_doliv_double_completion(
    client: AsyncClient, trader_user, doliv_user, app_settings
):
    """Second complete on the same request must return 409."""
    req_id, request_id = await _setup_pending_request(client, trader_user, doliv_user, app_settings)
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    first = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )
    assert first.status_code == 200

    second = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )
    # Should be rejected: either 400 (not in progress) or 409 (already completed)
    assert second.status_code in (400, 409)


@pytest.mark.asyncio
async def test_doliv_history(client: AsyncClient, doliv_user):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/doliv/history", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_doliv_stats(client: AsyncClient, doliv_user):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/doliv/stats", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "dolivs_count" in data


@pytest.mark.asyncio
async def test_doliv_stats_includes_earnings_today(client: AsyncClient, doliv_user, app_settings):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/doliv/stats", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "salary_per_doliv_usdt" in data
    assert "dolivs_today" in data
    assert "earnings_today" in data
    assert Decimal(data["salary_per_doliv_usdt"]) == Decimal("1")


@pytest.mark.asyncio
async def test_doliv_settings_returns_salary_rate(client: AsyncClient, doliv_user, app_settings):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/doliv/settings", headers=auth_headers(doliv_token))
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["salary_per_doliv_usdt"]) == Decimal("1")
    assert data["currency"] == "RUB"

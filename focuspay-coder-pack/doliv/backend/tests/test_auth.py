"""Tests for /auth endpoints: login, /me, rate limiting."""
import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.models import LoginFailure
from tests.conftest import auth_headers, get_token


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, trader_user):
    resp = await client.post("/auth/login", json={"login": "trader_test", "password": "Traderpass12"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["access_token"]


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, trader_user):
    resp = await client.post("/auth/login", json={"login": "trader_test", "password": "wrongpass"})
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post("/auth/login", json={"login": "nobody", "password": "anything"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, db_session, trader_user):
    trader_user.is_active = False
    await db_session.flush()
    resp = await client.post("/auth/login", json={"login": "trader_test", "password": "Traderpass12"})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()
    trader_user.is_active = True
    await db_session.flush()


@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["login"] == "trader_test"
    assert data["role"] == "trader"


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_bad_token(client: AsyncClient):
    resp = await client.get("/auth/me", headers={"Authorization": "Bearer badtoken"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.post("/auth/refresh", headers=auth_headers(token))
    assert resp.status_code == 200
    new_token = resp.json()["access_token"]
    assert new_token

    me_resp = await client.get("/auth/me", headers=auth_headers(new_token))
    assert me_resp.status_code == 200
    assert me_resp.json()["login"] == "trader_test"


@pytest.mark.asyncio
async def test_login_strips_whitespace(client: AsyncClient, admin_user):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    await client.post(
        "/admin/users",
        json={
            "login": "ws_trader",
            "password": "Strongpass12",
            "full_name": "WS Trader",
            "role": "trader",
        },
        headers=auth_headers(admin_token),
    )
    resp = await client.post(
        "/auth/login",
        json={"login": " ws_trader ", "password": " Strongpass12 "},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.post("/auth/logout", headers=auth_headers(token))
    assert resp.status_code == 200
    assert "Logged out" in resp.json()["message"]


@pytest.mark.asyncio
async def test_logout_without_auth_clears_cookie(client: AsyncClient):
    resp = await client.post("/auth/logout")
    assert resp.status_code == 200
    assert "Logged out" in resp.json()["message"]


@pytest.mark.asyncio
async def test_rate_limit_after_many_failures(client: AsyncClient, trader_user, db_session):
    """After 10 failed attempts the endpoint should return 429."""
    await db_session.execute(delete(LoginFailure))
    await db_session.flush()

    for _ in range(10):
        await client.post(
            "/auth/login",
            json={"login": "trader_test", "password": "wrong"},
            headers={"X-Real-IP": "10.0.0.1"},
        )
    resp = await client.post(
        "/auth/login",
        json={"login": "trader_test", "password": "wrong"},
        headers={"X-Real-IP": "10.0.0.1"},
    )
    assert resp.status_code == 429

    await db_session.execute(delete(LoginFailure))
    await db_session.flush()

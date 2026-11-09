"""Tests for /owner endpoints: admin management, stats, access control."""
import pytest
from httpx import AsyncClient

from app.models import UserRole
from tests.conftest import _create_user, auth_headers, get_token


async def _owner_token(client: AsyncClient, owner_user) -> str:
    return await get_token(client, "owner_test", "Ownerpass12")


async def _admin_token(client: AsyncClient, admin_user) -> str:
    return await get_token(client, "admin_test", "Adminpass12")


@pytest.mark.asyncio
async def test_owner_creates_admin(client: AsyncClient, owner_user, admin_user):
    token = await _owner_token(client, owner_user)
    resp = await client.post(
        "/owner/admins",
        json={"login": "new_admin", "password": "Adminpass121", "full_name": "New Admin"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["login"] == "new_admin"
    assert data["role"] == "admin"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_owner_deactivates_and_reactivates_admin(client: AsyncClient, owner_user, admin_user):
    token = await _owner_token(client, owner_user)

    # Need a second active admin so we can deactivate admin_test
    second = await client.post(
        "/owner/admins",
        json={"login": "admin_backup", "password": "Backuppass12", "full_name": "Backup Admin"},
        headers=auth_headers(token),
    )
    assert second.status_code == 201

    off_resp = await client.patch(
        f"/owner/admins/{admin_user.id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert off_resp.status_code == 200
    assert off_resp.json()["is_active"] is False

    login_resp = await client.post(
        "/auth/login",
        json={"login": "admin_test", "password": "Adminpass12"},
    )
    assert login_resp.status_code == 403

    on_resp = await client.patch(
        f"/owner/admins/{admin_user.id}",
        json={"is_active": True},
        headers=auth_headers(token),
    )
    assert on_resp.status_code == 200
    assert on_resp.json()["is_active"] is True

    login_resp2 = await client.post(
        "/auth/login",
        json={"login": "admin_test", "password": "Adminpass12"},
    )
    assert login_resp2.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_create_admin(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.post(
        "/admin/users",
        json={"login": "blocked_admin", "password": "Strongpass12", "full_name": "Blocked", "role": "admin"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_modify_owner(client: AsyncClient, owner_user, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.patch(
        f"/admin/users/{owner_user.id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_access_admin_users(client: AsyncClient, owner_user, admin_user):
    token = await _owner_token(client, owner_user)
    resp = await client.get("/admin/users", headers=auth_headers(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_stats_overview(client: AsyncClient, owner_user, admin_user):
    token = await _owner_token(client, owner_user)
    resp = await client.get("/owner/stats/overview", headers=auth_headers(token))
    assert resp.status_code == 200
    assert "total_profit" in resp.json()


@pytest.mark.asyncio
async def test_owner_dashboard(client: AsyncClient, owner_user, admin_user):
    token = await _owner_token(client, owner_user)
    resp = await client.get("/owner/dashboard", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "admin_summary" in data
    assert data["admin_summary"]["total"] >= 1


@pytest.mark.asyncio
async def test_admin_cannot_access_owner_admins(client: AsyncClient, owner_user, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/owner/admins", headers=auth_headers(token))
    assert resp.status_code == 403

    resp_post = await client.post(
        "/owner/admins",
        json={"login": "hacker_admin", "password": "Hackpass12xx", "full_name": "Hacker"},
        headers=auth_headers(token),
    )
    assert resp_post.status_code == 403


@pytest.mark.asyncio
async def test_cannot_deactivate_last_active_admin(client: AsyncClient, db_session):
    owner = await _create_user(db_session, "owner_solo", "Ownerpass12", "Owner Solo", UserRole.owner)
    admin = await _create_user(db_session, "solo_admin", "Adminpass12", "Solo Admin", UserRole.admin)
    await db_session.flush()

    owner_token = await get_token(client, "owner_solo", "Ownerpass12")
    resp = await client.patch(
        f"/owner/admins/{admin.id}",
        json={"is_active": False},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 400

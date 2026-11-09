"""Tests for archive requisite, admin assign/cancel doliv request, admin analytics, roles.

Covers backend features that have no frontend UI yet:
- POST /trader/requisites/{id}/archive
- POST /admin/doliv-requests/{id}/assign
- POST /admin/doliv-requests/{id}/cancel
- GET /admin/analytics/*
- GET/PATCH /admin/roles
- Admin deactivate user
"""
import io
import pytest
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Requisite, RequisiteStatus
from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


async def _add_zaliv(client: AsyncClient, trader_token: str, req_id: int, amount: str = "3000") -> None:
    resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": amount, "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    assert resp.status_code == 201, resp.text


# ──────────────────────────────────────────────────────────────────────────────
# Archive requisite
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_closed_requisite(
    client: AsyncClient, trader_user, doliv_user, admin_user, app_settings
):
    """Trader can archive a closed requisite."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")

    # Create and close a requisite via full workflow
    r = (await client.post(
        "/trader/requisites",
        json={"name": "Archive Me", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    req_id = r["id"]

    await _add_zaliv(client, trader_token, req_id, "5000")

    send = (await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )

    # Now archive
    archive_resp = await client.post(
        f"/trader/requisites/{req_id}/archive",
        headers=auth_headers(trader_token),
    )
    assert archive_resp.status_code == 200, archive_resp.text
    assert archive_resp.json()["message"] == "Archived"

    # Verify status changed
    detail = await client.get(
        f"/trader/requisites/{req_id}", headers=auth_headers(trader_token)
    )
    assert detail.json()["status"] == "archive"


@pytest.mark.asyncio
async def test_cannot_archive_active_requisite(client: AsyncClient, trader_user):
    """Archiving an active requisite must fail."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Active Card", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()

    resp = await client.post(
        f"/trader/requisites/{r['id']}/archive",
        headers=auth_headers(trader_token),
    )
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_archive_another_traders_requisite(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    """Trader cannot archive a requisite that belongs to another trader."""
    from app.core.auth import hash_password
    from app.models import User, UserRole

    other = User(
        login="trader_other",
        password_hash=hash_password("Otherpass12"),
        full_name="Other Trader",
        role=UserRole.trader,
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()

    # Create requisite as trader_test, try to archive as trader_other
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    r = (await client.post(
        "/trader/requisites",
        json={"name": "Not Yours", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()

    other_token = await get_token(client, "trader_other", "Otherpass12")
    resp = await client.post(
        f"/trader/requisites/{r['id']}/archive",
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Admin assign doliv request
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_assign_doliv_request(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Admin assigns a pending doliv request to a specific dolivshchik."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Assign Test", "total_amount": 8000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    req_id = r["id"]

    await _add_zaliv(client, trader_token, req_id, "3000")

    send = (await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    assign_resp = await client.post(
        f"/admin/doliv-requests/{request_id}/assign",
        json={"dolivshchik_id": doliv_user.id},
        headers=auth_headers(admin_token),
    )
    assert assign_resp.status_code == 200, assign_resp.text
    data = assign_resp.json()
    assert data["status"] == "in_progress"
    assert data["assigned_dolivshchik_id"] == doliv_user.id
    assert data["assigned_dolivshchik_name"] == "Doliv User"


@pytest.mark.asyncio
async def test_admin_cannot_reassign_in_progress_request(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Admin cannot hijack a request already taken by a dolivshchik."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Reassign Block", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    await _add_zaliv(client, trader_token, r["id"], "5000")
    send = (await client.post(
        f"/trader/requisites/{r['id']}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    resp = await client.post(
        f"/admin/doliv-requests/{request_id}/assign",
        json={"dolivshchik_id": doliv_user.id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
    assert "in progress" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_assign_nonexistent_request(client: AsyncClient, admin_user, doliv_user):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.post(
        "/admin/doliv-requests/999999/assign",
        json={"dolivshchik_id": doliv_user.id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_assign_invalid_dolivshchik(
    client: AsyncClient, admin_user, trader_user, app_settings
):
    """Assigning request to non-dolivshchik user must fail."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Bad Assign", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    await _add_zaliv(client, trader_token, r["id"])
    send = (await client.post(
        f"/trader/requisites/{r['id']}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()

    # Assign to the trader (wrong role)
    resp = await client.post(
        f"/admin/doliv-requests/{send['request_id']}/assign",
        json={"dolivshchik_id": trader_user.id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Admin cancel doliv request
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cancel_doliv_request(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Admin cancels a pending request, requisite reverts to active/in_work."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Cancel Test", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    req_id = r["id"]

    await _add_zaliv(client, trader_token, req_id)

    send = (await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    cancel_resp = await client.post(
        f"/admin/doliv-requests/{request_id}/cancel",
        headers=auth_headers(admin_token),
    )
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert cancel_resp.json()["status"] == "cancelled"

    # Requisite should revert to in_work after partial zaliv
    detail = await client.get(
        f"/trader/requisites/{req_id}", headers=auth_headers(trader_token)
    )
    assert detail.json()["status"] == "in_work"


@pytest.mark.asyncio
async def test_admin_cancel_completed_request_fails(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Cannot cancel a completed request."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Cancel Completed", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    req_id = r["id"]

    await _add_zaliv(client, trader_token, req_id, "5000")

    send = (await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )

    cancel_resp = await client.post(
        f"/admin/doliv-requests/{request_id}/cancel",
        headers=auth_headers(admin_token),
    )
    assert cancel_resp.status_code == 400
    assert "completed" in cancel_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_cancel_idempotent(
    client: AsyncClient, admin_user, trader_user, app_settings
):
    """Cancelling already-cancelled request returns 200 (idempotent)."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Idempotent Cancel", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    await _add_zaliv(client, trader_token, r["id"])
    send = (await client.post(
        f"/trader/requisites/{r['id']}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    await client.post(f"/admin/doliv-requests/{request_id}/cancel", headers=auth_headers(admin_token))
    second = await client.post(
        f"/admin/doliv-requests/{request_id}/cancel",
        headers=auth_headers(admin_token),
    )
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"


# ──────────────────────────────────────────────────────────────────────────────
# Deactivate requisite
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deactivate_active_requisite(client: AsyncClient, trader_user):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    r = (await client.post(
        "/trader/requisites",
        json={"name": "Deactivate Active", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()

    resp = await client.post(
        f"/trader/requisites/{r['id']}/deactivate",
        headers=auth_headers(trader_token),
    )
    assert resp.status_code == 200
    detail = await client.get(
        f"/trader/requisites/{r['id']}", headers=auth_headers(trader_token)
    )
    assert detail.json()["status"] == "archive"


@pytest.mark.asyncio
async def test_deactivate_awaiting_doliv_cancels_request(
    client: AsyncClient, trader_user, admin_user, app_settings
):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Cancel On Deactivate", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    await _add_zaliv(client, trader_token, r["id"])
    send = (await client.post(
        f"/trader/requisites/{r['id']}/send-to-doliv",
        headers=auth_headers(trader_token),
    )).json()
    request_id = send["request_id"]

    resp = await client.post(
        f"/trader/requisites/{r['id']}/deactivate",
        headers=auth_headers(trader_token),
    )
    assert resp.status_code == 200

    detail = await client.get(
        f"/trader/requisites/{r['id']}", headers=auth_headers(trader_token)
    )
    assert detail.json()["status"] == "archive"

    req_resp = await client.get(
        f"/admin/doliv-requests", headers=auth_headers(admin_token)
    )
    cancelled = next((x for x in req_resp.json() if x["id"] == request_id), None)
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_admin_deactivate_requisite(
    client: AsyncClient, admin_user, trader_user
):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    r = (await client.post(
        "/trader/requisites",
        json={"name": "Admin Deactivate", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()

    resp = await client.post(
        f"/admin/requisites/{r['id']}/deactivate",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    detail = await client.get(
        f"/admin/requisites/{r['id']}", headers=auth_headers(admin_token)
    )
    assert detail.json()["status"] == "archive"


# ──────────────────────────────────────────────────────────────────────────────
# Admin roles
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_get_roles(client: AsyncClient, admin_user, app_settings):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/roles", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    roles = [row["role"] for row in data]
    assert "admin" in roles
    assert "trader" in roles
    assert "dolivshchik" in roles


@pytest.mark.asyncio
async def test_admin_patch_roles_read_only(client: AsyncClient, admin_user, app_settings):
    """Role permission matrix is read-only at the API level."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    get_resp = await client.get("/admin/roles", headers=auth_headers(admin_token))
    assert get_resp.status_code == 200

    patch_resp = await client.patch(
        "/admin/roles/trader",
        json={"permissions": {"Реквизиты": ["view", "create"]}},
        headers=auth_headers(admin_token),
    )
    assert patch_resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_get_roles(client: AsyncClient, trader_user):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/admin/roles", headers=auth_headers(trader_token))
    assert resp.status_code == 403


# ──────────────────────────────────────────────────────────────────────────────
# Admin deactivate user
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_deactivate_user(client: AsyncClient, admin_user, trader_user):
    """Admin can deactivate a user; deactivated user cannot login."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    # Deactivate the trader
    patch_resp = await client.patch(
        f"/admin/users/{trader_user.id}",
        json={"is_active": False},
        headers=auth_headers(admin_token),
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["is_active"] is False

    # Deactivated user cannot login
    login_resp = await client.post(
        "/auth/login",
        json={"login": "trader_test", "password": "Traderpass12"},
    )
    assert login_resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_change_user_full_name(client: AsyncClient, admin_user, doliv_user):
    """Admin can update a user's full_name."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    patch_resp = await client.patch(
        f"/admin/users/{doliv_user.id}",
        json={"full_name": "Новое Имя Долива"},
        headers=auth_headers(admin_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["full_name"] == "Новое Имя Долива"


@pytest.mark.asyncio
async def test_admin_change_user_role(client: AsyncClient, admin_user, doliv_user):
    """Admin can change a user's role."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    patch_resp = await client.patch(
        f"/admin/users/{doliv_user.id}",
        json={"role": "trader"},
        headers=auth_headers(admin_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["role"] == "trader"


# ──────────────────────────────────────────────────────────────────────────────
# Admin stats and analytics
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_overview_stats(client: AsyncClient, admin_user, app_settings):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/stats/overview", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_turnover" in data
    assert "total_profit" in data


@pytest.mark.asyncio
async def test_admin_traders_stats(client: AsyncClient, admin_user, trader_user, app_settings):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/stats/traders", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_dolivshchiks_stats(client: AsyncClient, admin_user, doliv_user, app_settings):
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/stats/dolivshchiks", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_activity_feed(client: AsyncClient, admin_user, app_settings):
    """Admin activity feed endpoint at /admin/activity."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/activity", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_dashboard_stats_structure(client: AsyncClient, admin_user, app_settings):
    """Dashboard stats returns status counts, totals, and profit distribution."""
    admin_token = await get_token(client, "admin_test", "Adminpass12")
    resp = await client.get("/admin/stats/dashboard", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_profit" in data
    assert "total_turnover" in data
    assert "active_requisites" in data
    assert "operations_today" in data
    assert "profit_distribution" in data


# ──────────────────────────────────────────────────────────────────────────────
# Access control
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trader_cannot_access_admin_routes(client: AsyncClient, trader_user):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    routes = [
        "/admin/users",
        "/admin/stats/overview",
        "/admin/settings",
        "/admin/roles",
    ]
    for route in routes:
        resp = await client.get(route, headers=auth_headers(trader_token))
        assert resp.status_code == 403, f"Expected 403 for {route}, got {resp.status_code}"


@pytest.mark.asyncio
async def test_doliv_cannot_access_trader_routes(client: AsyncClient, doliv_user):
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.get("/trader/requisites", headers=auth_headers(doliv_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_trader_cannot_access_doliv_routes(client: AsyncClient, trader_user):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/doliv/requests", headers=auth_headers(trader_token))
    assert resp.status_code == 403

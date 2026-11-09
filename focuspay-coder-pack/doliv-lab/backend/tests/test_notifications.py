"""Tests for /notifications endpoints.

Covers:
- List notifications (empty, with items)
- Unread count changes when notifications exist
- Mark single notification as read
- Mark all notifications as read
- User isolation (can't read another user's notification)
- Notifications are created when trader sends to doliv
"""
import io
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User
from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


async def _seed_notification(db: AsyncSession, user: User, is_read: bool = False) -> Notification:
    n = Notification(
        user_id=user.id,
        title="Тест уведомление",
        message="Тестовое тело",
        kind="test",
        is_read=is_read,
    )
    db.add(n)
    await db.flush()
    await db.refresh(n)
    return n


# ──────────────────────────────────────────────────────────────────────────────
# Basic CRUD
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_notifications_empty(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_notifications_with_items(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    await _seed_notification(db_session, trader_user)
    await _seed_notification(db_session, trader_user, is_read=True)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    titles = [n["title"] for n in data]
    assert all(t == "Тест уведомление" for t in titles)


@pytest.mark.asyncio
async def test_list_notifications_unread_only(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    await _seed_notification(db_session, trader_user, is_read=False)
    await _seed_notification(db_session, trader_user, is_read=True)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications?unread_only=true", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["is_read"] is False


@pytest.mark.asyncio
async def test_unread_count_zero_initially(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications/unread-count", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_unread_count_increases_with_notifications(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    await _seed_notification(db_session, trader_user, is_read=False)
    await _seed_notification(db_session, trader_user, is_read=False)
    await _seed_notification(db_session, trader_user, is_read=True)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications/unread-count", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.asyncio
async def test_mark_notification_read(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    n = await _seed_notification(db_session, trader_user, is_read=False)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.post(f"/notifications/{n.id}/read", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True

    # Unread count should now be 0
    count_resp = await client.get("/notifications/unread-count", headers=auth_headers(token))
    assert count_resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_notifications_read(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    await _seed_notification(db_session, trader_user, is_read=False)
    await _seed_notification(db_session, trader_user, is_read=False)
    await _seed_notification(db_session, trader_user, is_read=False)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.post("/notifications/read-all", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["updated"] == 3

    count_resp = await client.get("/notifications/unread-count", headers=auth_headers(token))
    assert count_resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_already_read_returns_zero(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    await _seed_notification(db_session, trader_user, is_read=True)
    await _seed_notification(db_session, trader_user, is_read=True)

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.post("/notifications/read-all", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["updated"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# User isolation
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_cannot_read_another_users_notification(
    client: AsyncClient, trader_user, doliv_user, db_session: AsyncSession
):
    """Trader's notification must not be accessible by dolivshchik."""
    n = await _seed_notification(db_session, trader_user)

    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    resp = await client.post(f"/notifications/{n.id}/read", headers=auth_headers(doliv_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_notifications_isolated_per_user(
    client: AsyncClient, trader_user, doliv_user, db_session: AsyncSession
):
    """Each user sees only their own notifications."""
    await _seed_notification(db_session, trader_user)
    await _seed_notification(db_session, trader_user)
    await _seed_notification(db_session, doliv_user)

    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")

    trader_notifs = await client.get("/notifications", headers=auth_headers(trader_token))
    doliv_notifs = await client.get("/notifications", headers=auth_headers(doliv_token))

    assert len(trader_notifs.json()) == 2
    assert len(doliv_notifs.json()) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Notifications created by business actions
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_to_doliv_creates_notifications_for_dolivshchik(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Sending a requisite to doliv notifies the dolivshchik role."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Notify Test Card", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]

    zaliv = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "3000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    assert zaliv.status_code == 201

    await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )

    # Dolivshchik should have a notification
    doliv_notifs = await client.get("/notifications", headers=auth_headers(doliv_token))
    assert doliv_notifs.status_code == 200
    assert len(doliv_notifs.json()) >= 1
    kinds = [n["kind"] for n in doliv_notifs.json()]
    assert "doliv_request" in kinds

    # Admin should also have a notification
    admin_notifs = await client.get("/notifications", headers=auth_headers(admin_token))
    assert admin_notifs.status_code == 200
    assert len(admin_notifs.json()) >= 1

    # Unread count for dolivshchik should be >= 1
    count = await client.get("/notifications/unread-count", headers=auth_headers(doliv_token))
    assert count.json()["count"] >= 1


@pytest.mark.asyncio
async def test_notification_limit_param(
    client: AsyncClient, trader_user, db_session: AsyncSession
):
    """The ?limit= parameter should cap results."""
    for i in range(10):
        n = Notification(
            user_id=trader_user.id,
            title=f"Notif {i}",
            message="body",
            kind="test",
        )
        db_session.add(n)
    await db_session.flush()

    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/notifications?limit=3", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_notifications_require_auth(client: AsyncClient):
    """Notifications endpoints require a valid JWT."""
    resp = await client.get("/notifications")
    assert resp.status_code == 401

    resp2 = await client.get("/notifications/unread-count")
    assert resp2.status_code == 401

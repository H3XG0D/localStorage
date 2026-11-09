"""Tests for security audit fixes: net_profit, doliv amount, statements, token invalidation."""
import io
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FakeCheck, Requisite, RequisiteStatus, UserRole
from app.services.stats import get_overview_stats
from tests.conftest import _create_user, auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


@pytest.mark.asyncio
async def test_net_profit_excludes_double_doliv_loss(db_session: AsyncSession):
    """final_profit already includes doliv_profit_loss; net_profit must not subtract doliv_loss again."""
    overview = await get_overview_stats(db_session)
    if not overview.profit_by_day:
        pytest.skip("No deal data in test DB")
    for day in overview.profit_by_day:
        profit = day["profit"]
        fc_loss = day.get("fake_check_loss", 0)
        doliv_loss = day.get("doliv_loss", 0)
        net = day["net_profit"]
        assert net == round(profit - fc_loss, 2)
        assert net != round(profit - fc_loss - doliv_loss, 2) or doliv_loss == 0


@pytest.mark.asyncio
async def test_overview_total_profit_matches_daily_sum(db_session: AsyncSession):
    """total_profit must equal the sum of profit_by_day (same aggregation source)."""
    overview = await get_overview_stats(db_session)
    if not overview.profit_by_day:
        pytest.skip("No deal data in test DB")
    day_sum = sum(Decimal(str(d["profit"])) for d in overview.profit_by_day)
    assert overview.total_profit == day_sum.quantize(Decimal("0.01"))


@pytest.mark.asyncio
async def test_complete_doliv_rejects_wrong_amount(
    client: AsyncClient, trader_user, doliv_user, app_settings
):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Amount Test", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]
    await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    send_resp = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    request_id = send_resp.json()["request_id"]
    required = Decimal(send_resp.json()["required_amount"])

    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    bad_resp = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": str(required + 1), "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )
    assert bad_resp.status_code == 400


@pytest.mark.asyncio
async def test_statements_deduct_fake_check_loss(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings, db_session
):
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "FC Stmt", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]
    await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    send = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    request_id = send.json()["request_id"]

    admin_token = await get_token(client, "admin_test", "Adminpass12")
    await client.post(
        f"/admin/requisites/{req_id}/fake-checks",
        data={
            "rate": "90",
            "operation_date": "2024-06-01",
            "amount_usdt": "5.00",
        },
        headers=auth_headers(admin_token),
    )

    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))
    await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )

    resp = await client.get("/admin/statements", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    items = {i["item"]: i["amount"] for i in resp.json()["items"]}
    assert "Фейк-чеки" in items
    assert Decimal(str(items["Фейк-чеки"])) >= Decimal("5")


@pytest.mark.asyncio
async def test_password_change_invalidates_token(client: AsyncClient, admin_user, db_session):
    target = await _create_user(db_session, "pw_target", "oldpass", "PW Target", UserRole.trader)
    await db_session.flush()

    token = await get_token(client, "pw_target", "oldpass")
    me = await client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200

    admin_token = await get_token(client, "admin_test", "Adminpass12")
    patch = await client.patch(
        f"/admin/users/{target.id}",
        json={"password": "Newpass991234"},
        headers=auth_headers(admin_token),
    )
    assert patch.status_code == 200

    stale = await client.get("/auth/me", headers=auth_headers(token))
    assert stale.status_code == 401

    new_token = await get_token(client, "pw_target", "Newpass991234")
    fresh = await client.get("/auth/me", headers=auth_headers(new_token))
    assert fresh.status_code == 200

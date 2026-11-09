"""Tests for /admin endpoints: users, requisites, settings, dashboard."""
import pytest
from decimal import Decimal
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


async def _admin_token(client: AsyncClient, admin_user) -> str:
    return await get_token(client, "admin_test", "Adminpass12")


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient, admin_user, trader_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/users", headers=auth_headers(token))
    assert resp.status_code == 200
    logins = [u["login"] for u in resp.json()]
    assert "trader_test" in logins


@pytest.mark.asyncio
async def test_admin_create_user(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.post(
        "/admin/users",
        json={"login": "new_trader", "password": "Strongpass12", "full_name": "New Trader", "role": "trader"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["login"] == "new_trader"


@pytest.mark.asyncio
async def test_create_trader_can_login(client: AsyncClient, admin_user):
    """Newly created trader must be able to log in with the same credentials."""
    admin_token = await _admin_token(client, admin_user)
    create_resp = await client.post(
        "/admin/users",
        json={
            "login": "fresh_trader",
            "password": "Freshtrader12",
            "full_name": "Fresh Trader",
            "role": "trader",
        },
        headers=auth_headers(admin_token),
    )
    assert create_resp.status_code == 201

    login_resp = await client.post(
        "/auth/login",
        json={"login": "fresh_trader", "password": "Freshtrader12"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


@pytest.mark.asyncio
async def test_create_user_strips_password_whitespace(client: AsyncClient, admin_user):
    """Trailing spaces in password at create time must not break login."""
    admin_token = await _admin_token(client, admin_user)
    await client.post(
        "/admin/users",
        json={
            "login": "trim_trader",
            "password": "Strongpass12 ",
            "full_name": "Trim Trader",
            "role": "trader",
        },
        headers=auth_headers(admin_token),
    )
    login_resp = await client.post(
        "/auth/login",
        json={"login": "trim_trader", "password": "Strongpass12"},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_create_duplicate_user(client: AsyncClient, admin_user, trader_user):
    token = await _admin_token(client, admin_user)
    resp = await client.post(
        "/admin/users",
        json={"login": "trader_test", "password": "Strongpass12", "full_name": "Dup", "role": "trader"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_update_user(client: AsyncClient, admin_user, trader_user):
    token = await _admin_token(client, admin_user)
    resp = await client.patch(
        f"/admin/users/{trader_user.id}",
        json={"full_name": "Updated Trader"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated Trader"


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin(client: AsyncClient, trader_user):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/admin/users", headers=auth_headers(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_requisites(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/requisites", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_dashboard_stats(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/stats/dashboard", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "total_turnover" in data
    assert "profit_by_day" in data


@pytest.mark.asyncio
async def test_admin_settings_read(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/settings", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "currency" in data
    assert "max_upload_mb" in data
    assert isinstance(data["receipt_formats"], list)


@pytest.mark.asyncio
async def test_admin_settings_update(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.patch(
        "/admin/settings",
        json={"max_upload_mb": 5, "currency": "USD"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_upload_mb"] == 5
    assert data["currency"] == "USD"


@pytest.mark.asyncio
async def test_admin_employees(client: AsyncClient, admin_user, trader_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/employees", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_salaries(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/salaries", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_admin_statements(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/statements", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert "cards" in data
    assert "items" in data


@pytest.mark.asyncio
async def test_admin_doliv_requests(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/doliv-requests", headers=auth_headers(token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_last_admin_cannot_be_demoted(client: AsyncClient, admin_user):
    """Cannot demote or deactivate the only remaining admin."""
    token = await _admin_token(client, admin_user)
    resp = await client.patch(
        f"/admin/users/{admin_user.id}",
        json={"role": "trader"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_last_admin_cannot_be_deactivated(client: AsyncClient, admin_user):
    token = await _admin_token(client, admin_user)
    resp = await client.patch(
        f"/admin/users/{admin_user.id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400
    assert "last active admin" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_salaries_invalid_date(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/salaries?start=not-a-date", headers=auth_headers(token))
    assert resp.status_code == 400
    assert "Invalid date format" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_statements_invalid_date(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/statements?end=baddate", headers=auth_headers(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_create_trader_with_profit_percent(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.post(
        "/admin/users",
        json={
            "login": "trader11",
            "password": "Strongpass12",
            "full_name": "Trader 11%",
            "role": "trader",
            "profit_percent": "11",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert Decimal(resp.json()["profit_percent"]) == Decimal("11")


@pytest.mark.asyncio
async def test_admin_update_trader_profit_recalcs_zalivs(
    client: AsyncClient, admin_user, trader_user, app_settings
):
    import io
    from decimal import Decimal

    from tests.test_trader import _fake_jpg

    trader_token = await get_token(client, "trader_test", "Traderpass12")
    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Recalc Card", "total_amount": 20000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]
    zaliv_resp = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    assert zaliv_resp.status_code == 201
    assert Decimal(zaliv_resp.json()["profit_percent"]) == Decimal("12")

    admin_token = await _admin_token(client, admin_user)
    patch_resp = await client.patch(
        f"/admin/users/{trader_user.id}",
        json={"profit_percent": "15"},
        headers=auth_headers(admin_token),
    )
    assert patch_resp.status_code == 200
    assert Decimal(patch_resp.json()["profit_percent"]) == Decimal("15")

    detail = await client.get(
        f"/trader/requisites/{req_id}",
        headers=auth_headers(trader_token),
    )
    assert Decimal(detail.json()["zalivs"][0]["profit_percent"]) == Decimal("15")


@pytest.mark.asyncio
async def test_admin_create_dolivshchik_with_salary(client: AsyncClient, admin_user, app_settings):
    token = await _admin_token(client, admin_user)
    resp = await client.post(
        "/admin/users",
        json={
            "login": "doliv5",
            "password": "Strongpass12",
            "full_name": "Doliv 5 USDT",
            "role": "dolivshchik",
            "doliv_salary_usdt": "5",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert Decimal(resp.json()["doliv_salary_usdt"]) == Decimal("5")


@pytest.mark.asyncio
async def test_salary_uses_per_dolivshchik_rate(
    client: AsyncClient, admin_user, doliv_user, app_settings, db_session
):
    doliv_user.doliv_salary_usdt = Decimal("3")
    await db_session.flush()

    token = await _admin_token(client, admin_user)
    resp = await client.get("/admin/salaries", headers=auth_headers(token))
    assert resp.status_code == 200
    doliv_rows = [r for r in resp.json() if r["role"] == "dolivshchik"]
    assert len(doliv_rows) >= 1
    row = next(r for r in doliv_rows if r["user_id"] == doliv_user.id)
    assert "3 USDT/долив" in row["method"]

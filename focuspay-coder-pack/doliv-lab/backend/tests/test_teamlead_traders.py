"""Teamlead creates traders and sets profit_percent."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserRole
from tests.conftest import _create_user, auth_headers, get_token


@pytest.mark.asyncio
async def test_teamlead_creates_and_patches_trader(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    tl = await _create_user(db_session, "tl_create", "Teamleadpass12", "TL Create", UserRole.teamlead)
    tl.teamlead_percent = Decimal("12")
    await db_session.flush()

    other = await _create_user(db_session, "tl_other", "Teamleadpass99", "TL Other", UserRole.teamlead)
    await db_session.flush()

    tok = await get_token(client, "tl_create", "Teamleadpass12")
    headers = auth_headers(tok)

    me = await client.get("/teamlead/me", headers=headers)
    assert me.status_code == 200
    assert Decimal(me.json()["pool_percent"]) == Decimal("12")
    assert Decimal(me.json()["max_trader_percent"]) == Decimal("12")

    created = await client.post(
        "/teamlead/traders",
        headers=headers,
        json={
            "login": "tr_from_tl",
            "password": "Traderpass99x",
            "full_name": "Trader From TL",
            "profit_percent": "11",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["login"] == "tr_from_tl"
    assert Decimal(body["profit_percent"]) == Decimal("11")
    assert Decimal(body["teamlead_keep_percent"]) == Decimal("1")
    trader_id = body["id"]

    listed = await client.get("/teamlead/traders", headers=headers)
    assert listed.status_code == 200
    assert any(t["id"] == trader_id for t in listed.json())

    patched = await client.patch(
        f"/teamlead/traders/{trader_id}",
        headers=headers,
        json={"profit_percent": "9.5", "full_name": "Renamed"},
    )
    assert patched.status_code == 200, patched.text
    assert Decimal(patched.json()["profit_percent"]) == Decimal("9.5")
    assert patched.json()["full_name"] == "Renamed"
    assert Decimal(patched.json()["teamlead_keep_percent"]) == Decimal("2.5")

    # Other TL cannot patch
    other_tok = await get_token(client, "tl_other", "Teamleadpass99")
    denied = await client.patch(
        f"/teamlead/traders/{trader_id}",
        headers=auth_headers(other_tok),
        json={"profit_percent": "1"},
    )
    assert denied.status_code == 404

    summary = await client.get("/teamlead/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["traders_count"] == 1
    assert Decimal(summary.json()["pool_percent"]) == Decimal("12")

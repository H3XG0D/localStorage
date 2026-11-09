"""Personal tokens isolation (self-deposit removed — use wallet requests)."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserRole
from app.services import token_ledger
from tests.conftest import _create_user, auth_headers, get_token


@pytest.mark.asyncio
async def test_personal_tokens_isolated(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    tl = await _create_user(db_session, "tl_dep", "Teamleadpass12", "TL Dep", UserRole.teamlead)
    await token_ledger.ensure_personal_token(db_session, tl)
    trader = await _create_user(
        db_session, "tr_dep", "Traderpass12z", "Trader Dep", UserRole.trader
    )
    trader.teamlead_id = tl.id
    await db_session.flush()

    tok = await get_token(client, "tl_dep", "Teamleadpass12")
    created = await client.post(
        "/teamlead/traders",
        headers=auth_headers(tok),
        json={
            "login": "tr_personal",
            "password": "Traderpass99x",
            "full_name": "Personal",
            "profit_percent": "11",
        },
    )
    assert created.status_code == 201, created.text

    t1 = await get_token(client, "tr_personal", "Traderpass99x")
    t2 = await get_token(client, "tr_dep", "Traderpass12z")
    await token_ledger.ensure_personal_token(db_session, trader)
    await db_session.flush()

    w1 = await client.get("/trader/wallet", headers=auth_headers(t1))
    w2 = await client.get("/trader/wallet", headers=auth_headers(t2))
    assert w1.status_code == 200
    assert w2.status_code == 200
    assert w1.json()["id"] != w2.json()["id"]

    atok = await get_token(client, "admin_test", "Adminpass12")
    req = await client.post(
        "/trader/wallet/requests",
        headers=auth_headers(t1),
        json={"kind": "deposit", "amount_usdt": "50"},
    )
    assert req.status_code == 201, req.text
    ok = await client.post(
        f"/admin/wallet-requests/{req.json()['id']}/resolve",
        headers=auth_headers(atok),
        json={"approve": True},
    )
    assert ok.status_code == 200

    w1b = await client.get("/trader/wallet", headers=auth_headers(t1))
    w2b = await client.get("/trader/wallet", headers=auth_headers(t2))
    assert Decimal(w1b.json()["balance"]) == Decimal("50")
    assert Decimal(w2b.json()["balance"] or 0) == Decimal("0")


@pytest.mark.asyncio
async def test_teamlead_wallet_request(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    tl = await _create_user(db_session, "tl_wal", "Teamleadpass12", "TL Wal", UserRole.teamlead)
    tok = await get_token(client, "tl_wal", "Teamleadpass12")
    w = await client.get("/teamlead/wallet", headers=auth_headers(tok))
    assert w.status_code == 200, w.text
    req = await client.post(
        "/teamlead/wallet/requests",
        headers=auth_headers(tok),
        json={"kind": "deposit", "amount_usdt": "25"},
    )
    assert req.status_code == 201, req.text
    listed = await client.get("/teamlead/wallet/requests", headers=auth_headers(tok))
    assert listed.status_code == 200
    assert listed.json()[0]["kind"] == "deposit"
    assert Decimal(listed.json()[0]["amount_usdt"]) == Decimal("25")

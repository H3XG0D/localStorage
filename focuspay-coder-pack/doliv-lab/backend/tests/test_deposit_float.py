"""Working deposit, float, teamlead, payout, API keys."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models import User, UserRole, WorkToken
from app.services import token_ledger
from app.services.rapira import exposure_usdt
from tests.conftest import _create_user, _ensure_trader_token, auth_headers, get_token


@pytest.mark.asyncio
async def test_cannot_create_requisite_without_deposit(client: AsyncClient, db_session, app_settings):
    trader = await _create_user(db_session, "nodep", "Nodeposit12", "No Dep", UserRole.trader)
    token = await get_token(client, "nodep", "Nodeposit12")
    resp = await client.post(
        "/trader/requisites",
        headers=auth_headers(token),
        json={"name": "card", "total_amount": "18000", "target_rate": "90"},
    )
    assert resp.status_code == 400
    assert "work token" in resp.json()["detail"].lower() or "deposit" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_hold_blocks_over_exposure(client: AsyncClient, trader_user, app_settings, db_session):
    # trader_user has 10000 USDT; at rate 90 → max ~900000 RUB, use tiny deposit instead
    from app.models import TokenMember
    from sqlalchemy import select

    memb = (
        await db_session.execute(select(TokenMember).where(TokenMember.user_id == trader_user.id))
    ).scalar_one()
    # drain available by withdrawing almost all after checking
    bals = await token_ledger.compute_token_balances(db_session, memb.work_token_id)
    # Set balance low: debit down to 200 USDT available
    to_remove = bals["available"] - Decimal("200")
    if to_remove > 0:
        await token_ledger.withdraw(
            db_session,
            memb.work_token_id,
            to_remove,
            actor_id=None,
            idempotency_key="drain-for-test",
        )

    token = await get_token(client, "trader_test", "Traderpass12")
    # 200 USDT @ 90 = 18000 RUB max
    ok = await client.post(
        "/trader/requisites",
        headers=auth_headers(token),
        json={"name": "ok", "total_amount": "18000", "target_rate": "90"},
    )
    assert ok.status_code == 201, ok.text
    assert Decimal(ok.json()["hold_usdt"]) == exposure_usdt(Decimal("18000"), Decimal("90"))

    bad = await client.post(
        "/trader/requisites",
        headers=auth_headers(token),
        json={"name": "over", "total_amount": "50000", "target_rate": "90"},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_zaliv_increments_float_and_close_releases_hold(
    client: AsyncClient, trader_user, doliv_user, app_settings, db_session
):
    from io import BytesIO

    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")

    r = await client.post(
        "/trader/requisites",
        headers=auth_headers(trader_token),
        json={"name": "float-card", "total_amount": "10000", "target_rate": "90"},
    )
    assert r.status_code == 201
    req_id = r.json()["id"]
    hold = Decimal(r.json()["hold_usdt"])

    wallet_before = await client.get("/trader/wallet", headers=auth_headers(trader_token))
    held_before = Decimal(wallet_before.json()["held"])

    png = BytesIO(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    z = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        headers=auth_headers(trader_token),
        data={"amount": "7000", "rate": "90.0"},
        files={"receipt": ("r.png", png, "image/png")},
    )
    assert z.status_code == 201, z.text

    detail = await client.get(f"/trader/requisites/{req_id}", headers=auth_headers(trader_token))
    assert Decimal(detail.json()["float_rub"]) == Decimal("7000")

    float_sum = await client.get("/trader/float", headers=auth_headers(trader_token))
    assert Decimal(float_sum.json()["total_float_rub"]) >= Decimal("7000")

    await client.post(f"/trader/requisites/{req_id}/send-to-doliv", headers=auth_headers(trader_token))
    queue = await client.get("/doliv/requests", headers=auth_headers(doliv_token))
    request_id = next(x["id"] for x in queue.json() if x["requisite_id"] == req_id)
    await client.post(f"/doliv/requests/{request_id}/take", headers=auth_headers(doliv_token))

    png2 = BytesIO(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    done = await client.post(
        f"/doliv/requests/{request_id}/complete",
        headers=auth_headers(doliv_token),
        data={"amount": "3000", "rate": "90.0"},
        files={"receipt": ("d.png", png2, "image/png")},
    )
    assert done.status_code == 200, done.text

    closed = await client.get(f"/trader/requisites/{req_id}", headers=auth_headers(trader_token))
    assert closed.json()["status"] == "closed"
    assert Decimal(closed.json()["float_rub"]) == Decimal("0")

    wallet_after = await client.get("/trader/wallet", headers=auth_headers(trader_token))
    # hold released; trader credited zaliv_profit
    assert Decimal(wallet_after.json()["held"]) == held_before - hold
    assert Decimal(wallet_after.json()["balance"]) > Decimal(wallet_before.json()["balance"]) - Decimal("0.01")


@pytest.mark.asyncio
async def test_deposit_exempt_skips_hold(client: AsyncClient, db_session, app_settings):
    trader = await _create_user(
        db_session, "merchant", "Merchantpass1", "Merchant", UserRole.trader, deposit_exempt=True
    )
    token = await get_token(client, "merchant", "Merchantpass1")
    resp = await client.post(
        "/trader/requisites",
        headers=auth_headers(token),
        json={"name": "m", "total_amount": "500000", "target_rate": "90"},
    )
    assert resp.status_code == 201
    assert resp.json()["hold_usdt"] is None
    assert resp.json()["work_token_id"] is None


@pytest.mark.asyncio
async def test_teamlead_and_payout_and_api_key(client: AsyncClient, admin_user, trader_user, app_settings, db_session):
    tl = await _create_user(
        db_session, "tl_test", "Teamleadpass1", "TL", UserRole.teamlead, teamlead_percent=Decimal("2")
    )
    trader_user.teamlead_id = tl.id
    await db_session.flush()

    admin_token = await get_token(client, "admin_test", "Adminpass12")
    # create shared token for teamlead
    wt = await client.post(
        "/admin/work-tokens",
        headers=auth_headers(admin_token),
        json={"name": "team-token", "owner_id": tl.id, "member_user_ids": [tl.id]},
    )
    assert wt.status_code == 201
    tid = wt.json()["id"]
    await client.post(
        f"/admin/work-tokens/{tid}/deposit",
        headers=auth_headers(admin_token),
        json={"amount": "100", "idempotency_key": "tl-dep-1"},
    )

    key_resp = await client.post(
        f"/admin/work-tokens/{tid}/api-keys",
        headers=auth_headers(admin_token),
        json={"name": "integ"},
    )
    assert key_resp.status_code == 201
    raw_key = key_resp.json()["raw_key"]
    bal = await client.get("/integration/balance", headers={"X-API-Key": raw_key})
    assert bal.status_code == 200
    assert Decimal(bal.json()["balance"]) == Decimal("100")

    tl_token = await get_token(client, "tl_test", "Teamleadpass1")
    team = await client.get("/teamlead/traders", headers=auth_headers(tl_token))
    assert team.status_code == 200
    assert any(t["id"] == trader_user.id for t in team.json())

    trader_token = await get_token(client, "trader_test", "Traderpass12")
    payout = await client.post(
        "/trader/payout",
        headers=auth_headers(trader_token),
        json={"amount_usdt": "10", "idempotency_key": "payout-1"},
    )
    assert payout.status_code == 200
    assert Decimal(payout.json()["credited_bonus"]) == Decimal("0.1")


@pytest.mark.asyncio
async def test_rapira_rate_endpoint(client: AsyncClient, trader_user, app_settings):
    token = await get_token(client, "trader_test", "Traderpass12")
    resp = await client.get("/rates/rapira", headers=auth_headers(token))
    assert resp.status_code == 200
    assert Decimal(resp.json()["rate"]) > 0

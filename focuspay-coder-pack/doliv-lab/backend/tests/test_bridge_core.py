"""Wallet requests (admin approve) + payout jobs + bridge."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserRole
from app.services import token_ledger
from app.services.wallet_fees import fee_for_network
from app.models import CryptoNetwork
from tests.conftest import _create_user, auth_headers, get_token


def test_fee_by_network():
    assert fee_for_network(CryptoNetwork.usdt_trc20) == Decimal("3")
    assert fee_for_network(CryptoNetwork.btc) == Decimal("2")
    assert fee_for_network(CryptoNetwork.ltc) == Decimal("2")


@pytest.mark.asyncio
async def test_self_deposit_disabled(client: AsyncClient, app_settings, db_session: AsyncSession):
    trader = await _create_user(db_session, "tr_noself", "Traderpass12z", "T", UserRole.trader)
    await db_session.flush()
    tok = await get_token(client, "tr_noself", "Traderpass12z")
    r = await client.post(
        "/trader/wallet/deposit",
        headers=auth_headers(tok),
        json={"amount_usdt": "10"},
    )
    assert r.status_code == 400
    assert "request" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wallet_request_approve_withdraw_fee(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    trader = await _create_user(db_session, "tr_wr", "Traderpass12w", "TW", UserRole.trader)
    token = await token_ledger.ensure_personal_token(db_session, trader)
    await token_ledger.deposit(
        db_session, token.id, Decimal("100"), actor_id=None, idempotency_key="seed-wr"
    )
    await db_session.flush()

    ttok = await get_token(client, "tr_wr", "Traderpass12w")
    atok = await get_token(client, "admin_test", "Adminpass12")

    req = await client.post(
        "/trader/wallet/requests",
        headers=auth_headers(ttok),
        json={
            "kind": "withdraw",
            "amount_usdt": "10",
            "network": "usdt_trc20",
            "address": "TXabc",
        },
    )
    assert req.status_code == 201, req.text
    assert Decimal(req.json()["fee_usdt"]) == Decimal("3")
    rid = req.json()["id"]

    btc = await client.post(
        "/trader/wallet/requests",
        headers=auth_headers(ttok),
        json={"kind": "withdraw", "amount_usdt": "5", "network": "btc", "address": "bc1x"},
    )
    assert btc.status_code == 201
    assert Decimal(btc.json()["fee_usdt"]) == Decimal("2")

    ok = await client.post(
        f"/admin/wallet-requests/{rid}/resolve",
        headers=auth_headers(atok),
        json={"approve": True},
    )
    assert ok.status_code == 200, ok.text
    bals = await token_ledger.compute_token_balances(db_session, token.id)
    assert bals["available"] == Decimal("87")  # 100 - 10 - 3; btc still pending


@pytest.mark.asyncio
async def test_payout_job_claim_and_bridge(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    from app.models import Requisite, RequisiteStatus

    trader = await _create_user(db_session, "tr_pj", "Traderpass12p", "TP", UserRole.trader)
    await token_ledger.ensure_personal_token(db_session, trader)
    req = Requisite(
        trader_id=trader.id,
        name="float-sess",
        total_amount=Decimal("50000"),
        target_rate=Decimal("90"),
        status=RequisiteStatus.in_work,
        float_rub=Decimal("20000"),
    )
    db_session.add(req)
    await db_session.flush()

    atok = await get_token(client, "admin_test", "Adminpass12")
    ttok = await get_token(client, "tr_pj", "Traderpass12p")

    job = await client.post(
        "/admin/payout-jobs",
        headers=auth_headers(atok),
        json={
            "amount_rub": "15000",
            "pay_method": "sbp",
            "requisites": {"phone": "+7900"},
            "source": "manual",
        },
    )
    assert job.status_code == 201, job.text
    jid = job.json()["id"]

    claim = await client.post(
        f"/trader/payout-jobs/{jid}/claim",
        headers=auth_headers(ttok),
        json={"amount_rub": "15000"},
    )
    assert claim.status_code == 200, claim.text

    bk = await client.post("/admin/bridge-keys?name=test", headers=auth_headers(atok))
    assert bk.status_code == 201
    raw = bk.json()["raw_key"]
    bal = await client.get("/bridge/card-balances", headers={"X-Bridge-Key": raw})
    assert bal.status_code == 200
    assert Decimal(bal.json()["total_float_rub"]) >= Decimal("20000")

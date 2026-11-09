"""Teamlead pool: trader % capped; settle keep = pool - trader on turnover."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DealResult, Requisite, RequisiteStatus, UserRole, Zaliv
from app.services import token_ledger
from app.services.deal_settlement import settle_requisite_closed
from app.services.teamlead_pool import calc_teamlead_keep_usdt
from tests.conftest import _create_user, _ensure_trader_token, auth_headers, get_token


def test_calc_teamlead_keep_usdt_unit():
    z = MagicMock(spec=Zaliv)
    z.amount = Decimal("9000")
    z.profit_percent = Decimal("11")
    # pool 12 → keep 1% → 90 RUB / 90 rate = 1 USDT
    assert calc_teamlead_keep_usdt([z], pool=Decimal("12"), target_rate=Decimal("90")) == Decimal("1.000000")


@pytest.mark.asyncio
async def test_cannot_set_trader_above_pool(
    client: AsyncClient, app_settings, db_session: AsyncSession
):
    tl = await _create_user(db_session, "tl_pool", "Teamleadpass12", "TL Pool", UserRole.teamlead)
    tl.teamlead_percent = Decimal("12")
    await db_session.flush()

    tok = await get_token(client, "tl_pool", "Teamleadpass12")
    headers = auth_headers(tok)

    bad = await client.post(
        "/teamlead/traders",
        headers=headers,
        json={
            "login": "over_pool",
            "password": "Traderpass99x",
            "full_name": "Over",
            "profit_percent": "13",
        },
    )
    assert bad.status_code == 400
    assert "pool" in bad.json()["detail"].lower()

    ok = await client.post(
        "/teamlead/traders",
        headers=headers,
        json={
            "login": "in_pool",
            "password": "Traderpass99y",
            "full_name": "In",
            "profit_percent": "11",
        },
    )
    assert ok.status_code == 201, ok.text
    assert Decimal(ok.json()["teamlead_keep_percent"]) == Decimal("1")


@pytest.mark.asyncio
async def test_settle_credits_teamlead_keep_from_pool(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    """Close deal: trader 11% credit, TL keep 1% of turnover at target_rate."""
    tl = await _create_user(db_session, "tl_settle", "Teamleadpass12", "TL Settle", UserRole.teamlead)
    tl.teamlead_percent = Decimal("12")
    await _ensure_trader_token(db_session, tl, deposit=Decimal("10"))
    trader = await _create_user(
        db_session, "tr_settle", "Traderpass12z", "Trader Settle", UserRole.trader
    )
    trader.profit_percent = Decimal("11")
    trader.teamlead_id = tl.id
    await _ensure_trader_token(db_session, trader, deposit=Decimal("1000"))
    await db_session.flush()

    token = await token_ledger.get_active_token_for_user(db_session, trader.id)
    assert token
    req = Requisite(
        trader_id=trader.id,
        name="settle-test",
        total_amount=Decimal("9000"),
        target_rate=Decimal("90"),
        status=RequisiteStatus.closed,
        work_token_id=token.id,
        hold_usdt=Decimal("100"),
        float_rub=Decimal("0"),
    )
    db_session.add(req)
    await db_session.flush()
    z = Zaliv(
        requisite_id=req.id,
        amount=Decimal("9000"),
        rate=Decimal("90"),
        profit_percent=Decimal("11"),
        receipt_path="x.jpg",
    )
    db_session.add(z)
    deal = DealResult(
        requisite_id=req.id,
        total_turnover=Decimal("9000"),
        turnover_usdt=Decimal("100"),
        avg_rate=Decimal("90"),
        doliv_amount=Decimal("0"),
        doliv_rate=Decimal("0"),
        zaliv_profit=Decimal("11"),  # 9000*11%/90 = 11
        doliv_profit_loss=Decimal("0"),
        final_profit=Decimal("11"),
    )
    db_session.add(deal)
    await db_session.flush()

    tl_tok = await token_ledger.get_active_token_for_user(db_session, tl.id)
    assert tl_tok
    tl_before = await token_ledger.compute_token_balances(db_session, tl_tok.id)
    await settle_requisite_closed(db_session, req, deal, actor_id=admin_user.id)
    await db_session.flush()

    tl_after = await token_ledger.compute_token_balances(db_session, tl_tok.id)
    # keep 1% of 9000 / 90 = 1 USDT
    assert tl_after["balance"] - tl_before["balance"] == Decimal("1.000000")

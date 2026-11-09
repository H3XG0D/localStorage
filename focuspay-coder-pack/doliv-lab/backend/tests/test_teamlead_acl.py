"""Teamlead ACL: only own traders' cards/sessions; 403 on foreign."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole
from tests.conftest import _create_user, _ensure_trader_token, auth_headers, get_token


@pytest.mark.asyncio
async def test_teamlead_sees_only_own_traders_cards(
    client: AsyncClient, admin_user, app_settings, db_session: AsyncSession
):
    tl = await _create_user(db_session, "tl_acl", "Teamleadpass12", "TL ACL", UserRole.teamlead)
    own = await _create_user(db_session, "tr_own", "Traderpass12x", "Own Trader", UserRole.trader)
    own.teamlead_id = tl.id
    await _ensure_trader_token(db_session, own)
    foreign = await _create_user(db_session, "tr_foreign", "Traderpass12y", "Foreign", UserRole.trader)
    await _ensure_trader_token(db_session, foreign)
    await db_session.flush()

    # Foreign trader creates a card
    ft = await get_token(client, "tr_foreign", "Traderpass12y")
    card = await client.post(
        "/trader/cards",
        headers=auth_headers(ft),
        json={"name": "Foreign Card", "record_purchase_expense": False, "card_number": "4276123456785555"},
    )
    assert card.status_code == 201

    # Own trader creates a card
    ot = await get_token(client, "tr_own", "Traderpass12x")
    own_card = await client.post(
        "/trader/cards",
        headers=auth_headers(ot),
        json={"name": "Own Card", "record_purchase_expense": False, "card_number": "4276123456784444"},
    )
    assert own_card.status_code == 201

    tl_tok = await get_token(client, "tl_acl", "Teamleadpass12")
    headers = auth_headers(tl_tok)

    listed = await client.get("/admin/cards", headers=headers)
    assert listed.status_code == 200
    names = {c["name"] for c in listed.json()}
    assert "Own Card" in names
    assert "Foreign Card" not in names

    # Access foreign trader filter → 403
    denied = await client.get(f"/admin/cards?trader_id={foreign.id}", headers=headers)
    assert denied.status_code == 403

    # Sessions: foreign requisite not visible
    # Create session via legacy for foreign (needs office rate bootstrap)
    admin_tok = await get_token(client, "admin_test", "Adminpass12")
    await client.post(
        "/admin/rates/working",
        headers=auth_headers(admin_tok),
        json={"rate": "90", "mode": "manual"},
    )
    go = await client.post(
        f"/trader/cards/{card.json()['id']}/go-online",
        headers=auth_headers(ft),
        json={"accept_limit_rub": "900"},
    )
    assert go.status_code == 200, go.text
    sid = go.json()["session_id"]

    reqs = await client.get("/admin/requisites", headers=headers)
    assert reqs.status_code == 200
    assert all(r["id"] != sid for r in reqs.json())

    detail = await client.get(f"/admin/requisites/{sid}", headers=headers)
    assert detail.status_code == 403

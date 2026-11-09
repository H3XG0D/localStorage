"""Trader cards + expenses reduce net (commission − costs)."""
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services import token_ledger
from tests.conftest import auth_headers, get_token


@pytest.mark.asyncio
async def test_card_and_expense_debit_net(client: AsyncClient, trader_user, app_settings, db_session):
    token = await get_token(client, "trader_test", "Traderpass12")
    headers = auth_headers(token)

    before = await client.get("/trader/wallet", headers=headers)
    assert before.status_code == 200
    bal_before = Decimal(before.json()["balance"])

    card = await client.post(
        "/trader/cards",
        headers=headers,
        json={
            "name": "Tinkoff ****1234",
            "last4": "1234",
            "bank": "Tinkoff",
            "purchase_cost_rub": "9000",
            "rate": "90",
            "record_purchase_expense": True,
        },
    )
    assert card.status_code == 201, card.text
    assert card.json()["status"] == "active"
    # 9000/90 = 100 USDT expense
    assert Decimal(card.json()["expenses_usdt"]) == Decimal("100")

    after = await client.get("/trader/wallet", headers=headers)
    bal_after = Decimal(after.json()["balance"])
    assert bal_after == bal_before - Decimal("100")

    warm = await client.post(
        "/trader/expenses",
        headers=headers,
        json={
            "category": "warm",
            "amount_rub": "450",
            "rate": "90",
            "card_id": card.json()["id"],
            "comment": "прогрев",
        },
    )
    assert warm.status_code == 201, warm.text
    assert warm.json()["debited"] is True
    assert Decimal(warm.json()["amount_usdt"]) == Decimal("5")

    net = await client.get("/trader/net", headers=headers)
    assert net.status_code == 200
    assert Decimal(net.json()["expenses_usdt"]) == Decimal("105")
    assert Decimal(net.json()["expenses_rub"]) == Decimal("9450")

    block = await client.patch(
        f"/trader/cards/{card.json()['id']}",
        headers=headers,
        json={"status": "blocked"},
    )
    assert block.status_code == 200
    assert block.json()["status"] == "blocked"

    loss = await client.post(
        "/trader/expenses",
        headers=headers,
        json={
            "category": "block_loss",
            "amount_rub": "1800",
            "rate": "90",
            "card_id": card.json()["id"],
        },
    )
    assert loss.status_code == 201

    cards = await client.get("/trader/cards", headers=headers)
    assert any(c["id"] == card.json()["id"] and Decimal(c["expenses_usdt"]) == Decimal("125") for c in cards.json()["items"])

    cur = await client.patch(
        "/trader/settings/display-currency",
        headers=headers,
        json={"display_currency": "USDT"},
    )
    assert cur.status_code == 200
    assert cur.json()["display_currency"] == "USDT"

    settings = await client.get("/trader/settings", headers=headers)
    assert settings.json()["display_currency"] == "USDT"


@pytest.mark.asyncio
async def test_expense_without_token_is_accounting_only(client: AsyncClient, db_session, app_settings):
    from tests.conftest import _create_user
    from app.models import UserRole

    trader = await _create_user(
        db_session, "exptok", "Expass123456", "Exp Trader", UserRole.trader, deposit_exempt=True
    )
    token = await get_token(client, "exptok", "Expass123456")
    headers = auth_headers(token)

    exp = await client.post(
        "/trader/expenses",
        headers=headers,
        json={"category": "other", "amount_rub": "1000", "rate": "100"},
    )
    assert exp.status_code == 201
    assert exp.json()["debited"] is False
    assert Decimal(exp.json()["amount_usdt"]) == Decimal("10")

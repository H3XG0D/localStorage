"""End-to-end integration tests: full P2P doliv workflow.

Simulates a realistic work session:
  1. Trader creates a requisite
  2. Trader adds multiple zalivs with receipts
  3. Trader sends to doliv queue
  4. Dolivshchik sees the request in the queue
  5. Dolivshchik takes the request
  6. Dolivshchik completes it with receipt
  7. Deal result is stored and accessible to trader + admin
  8. Admin can see the closed requisite and deal result
  9. Notifications were created along the way
"""
import io
import pytest
from decimal import Decimal
from httpx import AsyncClient

from tests.conftest import auth_headers, get_token


def _fake_jpg() -> bytes:
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xd9"
    )


def _fake_png() -> bytes:
    # Minimal valid PNG (1x1 white pixel)
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Full workflow test
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_p2p_workflow(
    client: AsyncClient, admin_user, trader_user, doliv_user, app_settings
):
    """Simulate complete P2P cycle end-to-end."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    doliv_token = await get_token(client, "doliv_test", "Dolivpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    # ── Step 1: Trader creates a requisite ──────────────────────────────────
    create_resp = await client.post(
        "/trader/requisites",
        json={
            "name": "SberCard 4444 5555",
            "total_amount": 100000,
            "target_rate": 92.5,
            "comment": "Тестовый реквизит",
        },
        headers=auth_headers(trader_token),
    )
    assert create_resp.status_code == 201, create_resp.text
    req_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "active"

    # ── Step 2: Trader adds first zaliv (50 000 ₽) ──────────────────────────
    zaliv1 = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "50000", "rate": "92.0", "profit_percent": "12"},
        files={"receipt": ("receipt1.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    assert zaliv1.status_code == 201, zaliv1.text
    assert Decimal(zaliv1.json()["amount"]) == Decimal("50000")

    # ── Step 3: Trader adds second zaliv (30 000 ₽) ─────────────────────────
    zaliv2 = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "30000", "rate": "93.0", "profit_percent": "10"},
        files={"receipt": ("receipt2.png", io.BytesIO(_fake_png()), "image/png")},
        headers=auth_headers(trader_token),
    )
    assert zaliv2.status_code == 201, zaliv2.text

    # ── Step 4: Check requisite detail shows correct totals ──────────────────
    detail = await client.get(
        f"/trader/requisites/{req_id}", headers=auth_headers(trader_token)
    )
    assert detail.status_code == 200
    d = detail.json()
    assert len(d["zalivs"]) == 2
    assert Decimal(d["zaliv_total"]) == Decimal("80000")
    assert Decimal(d["remaining"]) == Decimal("20000")

    # ── Step 5: Trader sends to doliv ───────────────────────────────────────
    send_resp = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    assert send_resp.status_code == 200, send_resp.text
    request_id = send_resp.json()["request_id"]
    assert Decimal(send_resp.json()["required_amount"]) == Decimal("20000")

    # Status should now be awaiting_doliv
    detail2 = await client.get(
        f"/trader/requisites/{req_id}", headers=auth_headers(trader_token)
    )
    assert detail2.json()["status"] == "awaiting_doliv"

    # ── Step 6: Dolivshchik sees request in queue ────────────────────────────
    queue = await client.get("/doliv/requests", headers=auth_headers(doliv_token))
    assert queue.status_code == 200
    ids = [r["id"] for r in queue.json()]
    assert request_id in ids

    # ── Step 7: Dolivshchik takes the request ───────────────────────────────
    take_resp = await client.post(
        f"/doliv/requests/{request_id}/take",
        headers=auth_headers(doliv_token),
    )
    assert take_resp.status_code == 200, take_resp.text
    assert take_resp.json()["message"] == "Request taken"

    # Can't take it again
    double_take = await client.post(
        f"/doliv/requests/{request_id}/take",
        headers=auth_headers(doliv_token),
    )
    assert double_take.status_code == 400

    # ── Step 8: Dolivshchik completes the doliv ─────────────────────────────
    complete_resp = await client.post(
        f"/doliv/requests/{request_id}/complete",
        data={"amount": "20000", "rate": "92.5"},
        files={"receipt": ("doliv_receipt.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(doliv_token),
    )
    assert complete_resp.status_code == 200, complete_resp.text
    doliv_data = complete_resp.json()
    assert Decimal(doliv_data["amount"]) == Decimal("20000")
    assert doliv_data["dolivshchik_name"] == "Doliv User"

    # ── Step 9: Requisite should now be closed ───────────────────────────────
    final_detail = await client.get(
        f"/trader/requisites/{req_id}", headers=auth_headers(trader_token)
    )
    assert final_detail.json()["status"] == "closed"

    # ── Step 10: Deal result is accessible to trader ─────────────────────────
    deal_result = await client.get(
        f"/trader/requisites/{req_id}/deal-result",
        headers=auth_headers(trader_token),
    )
    assert deal_result.status_code == 200
    dr = deal_result.json()
    assert dr is not None
    assert "final_profit" in dr
    assert "total_turnover" in dr
    assert "doliv_amount" in dr

    # ── Step 11: Admin can see the requisite and deal result ─────────────────
    admin_req = await client.get(
        f"/admin/requisites/{req_id}", headers=auth_headers(admin_token)
    )
    assert admin_req.status_code == 200
    assert admin_req.json()["status"] == "closed"

    admin_dr = await client.get(
        f"/admin/requisites/{req_id}/deal-result",
        headers=auth_headers(admin_token),
    )
    assert admin_dr.status_code == 200
    assert admin_dr.json() is not None

    # ── Step 12: Doliv history and stats updated ─────────────────────────────
    history = await client.get("/doliv/history", headers=auth_headers(doliv_token))
    assert history.status_code == 200
    assert len(history.json()) >= 1

    stats = await client.get("/doliv/stats", headers=auth_headers(doliv_token))
    assert stats.status_code == 200
    assert stats.json()["dolivs_count"] >= 1

    # ── Step 13: Trader stats reflect the closed requisite ───────────────────
    trader_stats = await client.get("/trader/stats", headers=auth_headers(trader_token))
    assert trader_stats.status_code == 200
    ts = trader_stats.json()
    assert Decimal(ts["total_turnover"]) >= Decimal("100000")


@pytest.mark.asyncio
async def test_workflow_reject_second_send_while_awaiting(
    client: AsyncClient, trader_user, doliv_user, app_settings
):
    """Sending same requisite to doliv twice (while awaiting) returns existing request."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")

    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Double Send Card", "total_amount": 10000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]

    zaliv = await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0"},
        files={"receipt": ("test.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )
    assert zaliv.status_code == 201

    first_send = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    assert first_send.status_code == 200
    first_id = first_send.json()["request_id"]

    # Second send should either return same request_id or reject
    second_send = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    # Should not crash (200 with same id, or 400)
    assert second_send.status_code in (200, 400)
    if second_send.status_code == 200:
        assert second_send.json()["request_id"] == first_id


@pytest.mark.asyncio
async def test_workflow_zero_remaining_cannot_send(
    client: AsyncClient, trader_user, app_settings
):
    """If all zalivs fill the requisite, send-to-doliv should fail (no remaining)."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")

    create_resp = await client.post(
        "/trader/requisites",
        json={"name": "Full Card", "total_amount": 5000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )
    req_id = create_resp.json()["id"]

    # Fill completely
    await client.post(
        f"/trader/requisites/{req_id}/zalivs",
        data={"amount": "5000", "rate": "90.0", "profit_percent": "12"},
        files={"receipt": ("r.jpg", io.BytesIO(_fake_jpg()), "image/jpeg")},
        headers=auth_headers(trader_token),
    )

    # remaining == 0, send should fail
    send_resp = await client.post(
        f"/trader/requisites/{req_id}/send-to-doliv",
        headers=auth_headers(trader_token),
    )
    assert send_resp.status_code == 400
    assert "remaining" in send_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_workflow_admin_list_filters(
    client: AsyncClient, admin_user, trader_user, app_settings
):
    """Admin can filter requisites by status and trader_id."""
    trader_token = await get_token(client, "trader_test", "Traderpass12")
    admin_token = await get_token(client, "admin_test", "Adminpass12")

    # Create two requisites
    r1 = (await client.post(
        "/trader/requisites",
        json={"name": "Filter Test A", "total_amount": 1000, "target_rate": 90.0},
        headers=auth_headers(trader_token),
    )).json()
    r2 = (await client.post(
        "/trader/requisites",
        json={"name": "Filter Test B", "total_amount": 2000, "target_rate": 91.0},
        headers=auth_headers(trader_token),
    )).json()

    # Filter by active status
    resp = await client.get(
        "/admin/requisites?status=active", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert r1["id"] in ids
    assert r2["id"] in ids

    # Filter by trader_id
    resp2 = await client.get(
        f"/admin/requisites?trader_id={trader_user.id}", headers=auth_headers(admin_token)
    )
    assert resp2.status_code == 200
    ids2 = [r["id"] for r in resp2.json()]
    assert r1["id"] in ids2

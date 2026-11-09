"""Rapira USDT/RUB parser and fetch fallbacks."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rapira import _extract_rate, fetch_rapira_usdt_rub, get_rapira_usdt_rub_rate

RAPIRA_BODY = {
    "data": [
        {"symbol": "BTC/USDT", "close": 69237.5},
        {"symbol": "USDT/RUB", "close": 86.17, "open": 85.9, "high": 86.4, "low": 85.7},
        {"symbol": "TRX/USDT", "close": 0.3327},
    ],
    "code": 0,
    "message": "ok",
}


def test_extract_usdt_rub_close_from_rapira_array():
    assert _extract_rate(RAPIRA_BODY) == pytest.approx(86.17)


def test_extract_ignores_other_pairs_and_missing_usdt():
    assert _extract_rate({"data": [{"symbol": "BTC/USDT", "close": 1}]}) is None
    assert _extract_rate({"data": []}) is None
    assert _extract_rate({"price": 81.5}) == pytest.approx(81.5)


@pytest.mark.asyncio
async def test_empty_url_returns_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.rapira.settings",
        SimpleNamespace(RAPIRA_RATE_URL="", RAPIRA_RATE_FALLBACK=90.0),
    )
    rate, source = await fetch_rapira_usdt_rub()
    assert rate == Decimal("90.0000")
    assert source == "fallback"
    assert await get_rapira_usdt_rub_rate() == Decimal("90.0000")


@pytest.mark.asyncio
async def test_fetch_parses_rapira_close(monkeypatch):
    monkeypatch.setattr(
        "app.services.rapira.settings",
        SimpleNamespace(
            RAPIRA_RATE_URL="https://api.rapira.net/open/market/rates",
            RAPIRA_RATE_FALLBACK=90.0,
        ),
    )
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = RAPIRA_BODY

    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("app.services.rapira.httpx.AsyncClient", return_value=mock_client):
        rate, source = await fetch_rapira_usdt_rub()

    assert source == "rapira"
    assert rate == Decimal("86.1700")
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_falls_back_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.services.rapira.settings",
        SimpleNamespace(
            RAPIRA_RATE_URL="https://api.rapira.net/open/market/rates",
            RAPIRA_RATE_FALLBACK=90.0,
        ),
    )
    mock_client = AsyncMock()
    mock_client.get.side_effect = RuntimeError("timeout")
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("app.services.rapira.httpx.AsyncClient", return_value=mock_client):
        rate, source = await fetch_rapira_usdt_rub()

    assert source == "fallback"
    assert rate == Decimal("90.0000")

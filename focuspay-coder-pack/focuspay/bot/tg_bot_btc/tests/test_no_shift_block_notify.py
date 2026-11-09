"""Unit tests for no_shift_block_notify."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.no_shift_block_notify import (
    _DEBOUNCE_SEC,
    _direction_label,
    block_why,
    record_no_shift_block_and_notify,
)


def test_direction_label():
    assert _direction_label("sell") == "продажа"
    assert _direction_label("buy") == "покупка"


def test_block_why_names_the_paid_buy_gap():
    assert block_why("insufficient_paid_buys", {"paid_buys": 0, "min_paid_buys": 5}) == (
        "оплаченных покупок 0 из 5"
    )
    assert block_why("amount_over_cap", {"fiat_amount": 15000, "max_rub": 10000}) == (
        "сумма 15000 ₽ выше лимита автопилота 10000 ₽"
    )
    assert block_why(
        "coin_short",
        {"coin": "btc", "need": 0.02, "available": 0.005},
    ) == "BTC: нужно 0.02, свободно 0.005"
    assert block_why("coin_unknown") == "баланс этой валюты не удалось проверить"
    assert block_why("no_bill").startswith("Payfast")
    assert block_why("no_shift") == ""


def test_record_schedules_single_notify():
    bot = AsyncMock()
    bot_data: dict = {}

    async def _run():
        with patch(
            "services.no_shift_block_notify.record_no_shift_requisites_block",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.no_shift_block_notify._flush_pending",
            new=AsyncMock(),
        ) as flush_mock:
            await record_no_shift_block_and_notify(
                bot,
                bot_data,
                user_id=111,
                direction="buy",
                username="alice",
                missing_roles=("client", "finance"),
                fiat_amount=2600,
            )
            assert len(bot_data["no_shift_block_notify"]["events"]) == 1
            assert bot_data["no_shift_block_notify"]["events"][0]["missing_roles"] == (
                "client",
                "finance",
            )
            flush_mock.assert_called_once()

    asyncio.run(_run())


def test_duplicate_within_hour_skips_notify():
    bot = AsyncMock()
    bot_data: dict = {}

    async def _run():
        with patch(
            "services.no_shift_block_notify.record_no_shift_requisites_block",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.no_shift_block_notify._flush_pending",
            new=AsyncMock(),
        ) as flush_mock:
            await record_no_shift_block_and_notify(
                bot,
                bot_data,
                user_id=111,
                direction="buy",
                fiat_amount=2600,
            )
            assert "no_shift_block_notify" not in bot_data
            flush_mock.assert_not_called()

    asyncio.run(_run())


def test_debounce_batches_multiple_events():
    bot = MagicMock()
    bot_data: dict = {}
    sent_texts: list[str] = []

    async def fake_send(**kwargs):
        sent_texts.append(kwargs.get("text", ""))

    bot.send_message = AsyncMock(side_effect=fake_send)

    async def _run():
        with patch(
            "services.no_shift_block_notify.record_no_shift_requisites_block",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.no_shift_block_notify._notify_target",
            return_value=(12345, None),
        ), patch(
            "services.no_shift_block_notify.count_no_shift_blocks_since",
            new=AsyncMock(return_value=3),
        ), patch(
            "services.no_shift_block_notify.count_no_shift_blocks_since_empty_shift",
            new=AsyncMock(return_value=7),
        ), patch(
            "services.no_shift_block_notify.asyncio.sleep",
            new=AsyncMock(),
        ):
            await record_no_shift_block_and_notify(
                bot, bot_data, user_id=1, direction="buy"
            )
            await record_no_shift_block_and_notify(
                bot,
                bot_data,
                user_id=2,
                direction="sell",
                missing_roles=("finance",),
                why="оплаченных покупок 0 из 5",
            )
            task = bot_data["no_shift_block_notify"]["task"]
            assert task is not None
            await task

        assert bot.send_message.await_count == 1
        text = sent_texts[0]
        assert "Попыток за последний час" in text
        assert "7" in text
        assert f"За последние {int(_DEBOUNCE_SEC)} с" in text
        assert "2" in text
        assert "финансовый" in text
        assert "Почему: <b>оплаченных покупок 0 из 5</b>" in text

    asyncio.run(_run())


def test_get_no_shift_period_start_returns_none_when_active():
    from services.db import get_no_shift_period_start

    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[True])
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        with patch("services.db.get_pool", new=AsyncMock(return_value=pool)):
            assert await get_no_shift_period_start() is None

    asyncio.run(_run())


def test_count_no_shift_blocks_since_empty_shift_zero_when_on_shift():
    from services.db import count_no_shift_blocks_since_empty_shift

    async def _run():
        with patch(
            "services.db.get_no_shift_period_start",
            new=AsyncMock(return_value=None),
        ):
            assert await count_no_shift_blocks_since_empty_shift() == 0

    asyncio.run(_run())


def test_count_no_shift_blocks_since_empty_shift_counts_since_close():
    from services.db import count_no_shift_blocks_since_empty_shift

    since = datetime.now() - timedelta(hours=2)

    async def _run():
        with patch(
            "services.db.get_no_shift_period_start",
            new=AsyncMock(return_value=since),
        ), patch(
            "services.db.count_no_shift_blocks_since",
            new=AsyncMock(return_value=5),
        ) as count_mock:
            n = await count_no_shift_blocks_since_empty_shift()
            assert n == 5
            count_mock.assert_awaited_once_with(since)

    asyncio.run(_run())

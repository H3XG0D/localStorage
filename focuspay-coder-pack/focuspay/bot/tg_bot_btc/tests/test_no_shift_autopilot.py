"""Постоянник проходит без смены только по ответу API allow_auto."""
import asyncio
from unittest.mock import AsyncMock, patch

from services.no_shift_autopilot import regular_may_skip_shift


def test_allow_auto_skips_the_shift_block():
    with patch(
        "services.no_shift_autopilot._post",
        new=AsyncMock(return_value={"kind": "allow_auto", "reason": "eligible"}),
    ):
        assert asyncio.run(regular_may_skip_shift(100, 4000)) is True


def test_block_and_errors_keep_the_shift_block():
    with patch(
        "services.no_shift_autopilot._post",
        new=AsyncMock(return_value={"kind": "block", "reason": "insufficient_paid_buys"}),
    ):
        assert asyncio.run(regular_may_skip_shift(100, 4000)) is False
    with patch(
        "services.no_shift_autopilot._post",
        new=AsyncMock(return_value=None),
    ):
        assert asyncio.run(regular_may_skip_shift(100, 4000)) is False

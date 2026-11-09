"""Блок «Держат клиента»: зависающие BUY, которые блокируют новый обмен."""
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from routers.operator import (
    CLIENT_HOLD_STATUSES,
    CLOSE_CLIENT_HOLD_REASON,
    _annotate_client_hold,
    _CLIENT_HOLD_WHERE,
    get_operator_orders,
)


class AnnotateClientHoldTests(unittest.TestCase):
    def test_video_hold_label(self):
        out = _annotate_client_hold(
            {
                "order_id": "31100573",
                "status": "AWAITING_CHECK",
                "required_receipt_type": 3,
            }
        )
        self.assertEqual(out["hold_reason"], "video_hold")
        self.assertIn("видео", out["hold_reason_label"].lower())
        self.assertEqual(out["hold_reason_label"], "Ждёт видео")

    def test_video_hold_label_after_video_submitted(self):
        out = _annotate_client_hold(
            {
                "order_id": "31100573",
                "status": "AWAITING_CHECK",
                "required_receipt_type": 3,
                "receipt_file": "clip.mp4",
            }
        )
        self.assertEqual(out["hold_reason"], "video_hold")
        self.assertEqual(
            out["hold_reason_label"],
            "Видео у Payfast, ждём подтверждение",
        )

    def test_replaced_by_operator_wins(self):
        out = _annotate_client_hold(
            {
                "order_id": "31100573",
                "status": "AWAITING_CHECK",
                "required_receipt_type": 3,
                "replaced_by_order_id": "OP412B6DD6259C39C8",
            }
        )
        self.assertEqual(out["hold_reason"], "replaced_by_operator")
        self.assertIn("OP412B6DD6259C39C8", out["hold_reason_label"])

    def test_close_reason_long_enough_for_cancel_api(self):
        self.assertGreaterEqual(len(CLOSE_CLIENT_HOLD_REASON.strip()), 3)


class ClientHoldSqlTests(unittest.TestCase):
    def test_where_clause_covers_awaiting_check_and_operator_replace(self):
        self.assertIn("AWAITING_CHECK", _CLIENT_HOLD_WHERE)
        self.assertIn("manual_operator", _CLIENT_HOLD_WHERE)
        self.assertIn("CREATED", CLIENT_HOLD_STATUSES)
        source = Path(__file__).resolve().parent.parent / "routers" / "operator.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn('"client_holds"', text)
        self.assertIn("hold_rows = await conn.fetch", text)


class GetOperatorOrdersHoldsTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_holds_bucket_returned(self):
        hold_row = {
            "order_id": "31100573",
            "direction": "buy",
            "status": "AWAITING_CHECK",
            "crypto": "ltc",
            "fiat_amount": 2664,
            "crypto_amount": 0.43,
            "operator_id": None,
            "required_receipt_type": 3,
            "replaced_by_order_id": "OP412",
            "created_at": "2026-09-08T08:08:00+00:00",
        }
        conn = AsyncMock()
        conn.fetch = AsyncMock(
            side_effect=[[hold_row], [], [], [], [], [], [], []]
        )
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        async def _get_pool():
            return pool

        with patch("routers.operator.get_pool", new=_get_pool), patch(
            "routers.operator._queue_stats",
            new=AsyncMock(return_value={"queue_count": 0, "client_hold_count": 1}),
        ), patch(
            "routers.operator._withdrawal_market_rates",
            new=AsyncMock(return_value={}),
        ):
            result = await get_operator_orders(op={"id": 1, "username": "op"})

        self.assertEqual(len(result["client_holds"]), 1)
        hold = result["client_holds"][0]
        self.assertEqual(hold["order_id"], "31100573")
        self.assertEqual(hold["hold_reason"], "replaced_by_operator")
        self.assertEqual(hold["replaced_by_order_id"], "OP412")


if __name__ == "__main__":
    unittest.main()

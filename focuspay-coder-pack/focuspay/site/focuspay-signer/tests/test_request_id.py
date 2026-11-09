"""Номер отправки, который подписант согласен принять."""
import unittest

from pydantic import ValidationError

from main import PayoutBody


def _body(request_id: str) -> PayoutBody:
    return PayoutBody.model_validate(
        {
            "request_id": request_id,
            "coin": "ltc",
            "address": "M" + "A" * 33,
            "amount": 2.5,
        }
    )


class RequestIdTests(unittest.TestCase):
    def test_swap_send_id_is_accepted(self):
        body = _body("swap:6:" + "a" * 32)
        self.assertEqual(body.request_id, "swap:6:" + "a" * 32)

    def test_order_and_withdrawal_ids_stay_accepted(self):
        self.assertEqual(_body("order:51579642").coin, "ltc")
        self.assertEqual(_body("order:35528513-r2").amount, 2.5)
        self.assertEqual(_body("wd:88").kind, "withdrawal")

    def test_unknown_prefix_is_rejected(self):
        with self.assertRaises(ValidationError):
            _body("swap:6:not-a-uuid")
        with self.assertRaises(ValidationError):
            _body("manual:1")

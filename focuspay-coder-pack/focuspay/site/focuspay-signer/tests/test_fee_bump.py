"""Классификация ошибок узла и ставка для bumpfee."""
import unittest

from wallet_rpc import classify_bump_error, fee_rate_btc_kvb, presend_reject_reason, sat_vb_to_btc_kvb


class FeeBumpHelperTests(unittest.TestCase):
    def test_wallet_miss_is_not_our_transaction(self):
        self.assertEqual(
            classify_bump_error("{'code': -5, 'message': 'Invalid or non-wallet transaction id'}"),
            "not_in_wallet",
        )

    def test_missing_rbf_flag_cannot_be_bumped(self):
        self.assertEqual(
            classify_bump_error("Transaction is not BIP 125 replaceable"),
            "not_replaceable",
        )

    def test_fee_rate_rounds_up_so_the_node_accepts_it(self):
        # 0.000015 BTC на 141 vbyte → чуть выше сырого BTC/kvB.
        rate = fee_rate_btc_kvb(0.000015, 141)
        raw = 0.000015 * 1000 / 141
        self.assertGreaterEqual(rate, raw)
        self.assertLess(rate - raw, 1e-8)

    def test_sat_per_vbyte_becomes_btc_per_kvb(self):
        self.assertEqual(sat_vb_to_btc_kvb(1), 0.00001)
        self.assertEqual(sat_vb_to_btc_kvb(8), 0.00008)
        self.assertEqual(sat_vb_to_btc_kvb(1.05), 0.0000105)


class PresendRejectTests(unittest.TestCase):
    def test_insufficient_funds_is_a_definite_reject(self):
        exc = RuntimeError("{'code': -6, 'message': 'Insufficient funds'}")
        self.assertEqual(presend_reject_reason(exc), "insufficient_funds")

    def test_amount_too_small_is_a_definite_reject(self):
        self.assertEqual(
            presend_reject_reason(RuntimeError("Transaction amount too small")),
            "amount_too_small",
        )

    def test_timeout_stays_unknown(self):
        self.assertIsNone(presend_reject_reason(TimeoutError("timed out")))
        self.assertIsNone(presend_reject_reason(RuntimeError("connection reset by peer")))


if __name__ == "__main__":
    unittest.main()

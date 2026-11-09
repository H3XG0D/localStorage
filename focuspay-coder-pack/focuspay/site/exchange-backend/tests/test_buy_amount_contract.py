"""P0: контракт _validate_amounts и распаковка в operator-BUY.

Инцидент: в ручную BUY-заявку в crypto_amount записалось 9000 (рубли) вместо
~2.26 LTC из-за неверной распаковки `_, crypto_dec, rate_dec`. Оператор мог
отправить 9000 LTC. _validate_amounts возвращает (crypto, fiat, rate) — крипта
первой. Эти тесты фиксируют порядок и ловят утечку фиата в слот крипты.
"""
import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException

from buy_rub_quote import quote_buy_rub_base
from order_service import _validate_amounts


MARKET = {"ltc": 4000.0, "usdt": 105.0, "btc": 60000.0, "trx": 5.0}


class ValidateAmountsContractTests(unittest.TestCase):
    def test_returns_crypto_fiat_rate_order(self):
        crypto_amt, fiat, rate = _validate_amounts(
            "ltc", "buy", 9000, None, MARKET, manual_buy=True
        )
        # rate = 4000 * buy_markup(1.20) = 4800
        self.assertGreater(float(rate), 4000)
        self.assertEqual(int(fiat), 9000)
        # 9000 / 4800 ≈ 1.875 LTC — крипта, не рубли
        self.assertAlmostEqual(float(crypto_amt), 9000 / float(rate), places=4)

    def test_crypto_not_equal_fiat(self):
        """Регрессия 9000 LTC: крипта не должна равняться сумме в рублях."""
        crypto_amt, fiat, _ = _validate_amounts(
            "ltc", "buy", 9000, None, MARKET, manual_buy=True
        )
        self.assertNotEqual(float(crypto_amt), float(fiat))
        self.assertLess(float(crypto_amt), 100)  # LTC за 9000 ₽ — единицы, не тысячи

    def test_buy_fiat_is_integer(self):
        _, fiat, _ = _validate_amounts("ltc", "buy", 9000, None, MARKET, manual_buy=True)
        self.assertEqual(float(fiat), float(int(fiat)))

    def test_simulated_buggy_unpack_would_be_caught(self):
        """Старый баг: `_, crypto_dec, rate_dec` клал фиат в crypto_dec."""
        result = _validate_amounts("ltc", "buy", 9000, None, MARKET, manual_buy=True)
        _, buggy_crypto, _buggy_rate = result  # как было в баге
        correct_crypto, _, _ = result
        # Демонстрируем, что неправильная распаковка дала бы 9000 (фиат)
        self.assertEqual(int(buggy_crypto), 9000)
        # А правильная — маленькую крипту
        self.assertLess(float(correct_crypto), 100)


class WebBuyMarketBaseTests(unittest.TestCase):
    """Сайт и бот: ввод в рублях — оценка по CoinGecko, оплата по Rapira."""

    def tearDown(self):
        import runtime_settings as rs

        rs._cache = None
        rs._cache_ts = 0.0

    def test_fiat_input_same_need_and_market_keeps_old_numbers(self):
        with patch("runtime_settings.buy_markup", return_value=1.2):
            crypto_amt, fiat, rate = _validate_amounts(
                "ltc",
                "buy",
                8000,
                None,
                MARKET,
                buy_fiat_is_market_base=True,
                need={"ltc": 4000.0},
            )
        self.assertEqual(int(fiat), 9600)  # 8000 × 1.2
        self.assertAlmostEqual(float(crypto_amt), 2.0, places=4)  # 8000 / 4000
        self.assertAlmostEqual(float(rate), 4800.0, places=2)

    def test_fiat_input_uses_coingecko_for_crypto_rapira_for_pay(self):
        with patch("runtime_settings.buy_markup", return_value=1.2):
            crypto_amt, fiat, rate = _validate_amounts(
                "ltc",
                "buy",
                8000,
                None,
                MARKET,
                buy_fiat_is_market_base=True,
                need={"ltc": 3800.0},
            )
        expected_crypto, expected_pay, expected_rate = quote_buy_rub_base(
            base_fiat=Decimal("8000"),
            rapira=Decimal("4000"),
            coingecko=Decimal("3800"),
            markup=Decimal("1.2"),
        )
        self.assertAlmostEqual(float(crypto_amt), float(expected_crypto), places=8)
        self.assertEqual(int(fiat), int(expected_pay))
        self.assertAlmostEqual(float(rate), float(expected_rate), places=2)
        self.assertGreater(float(crypto_amt), 8000 / 4000)

    def test_fiat_input_without_need_is_unavailable(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_amounts(
                "ltc",
                "buy",
                8000,
                None,
                MARKET,
                buy_fiat_is_market_base=True,
            )
        self.assertEqual(ctx.exception.status_code, 503)

    def test_fiat_input_uses_amount_tier(self):
        import time

        import runtime_settings as rs

        rs._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 20,
            "buy_spread_auto_tiers": [
                {"min_amount_rub": 0, "pct": 25},
                {"min_amount_rub": 1000, "pct": 23},
            ],
        }
        rs._cache_ts = time.time()
        crypto_amt, fiat, rate = _validate_amounts(
            "ltc",
            "buy",
            1000,
            None,
            MARKET,
            buy_fiat_is_market_base=True,
            need={"ltc": 4000.0},
        )
        self.assertAlmostEqual(float(rate), 4000 * 1.23, places=2)
        self.assertAlmostEqual(float(crypto_amt), 1000 / 4000, places=4)
        self.assertGreater(int(fiat), 1000)

    def test_crypto_input_uses_base_fiat_tier(self):
        import time

        import runtime_settings as rs

        rs._cache = {
            "buy_spread_auto_pct": 25,
            "buy_spread_manual_pct": 20,
            "buy_spread_auto_tiers": [
                {"min_amount_rub": 0, "pct": 25},
                {"min_amount_rub": 1000, "pct": 23},
            ],
        }
        rs._cache_ts = time.time()
        # 0.2 LTC × 4000 = 800 ₽ base → 25%
        crypto_amt, fiat, rate = _validate_amounts(
            "ltc",
            "buy",
            None,
            0.2,
            MARKET,
            buy_fiat_is_market_base=True,
        )
        self.assertAlmostEqual(float(crypto_amt), 0.2, places=4)
        self.assertAlmostEqual(float(rate), 4000 * 1.25, places=2)
        self.assertEqual(int(fiat), 1000)

    def test_crypto_input_adds_commission_on_top(self):
        with patch("runtime_settings.buy_markup", return_value=1.2):
            crypto_amt, fiat, _ = _validate_amounts(
                "ltc",
                "buy",
                None,
                2.0,
                MARKET,
                buy_fiat_is_market_base=True,
            )
        self.assertEqual(int(fiat), 9600)
        self.assertAlmostEqual(float(crypto_amt), 2.0, places=4)


class OperatorManualLimitsTests(unittest.TestCase):
    """Ручные заявки оператора: без лимитов min_crypto / min_fiat."""

    def test_usdt_1000_rub_allowed_for_operator_manual(self):
        crypto_amt, fiat, _ = _validate_amounts(
            "usdt",
            "buy",
            1000,
            None,
            MARKET,
            manual_buy=True,
            operator_manual=True,
        )
        self.assertEqual(int(fiat), 1000)
        self.assertLess(float(crypto_amt), 10)

    def test_operator_manual_allows_small_amounts(self):
        crypto_amt, fiat, _ = _validate_amounts(
            "usdt",
            "buy",
            100,
            None,
            MARKET,
            manual_buy=True,
            operator_manual=True,
        )
        self.assertEqual(int(fiat), 100)
        self.assertGreater(float(crypto_amt), 0)

    def test_public_buy_uses_fiat_min_not_crypto_min(self):
        """Fiat в пределах min_fiat — min_crypto больше не блокирует."""
        market = {"usdt": 105.0}
        crypto_amt, fiat, _ = _validate_amounts(
            "usdt",
            "buy",
            1000,
            None,
            market,
            buy_fiat_is_market_base=True,
            need={"usdt": 105.0},
        )
        self.assertAlmostEqual(float(crypto_amt), 1000 / 105.0, places=4)
        self.assertLess(float(crypto_amt), 10)
        self.assertGreaterEqual(int(fiat), 1000)


class OperatorManualCryptoLockTests(unittest.TestCase):
    def test_operator_manual_keeps_btc_sats_and_kopeck_fiat(self):
        crypto_amt, fiat, _ = _validate_amounts(
            "btc",
            "buy",
            None,
            0.00092555,
            MARKET,
            manual_buy=True,
            operator_manual=True,
        )
        self.assertEqual(float(crypto_amt), 0.00092555)
        self.assertEqual(float(fiat), float(int(fiat)))
        self.assertGreaterEqual(float(fiat), float(crypto_amt) * float(MARKET["btc"]))

    def test_public_buy_still_truncates_fiat_to_int(self):
        _, fiat, _ = _validate_amounts(
            "btc",
            "buy",
            None,
            0.018,  # 0.018 BTC × 60000 × 1.20 = 1296₽, выше min_fiat
            MARKET,
            manual_buy=True,
        )
        self.assertEqual(float(fiat), float(int(fiat)))


class ClampLockCryptoTests(unittest.TestCase):
    def test_lock_crypto_does_not_shrink_btc(self):
        from buy_crypto_amount import clamp_buy_crypto_amount

        out = clamp_buy_crypto_amount(
            0.00092555,
            fiat_amount=66,
            rate=72000,
            crypto="btc",
            lock_crypto=True,
        )
        self.assertEqual(out, 0.00092555)


if __name__ == "__main__":
    unittest.main()

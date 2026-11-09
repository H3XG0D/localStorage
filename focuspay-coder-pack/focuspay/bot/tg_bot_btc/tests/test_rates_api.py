"""Rapira rates: полный/частичный ответ, frozen snapshot, Telegram edit."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import telegram

from handlers.telegram_utils import edit_message_text_safe, edit_order_message
from services import rates_api as ra


FULL_RATES = {"usdt": 90.0, "btc": 9_000_000.0, "ltc": 9000.0, "trx": 27.0}
FROZEN_RATES = {"usdt": 80.0, "btc": 8_000_000.0, "ltc": 8000.0, "trx": 24.0}
SERVED_LIVE = {**FULL_RATES, "usdt": 92.0}
SERVED_FROZEN = {**FROZEN_RATES, "usdt": 82.5}


def _rapira_body(*tickers: dict) -> dict:
    return {"data": list(tickers)}


class ParseRapiraTests(unittest.TestCase):
    def test_full_response(self):
        body = _rapira_body(
            {"symbol": "USDT/RUB", "close": 90},
            {"symbol": "BTC/USDT", "close": 100000},
            {"symbol": "LTC/USDT", "close": 100},
            {"symbol": "TRX/USDT", "close": 0.3},
        )
        rates = ra.parse_rapira_payload(body)
        self.assertAlmostEqual(rates["usdt"], 90.0)
        self.assertAlmostEqual(rates["btc"], 9_000_000.0)
        self.assertAlmostEqual(rates["ltc"], 9000.0)
        self.assertAlmostEqual(rates["trx"], 27.0)

    def test_empty_data_raises(self):
        with self.assertRaises(ValueError) as ctx:
            ra.parse_rapira_payload({"data": []})
        self.assertIn("empty", str(ctx.exception).lower())

    def test_missing_data_array_raises(self):
        with self.assertRaises(ValueError):
            ra.parse_rapira_payload({"ok": True})
        with self.assertRaises(ValueError):
            ra.parse_rapira_payload("nope")

    def test_invalid_usdt_raises(self):
        with self.assertRaises(ValueError):
            ra.parse_rapira_payload(
                _rapira_body({"symbol": "USDT/RUB", "close": 0})
            )
        with self.assertRaises(ValueError):
            ra.parse_rapira_payload(
                _rapira_body({"symbol": "BTC/USDT", "close": 1})
            )

    def test_partial_skips_missing_pairs(self):
        rates = ra.parse_rapira_payload(
            _rapira_body(
                {"symbol": "USDT/RUB", "close": 90},
                {"symbol": "BTC/USDT", "close": 100000},
            )
        )
        self.assertEqual(set(rates), {"usdt", "btc"})
        self.assertNotIn("ltc", rates)
        self.assertNotIn("trx", rates)

    def test_non_numeric_close_skipped(self):
        rates = ra.parse_rapira_payload(
            _rapira_body(
                {"symbol": "USDT/RUB", "close": 90},
                {"symbol": "BTC/USDT", "close": "n/a"},
                {"symbol": "LTC/USDT", "close": -1},
            )
        )
        self.assertEqual(set(rates), {"usdt"})


class _RatesCase:
    def setUp(self):
        super().setUp()
        handle = tempfile.NamedTemporaryFile(
            prefix="rapira_snap_", suffix=".json", delete=False
        )
        handle.close()
        self._snap = Path(handle.name)
        self._snap.unlink(missing_ok=True)
        ra.reset_rates_state(snapshot_path=self._snap, clear_file=True)

    def tearDown(self):
        ra.reset_rates_state(snapshot_path=self._snap, clear_file=True)
        self._snap.unlink(missing_ok=True)
        super().tearDown()


class FrozenSnapshotTests(_RatesCase, unittest.TestCase):
    def test_valid_frozen_kept(self):
        now = time.time()
        ra._store_frozen(FROZEN_RATES, now)
        snap = ra.get_frozen_snapshot(now)
        self.assertEqual(snap, FROZEN_RATES)

    def test_old_rapira_snapshot_still_used(self):
        now = time.time()
        ra._store_frozen(FROZEN_RATES, now - 24 * 3600, persist=True)
        ra._FROZEN.clear()
        snap = ra.get_frozen_snapshot(now)
        self.assertEqual(snap, FROZEN_RATES)

    def test_incomplete_frozen_rejected(self):
        now = time.time()
        ra._FROZEN.update({"usdt": 90.0, "btc": 1.0, "_ts": now})
        self.assertIsNone(ra.get_frozen_snapshot(now))

    def test_cache_promoted_if_complete(self):
        now = time.time()
        for coin, price in FROZEN_RATES.items():
            ra.CACHE[coin] = {"price": price, "time": now}
        snap = ra.get_frozen_snapshot(now)
        self.assertEqual(snap, FROZEN_RATES)

    def test_persisted_reload_after_memory_clear(self):
        now = time.time()
        ra._store_frozen(FROZEN_RATES, now, persist=True)
        ra.CACHE.clear()
        ra._FROZEN.clear()
        snap = ra.get_frozen_snapshot(now)
        self.assertEqual(snap, FROZEN_RATES)


class MarkupOnceTests(_RatesCase, unittest.TestCase):

    def test_buy_sell_markup_applied_once(self):
        ra.CACHE["usdt"] = {"price": 100.0, "time": time.time()}
        ra._LAST_SOURCE = "rapira"
        with patch("services.rates_api.buy_markup", return_value=1.20), patch(
            "services.rates_api.sell_discount", return_value=0.95
        ):
            self.assertAlmostEqual(ra.get_cached_rate("usdt", "buy"), 122.4)
            self.assertAlmostEqual(ra.get_cached_rate("usdt", "sell"), 93.1)
        self.assertIsNone(ra.get_cached_rate("btc", "buy"))
        self.assertEqual(ra.CACHE["usdt"]["price"], 100.0)

    def test_sell_prefers_coingecko_need_cache(self):
        ra.CACHE["usdt"] = {"price": 100.0, "time": time.time()}
        ra._NEED["usdt"] = 110.0
        with patch("services.rates_api.sell_discount", return_value=0.95):
            self.assertAlmostEqual(ra.get_cached_rate("usdt", "sell"), 102.6)

    def test_frozen_usdt_pad_before_markup(self):
        ra.CACHE["usdt"] = {"price": 80.0, "time": time.time()}
        ra._LAST_SOURCE = "frozen"
        with patch("services.rates_api.buy_markup", return_value=1.20):
            self.assertAlmostEqual(ra.get_cached_rate("usdt", "buy"), 99.0)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)

    def test_live_usdt_earn_pad_before_markup(self):
        ra.CACHE["usdt"] = {"price": 80.0, "time": time.time()}
        ra._LAST_SOURCE = "rapira"
        with patch("services.rates_api.buy_markup", return_value=1.20):
            self.assertAlmostEqual(ra.get_cached_rate("usdt", "buy"), 98.4)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)


class CachedBuyMarketTests(_RatesCase, unittest.TestCase):
    def test_live_usdt_pad_keeps_cache_raw(self):
        ra.CACHE["usdt"] = {"price": 90.0, "time": time.time()}
        ra.CACHE["btc"] = {"price": 9_000_000.0, "time": time.time()}
        ra._LAST_SOURCE = "rapira"
        self.assertAlmostEqual(ra.get_cached_buy_market("usdt"), 92.0)
        self.assertAlmostEqual(ra.get_cached_buy_market("usdt_trc20"), 92.0)
        self.assertAlmostEqual(ra.get_cached_buy_market("btc"), 9_000_000.0)
        self.assertEqual(ra.CACHE["usdt"]["price"], 90.0)

    def test_frozen_usdt_pad(self):
        ra.CACHE["usdt"] = {"price": 80.0, "time": time.time()}
        ra._LAST_SOURCE = "frozen"
        self.assertAlmostEqual(ra.get_cached_buy_market("usdt"), 82.5)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)

    def test_missing_returns_none(self):
        self.assertIsNone(ra.get_cached_buy_market("usdt"))


class QuotedBuyMarkupPadTests(_RatesCase, unittest.TestCase):
    def test_quoted_markup_uses_padded_market(self):
        from services.buy_order_service import _buy_markup_from_quoted_rate
        from services.economics_snapshot import quoted_buy_markup

        ra.CACHE["usdt"] = {"price": 90.0, "time": time.time()}
        ra._LAST_SOURCE = "rapira"
        rate = 92.0 * 1.2
        self.assertAlmostEqual(quoted_buy_markup("usdt", rate), 1.2)
        self.assertAlmostEqual(_buy_markup_from_quoted_rate("usdt", rate), 1.2)
        self.assertAlmostEqual(quoted_buy_markup("usdt_trc20", rate), 1.2)


class RefreshCacheTests(_RatesCase, unittest.IsolatedAsyncioTestCase):

    async def test_successful_rapira(self):
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=dict(FULL_RATES)),
        ):
            rates = await ra.refresh_all_rates_cache()
        self.assertEqual(rates, SERVED_LIVE)
        self.assertEqual(ra.CACHE["usdt"]["price"], FULL_RATES["usdt"])
        self.assertEqual(ra.CACHE["btc"]["price"], FULL_RATES["btc"])
        self.assertEqual(ra.get_frozen_snapshot(), FULL_RATES)
        self.assertEqual(ra._LAST_SOURCE, "rapira")

    async def test_full_failure_uses_frozen(self):
        now = time.time()
        ra._store_frozen(FROZEN_RATES, now)
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("Rapira HTTP 503")),
        ):
            rates = await ra.refresh_all_rates_cache()
        self.assertEqual(rates, SERVED_FROZEN)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)
        self.assertEqual(ra.get_frozen_snapshot()["usdt"], 80.0)
        self.assertEqual(ra._LAST_SOURCE, "frozen")
        again = await ra.ensure_rates_cache()
        self.assertEqual(again["usdt"], 82.5)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)

    async def test_full_failure_without_frozen_raises(self):
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            with self.assertRaises(ra.RatesUnavailableError) as ctx:
                await ra.refresh_all_rates_cache()
        self.assertIn("no valid frozen", ctx.exception.reason)
        self.assertNotIn("token", ctx.exception.reason.lower())
        self.assertEqual(
            ra.USER_RATES_UNAVAILABLE.count("недоступн"),
            1,
        )

    async def test_old_persisted_rapira_used_after_restart(self):
        ra._store_frozen(FROZEN_RATES, time.time() - 24 * 3600, persist=True)
        ra.CACHE.clear()
        ra._FROZEN.clear()
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            rates = await ra.refresh_all_rates_cache()
        self.assertEqual(rates, SERVED_FROZEN)
        self.assertEqual(ra._LAST_SOURCE, "frozen")
        self.assertNotEqual(ra._LAST_SOURCE, "cbr_coingecko")
        raw = json.loads(self._snap.read_text(encoding="utf-8"))
        self.assertEqual(raw["rates"]["usdt"], 80.0)

    async def test_successful_rapira_writes_snapshot_file(self):
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=dict(FULL_RATES)),
        ):
            await ra.refresh_all_rates_cache()
        self.assertTrue(self._snap.is_file())
        ra.CACHE.clear()
        ra._FROZEN.clear()
        snap = ra.get_frozen_snapshot()
        self.assertEqual(snap, FULL_RATES)

    async def test_partial_filled_from_frozen(self):
        ra._store_frozen(FROZEN_RATES, time.time())
        live = {"usdt": 91.0, "btc": 9_100_000.0}
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=live),
        ):
            rates = await ra.refresh_all_rates_cache()
        self.assertAlmostEqual(rates["usdt"], 93.0)
        self.assertAlmostEqual(rates["btc"], 9_100_000.0)
        self.assertAlmostEqual(rates["ltc"], 8000.0)
        self.assertAlmostEqual(rates["trx"], 24.0)
        self.assertEqual(ra._LAST_SOURCE, "partial_frozen")
        # mixed fill must not become the new frozen snapshot
        self.assertEqual(ra.get_frozen_snapshot(), FROZEN_RATES)

    async def test_partial_without_frozen_does_not_invent(self):
        live = {"usdt": 91.0, "btc": 9_100_000.0}
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=live),
        ):
            rates = await ra.refresh_all_rates_cache()
        self.assertEqual(set(rates), {"usdt", "btc"})
        self.assertNotIn("ltc", ra.CACHE)
        self.assertNotIn("trx", ra.CACHE)
        self.assertIsNone(ra.get_frozen_snapshot())
        self.assertEqual(ra._LAST_SOURCE, "partial")

    async def test_reason_redacts_secrets_and_urls(self):
        reason = ra._log_reason(
            "Rapira fetch error",
            RuntimeError(
                "token=secret-bot-token https://api.rapira.net/open/market/rates?key=abc"
            ),
        )
        self.assertNotIn("secret-bot-token", reason)
        self.assertNotIn("key=abc", reason)
        self.assertIn("***", reason)
        self.assertIn("[url]", reason)


class GetMarketPriceTests(_RatesCase, unittest.IsolatedAsyncioTestCase):

    async def test_fresh_cache_hit(self):
        ra.CACHE["usdt"] = {"price": 90.0, "time": time.time()}
        ra._LAST_SOURCE = "rapira"
        price, stale, blocked = await ra.get_market_price("usdt")
        self.assertEqual(price, 92.0)
        self.assertFalse(stale)
        self.assertFalse(blocked)
        self.assertEqual(ra.CACHE["usdt"]["price"], 90.0)

    async def test_rapira_ok(self):
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=dict(FULL_RATES)),
        ):
            price, stale, blocked = await ra.get_market_price("btc")
        self.assertEqual(price, FULL_RATES["btc"])
        self.assertFalse(stale)
        self.assertFalse(blocked)

    async def test_fallback_then_blocked(self):
        ra._store_frozen(FROZEN_RATES, time.time())
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            price, stale, blocked = await ra.get_market_price("ltc")
        self.assertEqual(price, 8000.0)
        self.assertTrue(stale)
        self.assertFalse(blocked)

        usdt, _usdt_stale, usdt_blocked = await ra.get_market_price("usdt")
        self.assertEqual(usdt, 82.5)
        self.assertFalse(usdt_blocked)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)

        ra.reset_rates_state(snapshot_path=self._snap, clear_file=True)
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            price, stale, blocked = await ra.get_market_price("ltc")
        self.assertIsNone(price)
        self.assertTrue(blocked)

    async def test_frozen_usdt_served_with_pad(self):
        ra._store_frozen(FROZEN_RATES, time.time())
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            price, stale, blocked = await ra.get_market_price("usdt")
        self.assertEqual(price, 82.5)
        self.assertTrue(stale)
        self.assertFalse(blocked)
        self.assertEqual(ra.CACHE["usdt"]["price"], 80.0)
        self.assertEqual(ra.get_frozen_snapshot()["usdt"], 80.0)


class RapiraLatencyGuardTests(_RatesCase, unittest.IsolatedAsyncioTestCase):
    async def test_frozen_user_path_does_not_wait_for_rapira(self):
        from services.payment_methods_display import build_rates_message_html

        ra._store_frozen(FROZEN_RATES, time.time())

        async def slow_fetch(**_kwargs):
            await asyncio.sleep(8)
            return dict(FULL_RATES)

        started = time.monotonic()
        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=slow_fetch),
        ), patch(
            "services.crypto_network_fee.format_withdraw_terms_html",
            new=AsyncMock(return_value=""),
        ), patch(
            "services.rates_api.buy_markup", return_value=1.20
        ), patch(
            "services.rates_api.sell_discount", return_value=0.95
        ):
            text = await build_rates_message_html()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertIn("BTC", text)
        self.assertIn("USDT", text)
        self.assertNotIn("Курсы временно недоступны", text)

    async def test_refresh_single_flight(self):
        calls = {"n": 0}

        async def slow_fetch(**_kwargs):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return dict(FULL_RATES)

        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=slow_fetch),
        ):
            first, second = await asyncio.gather(
                ra.refresh_all_rates_cache(),
                ra.refresh_all_rates_cache(),
            )
        self.assertEqual(calls["n"], 1)
        self.assertEqual(first, second)
        self.assertEqual(first, SERVED_LIVE)

    async def test_backoff_skips_live_fetch(self):
        ra._store_frozen(FROZEN_RATES, time.time())
        fetch = AsyncMock(side_effect=RuntimeError("timeout"))
        with patch("services.rates_api.fetch_all_rates_from_rapira", new=fetch):
            await ra.refresh_all_rates_cache()
            await ra.refresh_all_rates_cache()
            fetch.reset_mock()
            rates = await ra.refresh_all_rates_cache()
        self.assertEqual(fetch.await_count, 0)
        self.assertEqual(rates, SERVED_FROZEN)
        self.assertGreater(ra._rapira_backoff_until, time.time())

    def test_fast_fetch_params_when_snapshot_exists(self):
        timeout, attempts = ra._rapira_fetch_params(has_snapshot=True)
        self.assertEqual(timeout, ra.RAPIRA_FAST_TIMEOUT_SEC)
        self.assertEqual(attempts, ra.RAPIRA_FAST_ATTEMPTS)
        timeout, attempts = ra._rapira_fetch_params(has_snapshot=False)
        self.assertEqual(timeout, ra.RAPIRA_REQUEST_TIMEOUT_SEC)
        self.assertEqual(attempts, ra.RAPIRA_ATTEMPTS)


class BuildRatesMessageTests(_RatesCase, unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_user_text(self):
        from services.payment_methods_display import build_rates_message_html

        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            text = await build_rates_message_html()
        self.assertIn("Курсы временно недоступны", text)
        self.assertNotIn("RuntimeError", text)
        self.assertNotIn("down", text)

    async def test_success_shows_live_rates(self):
        from services.payment_methods_display import build_rates_message_html

        with patch(
            "services.rates_api.fetch_all_rates_from_rapira",
            new=AsyncMock(return_value=dict(FULL_RATES)),
        ), patch(
            "services.crypto_network_fee.format_withdraw_terms_html",
            new=AsyncMock(return_value=""),
        ), patch(
            "services.rates_api.buy_markup", return_value=1.20
        ), patch(
            "services.rates_api.sell_discount", return_value=0.95
        ):
            text = await build_rates_message_html()
        self.assertIn("BTC", text)
        self.assertIn("USDT", text)
        self.assertNotIn("Курсы временно недоступны", text)


class TelegramEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_with_dynamic_rate_chars(self):
        edit_fn = AsyncMock()
        text = "Курс BTC: 9_123_456.78 * 1.20 = [buy] 10_948_148.14"
        ok = await edit_message_text_safe(edit_fn, text)
        self.assertTrue(ok)
        self.assertEqual(edit_fn.await_count, 1)
        self.assertEqual(edit_fn.await_args.kwargs.get("parse_mode"), "HTML")

    async def test_html_parse_error_falls_back_to_plain(self):
        calls: list[tuple[str, str | None]] = []

        async def edit_fn(body, **kwargs):
            calls.append((body, kwargs.get("parse_mode")))
            if kwargs.get("parse_mode") == "HTML":
                raise telegram.error.BadRequest("Can't parse entities")

        ok = await edit_message_text_safe(
            edit_fn, "<b>Курс 1 USDT = 90.5 ₽</b> *unclosed"
        )
        self.assertTrue(ok)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "HTML")
        self.assertIsNone(calls[-1][1])
        self.assertTrue(calls[-1][0])

    async def test_not_modified_is_ok(self):
        edit_fn = AsyncMock(
            side_effect=telegram.error.BadRequest("Message is not modified")
        )
        self.assertTrue(await edit_message_text_safe(edit_fn, "same"))

    async def test_telegram_api_error_does_not_raise(self):
        edit_fn = AsyncMock(side_effect=telegram.error.NetworkError("timed out"))
        ok = await edit_message_text_safe(edit_fn, "Курс USDT = 90.5")
        self.assertFalse(ok)

    async def test_edit_order_message_uses_html(self):
        bot = AsyncMock()
        await edit_order_message(bot, 1, 2, "Курс *USDT* = 90_0.5")
        bot.edit_message_text.assert_awaited()
        kwargs = bot.edit_message_text.await_args.kwargs
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertEqual(kwargs["chat_id"], 1)
        self.assertEqual(kwargs["message_id"], 2)


if __name__ == "__main__":
    unittest.main()

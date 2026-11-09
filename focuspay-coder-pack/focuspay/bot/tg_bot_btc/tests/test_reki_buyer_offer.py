"""Подсказка «доплатить/переплатить» покупателю, когда реквизитов нет."""
import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.reki_snapshot import (  # noqa: E402
    FIT_EXACT,
    RekiBand,
    RekiSection,
    RekiSnapshot,
    SUB_TOKEN_SBP,
    fit_reki,
)
from services.requisite_retry_client import (  # noqa: E402
    REKI_CALLBACK,
    RETRY_CALLBACK,
    reki_offer_text,
    retry_keyboard,
)


def _snapshot(now=None):
    return RekiSnapshot(
        sections={
            SUB_TOKEN_SBP: RekiSection(
                sub_token=SUB_TOKEN_SBP,
                count=2,
                total_rub=Decimal("5503.00"),
                bands=(
                    RekiBand(Decimal("2403"), Decimal("2403"), Decimal("2403")),
                    RekiBand(Decimal("3000"), Decimal("3100"), Decimal("3100")),
                ),
            )
        },
        taken_at=now or datetime.now(timezone.utc),
    )


class OfferTextTests(unittest.TestCase):
    def test_over_pay_text_mentions_credit(self):
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 2950)
        text = reki_offer_text(fit)
        self.assertIn("3000 ₽", text)
        self.assertIn("50 ₽", text)
        self.assertIn("крипту получите на всю эту сумму", text.lower())

    def test_top_up_text_warns_about_balance(self):
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 2450)
        text = reki_offer_text(fit)
        self.assertIn("2403 ₽", text)
        self.assertIn("остаток обменяете отдельно", text)

    def test_nothing_to_offer(self):
        self.assertIsNone(reki_offer_text(None))
        exact = fit_reki(_snapshot(), SUB_TOKEN_SBP, 3050)
        self.assertEqual(exact.kind, FIT_EXACT)
        self.assertIsNone(reki_offer_text(exact))


class KeyboardTests(unittest.TestCase):
    def test_retry_only(self):
        rows = retry_keyboard().inline_keyboard
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0].callback_data, RETRY_CALLBACK)

    def test_offer_button_carries_amount(self):
        rows = retry_keyboard(Decimal("3000.00")).inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0].callback_data, f"{REKI_CALLBACK}:3000")
        self.assertIn("3000 ₽", rows[0][0].text)
        self.assertEqual(rows[1][0].callback_data, RETRY_CALLBACK)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import handlers.exchange_flow as flow

        self.flow = flow

    def _ctx(self, data):
        ctx = MagicMock()
        ctx.user_data = dict(data)
        return ctx

    async def test_fit_uses_draft_amount_and_method(self):
        ctx = self._ctx({"fiat_amount": 2950, "sub_token": SUB_TOKEN_SBP})
        with patch("services.reki_poll.load_snapshot", AsyncMock(return_value=_snapshot())):
            fit = await self.flow._reki_fit(ctx)
        self.assertEqual(int(fit.pay_rub), 3000)

    async def test_no_fit_without_amount(self):
        ctx = self._ctx({"sub_token": SUB_TOKEN_SBP})
        self.assertIsNone(await self.flow._reki_fit(ctx))

    async def test_db_failure_is_silent(self):
        ctx = self._ctx({"fiat_amount": 2950, "sub_token": SUB_TOKEN_SBP})
        with patch("services.reki_poll.load_snapshot", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertIsNone(await self.flow._reki_fit(ctx))

    async def test_offer_is_stashed_after_clear(self):
        ctx = self._ctx({})
        body = {
            "crypto": "USDT_TRC20",
            "network": "trc20",
            "wallet": "T" * 34,
            "sub_token": SUB_TOKEN_SBP,
            "rate": 95.5,
            "amount_currency": None,
        }
        fit = fit_reki(_snapshot(), SUB_TOKEN_SBP, 2950)
        self.flow._stash_reki_offer(ctx, body, fit)
        offer = ctx.user_data["reki_offer"]
        self.assertEqual(offer["pay_rub"], 3000)
        self.assertEqual(offer["wallet"], body["wallet"])

    async def test_nothing_stashed_without_fit(self):
        ctx = self._ctx({})
        self.flow._stash_reki_offer(ctx, {"wallet": "x"}, None)
        self.assertNotIn("reki_offer", ctx.user_data)

    async def test_press_rebuilds_draft_and_runs(self):
        ctx = self._ctx(
            {
                "reki_offer": {
                    "pay_rub": 3000,
                    "crypto": "USDT_TRC20",
                    "network": "trc20",
                    "wallet": "T" * 34,
                    "sub_token": SUB_TOKEN_SBP,
                    "rate": 100.0,
                    "amount_currency": None,
                }
            }
        )
        update = MagicMock()
        update.effective_user = MagicMock(id=42)
        run = AsyncMock()
        with patch.object(self.flow, "_run_buy_draft", run), patch.object(
            self.flow, "_tg_msg", MagicMock(return_value=None)
        ):
            await self.flow._handle_reki_offer_press(update, ctx, "3000")
        run.assert_awaited_once()
        self.assertEqual(ctx.user_data["fiat_amount"], 3000)
        self.assertEqual(ctx.user_data["crypto"], "usdt")
        self.assertEqual(ctx.user_data["crypto_amount"], 30.0)
        self.assertTrue(ctx.user_data["requisite_retry_attempt"])

    async def test_press_rejects_tampered_amount(self):
        ctx = self._ctx({"reki_offer": {"pay_rub": 3000, "rate": 100.0, "wallet": "T" * 34}})
        update = MagicMock()
        update.effective_user = MagicMock(id=42)
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        run = AsyncMock()
        with patch.object(self.flow, "_run_buy_draft", run), patch.object(
            self.flow, "_tg_msg", MagicMock(return_value=msg)
        ), patch.object(self.flow, "menu_for", AsyncMock(return_value=None)):
            await self.flow._handle_reki_offer_press(update, ctx, "999999")
        run.assert_not_awaited()
        self.assertIn("больше не действует", msg.reply_text.await_args.args[0])

    def _reject_ctx(self):
        return self._ctx(
            {
                "fiat_amount": 2950,
                "sub_token": SUB_TOKEN_SBP,
                "crypto": "usdt",
                "network": "trc20",
                "buy_wallet": "T" * 34,
                "effective_rate": 95.5,
                "crypto_amount": 30.0,
            }
        )

    async def _run_reject(self, ctx, snapshot):
        update = MagicMock()
        update.effective_user = MagicMock(id=42)
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        with patch("services.reki_poll.load_snapshot", AsyncMock(return_value=snapshot)), patch.object(
            self.flow, "_tg_msg", MagicMock(return_value=msg)
        ), patch.object(self.flow, "menu_for", AsyncMock(return_value=None)):
            await self.flow._reply_no_requisites_for_amount(update, ctx, None)
        return msg

    async def test_reject_offers_nearest_amount(self):
        ctx = self._reject_ctx()
        msg = await self._run_reject(ctx, _snapshot())
        first = msg.reply_text.await_args_list[0]
        self.assertIn("3000 ₽", first.args[0])
        rows = first.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(rows[0][0].callback_data, f"{REKI_CALLBACK}:3000")
        self.assertEqual(ctx.user_data["reki_offer"]["pay_rub"], 3000)

    async def test_reject_falls_back_to_plain_text(self):
        ctx = self._reject_ctx()
        msg = await self._run_reject(ctx, RekiSnapshot(sections={}, taken_at=None))
        msg.reply_text.assert_awaited_once()
        self.assertIn("Нет реквизитов на эту сумму", msg.reply_text.await_args.args[0])
        self.assertNotIn("reki_offer", ctx.user_data)

    async def test_reject_escapes_plan_message(self):
        ctx = self._reject_ctx()
        update = MagicMock()
        update.effective_user = MagicMock(id=42)
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        with patch("services.reki_poll.load_snapshot", AsyncMock(return_value=_snapshot())), patch.object(
            self.flow, "_tg_msg", MagicMock(return_value=msg)
        ), patch.object(self.flow, "menu_for", AsyncMock(return_value=None)):
            await self.flow._reply_no_requisites_for_amount(update, ctx, "сумма < 3000")
        self.assertIn("&lt; 3000", msg.reply_text.await_args_list[0].args[0])

    async def test_press_without_offer(self):
        ctx = self._ctx({})
        update = MagicMock()
        update.effective_user = MagicMock(id=42)
        msg = MagicMock()
        msg.reply_text = AsyncMock()
        run = AsyncMock()
        with patch.object(self.flow, "_run_buy_draft", run), patch.object(
            self.flow, "_tg_msg", MagicMock(return_value=msg)
        ), patch.object(self.flow, "menu_for", AsyncMock(return_value=None)):
            await self.flow._handle_reki_offer_press(update, ctx, "3000")
        run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

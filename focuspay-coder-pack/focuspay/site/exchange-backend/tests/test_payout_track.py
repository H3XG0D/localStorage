"""Цена ускорения Bitcoin: сеть × 1.2, сдвиг цены, возврат, чужой txid."""
from decimal import Decimal
from pathlib import Path
import unittest

from payout_track import (
    PushError,
    buyer_price,
    confirmation_label,
    cost_from_delta,
    eta_label,
    mempool_bump_delta_btc,
    next_block_sat_vb,
    operator_prompt_keyboard,
    operator_prompt_text,
    projected_minutes,
    push_decision,
    refund_delta,
    refund_split,
    resolve_charge,
    settlement,
    bump_speed_targets,
    collapse_push_options,
    label_for_quoted_rate,
)


ROOT = Path(__file__).resolve().parents[1]


class BuyerPriceTests(unittest.TestCase):
    def test_thirty_rubles_of_network_cost_is_thirty_six(self):
        self.assertEqual(buyer_price(Decimal("30")), Decimal("36.00"))
        self.assertEqual(buyer_price(30), Decimal("36.00"))

    def test_markup_rounds_half_up_to_kopecks(self):
        self.assertEqual(buyer_price(Decimal("10.04")), Decimal("12.05"))
        self.assertEqual(buyer_price(Decimal("0")), Decimal("0.00"))

    def test_delta_times_rate_then_markup(self):
        cost = cost_from_delta(Decimal("0.000005"), Decimal("6000000"))
        self.assertEqual(cost, Decimal("30.00"))
        self.assertEqual(buyer_price(cost), Decimal("36.00"))


class ChargeDriftTests(unittest.TestCase):
    def test_growth_above_one_ruble_is_refused(self):
        with self.assertRaises(PushError) as exc:
            resolve_charge(Decimal("36.00"), Decimal("37.01"))
        self.assertEqual(exc.exception.code, "price_changed")
        self.assertEqual(exc.exception.extra["push_price_rub"], 37.01)

    def test_growth_within_one_ruble_keeps_the_agreed_price(self):
        self.assertEqual(resolve_charge(Decimal("36.00"), Decimal("37.00")), Decimal("36.00"))

    def test_cheaper_quote_charges_the_fresh_price(self):
        self.assertEqual(resolve_charge(Decimal("36.00"), Decimal("30.00")), Decimal("30.00"))


class RefundTests(unittest.TestCase):
    def test_cheaper_bump_refunds_the_difference_after_markup(self):
        # Списали 36 ₽ (котировка 30). Факт сети 25 ₽ → покупателю 30 ₽, вернуть 6 ₽.
        self.assertEqual(refund_delta(Decimal("36.00"), Decimal("25")), Decimal("6.00"))

    def test_same_cost_refunds_nothing(self):
        self.assertEqual(refund_delta(Decimal("36.00"), Decimal("30")), Decimal("0.00"))

    def test_node_refusal_returns_the_whole_charge(self):
        done = settlement(Decimal("36.00"), Decimal("30"), bump_ok=False, definite=True)
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["refund"], Decimal("36.00"))
        self.assertEqual(done["keep"], Decimal("0.00"))

    def test_unknown_outcome_does_not_refund(self):
        done = settlement(Decimal("36.00"), Decimal("0"), bump_ok=False, definite=False)
        self.assertEqual(done["status"], "unknown")
        self.assertEqual(done["refund"], Decimal("0.00"))

    def test_successful_cheaper_bump_keeps_markup_on_the_actual_cost(self):
        done = settlement(Decimal("36.00"), Decimal("25"), bump_ok=True, definite=True)
        self.assertEqual(done["status"], "sent")
        self.assertEqual(done["refund"], Decimal("6.00"))
        self.assertEqual(done["keep"], Decimal("30.00"))

    def test_refund_returns_partner_balance_first(self):
        self.assertEqual(
            refund_split(Decimal("20"), Decimal("10"), Decimal("6"), Decimal("6")),
            (Decimal("0.00"), Decimal("0.00"), Decimal("6.00")),
        )


class ForeignTxTests(unittest.TestCase):
    def test_operator_txid_cannot_be_pushed(self):
        decision = push_decision(
            coin="btc",
            ours=False,
            confirmed=False,
            quote_ok=True,
            price=Decimal("36.00"),
        )
        self.assertFalse(decision["can_push"])
        self.assertEqual(decision["push_reason"], "not_our_wallet")
        self.assertIsNone(decision["push_price_rub"])

    def test_other_coins_show_no_button(self):
        decision = push_decision(
            coin="usdt",
            ours=False,
            confirmed=False,
            quote_ok=False,
            price=None,
        )
        self.assertEqual(decision["push_reason"], "not_btc")

    def test_our_unconfirmed_bitcoin_offers_the_marked_up_price(self):
        decision = push_decision(
            coin="btc",
            ours=True,
            confirmed=False,
            quote_ok=True,
            price=buyer_price(Decimal("30")),
        )
        self.assertTrue(decision["can_push"])
        self.assertEqual(decision["push_price_rub"], 36.0)


class EtaTests(unittest.TestCase):
    def test_confirmation_labels(self):
        self.assertEqual(confirmation_label(0, confirmed=False), "0 подтверждений")
        self.assertEqual(confirmation_label(1, confirmed=True), "В сети · 1 подтверждение")
        self.assertEqual(confirmation_label(2, confirmed=False), "2 подтверждения")
        self.assertEqual(confirmation_label(11, confirmed=False), "11 подтверждений")
        self.assertEqual(confirmation_label(21, confirmed=False), "21 подтверждение")

    def test_next_block_is_about_ten_minutes(self):
        blocks = [{"feeRange": [20, 40]}, {"feeRange": [8, 19]}, {"feeRange": [1, 7]}]
        minutes = projected_minutes("btc", 25, blocks)
        self.assertEqual(minutes, 10)
        self.assertEqual(eta_label("btc", minutes, confirmed=False), "около 10 минут")

    def test_third_projected_block_is_twenty_to_thirty_minutes(self):
        blocks = [{"feeRange": [30, 50]}, {"feeRange": [15, 29]}, {"feeRange": [5, 14]}]
        minutes = projected_minutes("btc", 6, blocks)
        self.assertEqual(minutes, 30)
        self.assertEqual(eta_label("btc", minutes, confirmed=False), "около 20–30 минут")

    def test_below_the_projected_window_is_more_than_an_hour(self):
        blocks = [{"feeRange": [10, 20]}] * 8
        minutes = projected_minutes("btc", 1, blocks)
        self.assertGreater(minutes, 60)
        self.assertEqual(eta_label("btc", minutes, confirmed=False), "больше часа")

    def test_tron_wait_is_about_a_minute(self):
        self.assertEqual(eta_label("usdt", projected_minutes("usdt", None, None), confirmed=False), "около минуты")
        self.assertIsNone(eta_label("btc", 10, confirmed=True))


class SpeedOptionTests(unittest.TestCase):
    def test_three_speeds_use_the_cheapest_floor_inside_each_cap(self):
        blocks = [
            {"feeRange": [8, 12]},
            {"feeRange": [4, 7]},
            {"feeRange": [2, 3]},
            {"feeRange": [1.5, 1.9]},
            {"feeRange": [1.2, 1.4]},
            {"feeRange": [1.05, 1.1]},
        ]
        options = bump_speed_targets(1, blocks)
        self.assertEqual(
            [(item["target_sat_vb"], item["eta_label"]) for item in options],
            [
                (8, "около 10 минут"),
                (2, "около 20–30 минут"),
                (1.05, "около часа"),
            ],
        )

    def test_a_wait_that_is_not_faster_is_dropped(self):
        blocks = [{"feeRange": [8, 12]}, {"feeRange": [2, 4]}]
        options = bump_speed_targets(8, blocks)
        self.assertEqual(options, [])

    def test_same_eta_keeps_the_cheaper_price(self):
        kept = collapse_push_options(
            [
                {"eta_label": "около 10 минут", "price_rub": 80, "fee_rate_sat_vb": 8},
                {"eta_label": "около 10 минут", "price_rub": 40, "fee_rate_sat_vb": 4},
                {"eta_label": "около часа", "price_rub": 39.2, "fee_rate_sat_vb": 1.2},
                {"eta_label": "около часа", "price_rub": 20, "fee_rate_sat_vb": 1.05},
            ]
        )
        self.assertEqual([item["price_rub"] for item in kept], [40, 20])

    def test_one_ruble_gap_keeps_only_the_faster_option(self):
        kept = collapse_push_options(
            [
                {"eta_label": "около 10 минут", "price_rub": 62, "fee_rate_sat_vb": 8},
                {"eta_label": "около 20–30 минут", "price_rub": 61.4, "fee_rate_sat_vb": 2},
            ]
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["eta_label"], "около 10 минут")

    def test_node_rbf_step_relabels_the_option_by_the_actual_rate(self):
        blocks = [
            {"feeRange": [8, 12]},
            {"feeRange": [4, 7]},
            {"feeRange": [2, 3]},
            {"feeRange": [1.5, 1.9]},
            {"feeRange": [1.2, 1.4]},
            {"feeRange": [1.05, 1.1]},
        ]
        # 8 sat/vB = 0.00008 BTC/kvB. Нода подняла «часовую» цель до ближайшего блока.
        self.assertEqual(label_for_quoted_rate("около часа", 0.00008, blocks), "около 10 минут")


class OperatorTxTests(unittest.TestCase):
    def test_gap_to_next_block_is_marked_up(self):
        vsize = 141
        target = Decimal("10") + (Decimal("500") / Decimal(vsize))
        delta = mempool_bump_delta_btc(10, target, vsize)
        cost = cost_from_delta(delta, Decimal("6000000"))
        self.assertEqual(cost, Decimal("30.00"))
        self.assertEqual(buyer_price(cost), Decimal("36.00"))

    def test_already_in_next_block_has_no_delta(self):
        blocks = [{"feeRange": [8, 20]}]
        self.assertEqual(next_block_sat_vb(blocks), 8)
        self.assertEqual(mempool_bump_delta_btc(8, next_block_sat_vb(blocks), 141), Decimal("0"))

    def test_operator_with_a_price_can_be_asked(self):
        decision = push_decision(
            coin="btc",
            ours=False,
            confirmed=False,
            quote_ok=True,
            price=buyer_price(Decimal("30")),
            ask_operator=True,
        )
        self.assertTrue(decision["can_push"])
        self.assertEqual(decision["push_reason"], "operator")
        self.assertEqual(decision["push_price_rub"], 36.0)

    def test_waiting_for_operator_is_not_a_second_charge(self):
        decision = push_decision(
            coin="btc",
            ours=False,
            confirmed=False,
            quote_ok=True,
            price=Decimal("36"),
            pending=True,
            pending_kind="asked",
        )
        self.assertFalse(decision["can_push"])
        self.assertTrue(decision["push_pending"])
        self.assertEqual(decision["push_reason"], "operator")

    def test_prompt_names_the_price_and_the_buttons(self):
        text = operator_prompt_text(
            order_id="FP-9",
            crypto_amount=Decimal("0.01"),
            charged_rub=Decimal("36"),
            explorer="https://mempool.space/tx/" + "ab" * 32,
        )
        self.assertIn("FP-9", text)
        self.assertIn("36,00 ₽", text)
        self.assertNotIn("20%", text)
        keys = operator_prompt_keyboard(15)["inline_keyboard"][0]
        self.assertEqual(keys[0]["callback_data"], "oppush:15:1")
        self.assertEqual(keys[1]["callback_data"], "oppush:15:0")
        self.assertEqual(keys[0]["text"], "Пропушить")
        self.assertEqual(keys[1]["text"], "Не надо")


class LedgerKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_debit_and_refund_skip_the_buy_order_id(self):
        from decimal import Decimal
        from unittest.mock import AsyncMock, patch

        from payout_track import _credit, _debit, push_debit_key, push_refund_key

        conn = AsyncMock()
        debit_key = push_debit_key("FP-9")
        self.assertTrue(debit_key.startswith("btc-push:FP-9:"))
        self.assertNotEqual(debit_key, "FP-9")
        with patch(
            "payout_track._spendable",
            new=AsyncMock(return_value=(50.0, 0.0, 0.0)),
        ), patch(
            "payout_track.split_sources",
            return_value=(Decimal("36"), Decimal("0"), Decimal("0")),
        ):
            await _debit(conn, 7, Decimal("36"), "FP-9", ledger_key=debit_key)
        cashback_insert = conn.execute.await_args_list[0]
        self.assertIn("user_cashback_ledger", cashback_insert.args[0])
        self.assertEqual(cashback_insert.args[3], debit_key)
        self.assertNotEqual(cashback_insert.args[3], "FP-9")

        conn.execute.reset_mock()
        refund_key = push_refund_key(15)
        self.assertEqual(refund_key, "btc-push-refund:15")
        self.assertNotEqual(refund_key, debit_key)
        await _credit(
            conn,
            7,
            "FP-9",
            Decimal("36"),
            Decimal("0"),
            Decimal("0"),
            ledger_key=refund_key,
        )
        refund_insert = conn.execute.await_args_list[0]
        self.assertEqual(refund_insert.args[3], refund_key)
        self.assertNotEqual(refund_insert.args[3], "FP-9")


class RouteTests(unittest.TestCase):
    def test_track_route_is_registered_before_order_id(self):
        text = (ROOT / "routers" / "web_orders.py").read_text(encoding="utf-8")
        self.assertLess(text.index('"/orders/payout-track"'), text.index('"/orders/{order_id}"'))
        self.assertIn('"/orders/{order_id}/payout-push"', text)
        internal = (ROOT / "routers" / "chat_internal.py").read_text(encoding="utf-8")
        self.assertIn('"/payout-push/answer"', internal)
        bot = ROOT.parents[1] / "bot" / "tg_bot_btc" / "main.py"
        self.assertIn("payout_push_callback", bot.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

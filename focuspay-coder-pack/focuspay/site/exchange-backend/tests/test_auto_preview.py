"""Тестовая оценка автопилота на заявках."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from auto_preview import PreviewContext, payout_moment, preview_order_autopay, with_live_checks

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _ctx(paid: int, *, user_id: int = 1, override=None, banned=False) -> PreviewContext:
    ctx = PreviewContext()
    ctx.paid_buys[user_id] = [NOW - timedelta(days=i + 1) for i in range(paid)]
    ctx.overrides[user_id] = override
    if banned:
        ctx.banned.add(user_id)
    return ctx


def _order(**kw) -> dict:
    base = {
        "user_id": 1,
        "direction": "buy",
        "crypto": "btc",
        "fiat_amount": 5000,
        "status": "COMPLETED",
        "created_at": NOW,
        "requisites": "bc1qtest",
        "crypto_amount": 0.001,
    }
    base.update(kw)
    return base


class PreviewTests(unittest.TestCase):
    def setUp(self):
        patches = {
            "auto_preview.auto_no_shift_min_buy_paid": 5,
            "auto_preview.auto_no_shift_max_rub": 10_000,
            "auto_preview.auto_payout_max_rub": 10_000,
            "auto_preview.auto_whitelist_user_ids": set(),
            "auto_preview.auto_mode_enabled": False,
            "auto_preview.auto_no_shift_enabled": False,
            "auto_preview.auto_payout_enabled": False,
        }
        for target, value in patches.items():
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_regular_is_auto(self):
        out = preview_order_autopay(_order(), _ctx(7))
        self.assertEqual(out["verdict"], "auto")
        self.assertEqual(out["reasons"], [])
        self.assertFalse(out["toggles"]["mode"])

    def test_newcomer_is_manual(self):
        out = preview_order_autopay(_order(), _ctx(2))
        self.assertEqual(out["verdict"], "manual")
        self.assertIn("paid_buys", out["reasons"])

    def test_counts_only_buys_before_order(self):
        ctx = _ctx(3)
        ctx.paid_buys[1] += [NOW + timedelta(days=1), NOW + timedelta(days=2)]
        out = preview_order_autopay(_order(), ctx)
        self.assertEqual(out["verdict"], "manual")

    def test_over_cap_is_manual(self):
        out = preview_order_autopay(_order(fiat_amount=15_000), _ctx(9))
        self.assertIn("amount_cap", out["reasons"])

    def test_usdt_is_manual(self):
        out = preview_order_autopay(_order(crypto="usdt_trc20"), _ctx(9))
        self.assertIn("coin", out["reasons"])

    def test_sell_is_not_applicable(self):
        out = preview_order_autopay(_order(direction="sell"), _ctx(9))
        self.assertEqual(out["verdict"], "n/a")

    def test_override_on_skips_paid_count(self):
        out = preview_order_autopay(_order(), _ctx(0, override=True))
        self.assertEqual(out["verdict"], "auto")

    def test_payfast_is_first_check(self):
        out = preview_order_autopay(_order(), _ctx(7))
        self.assertEqual(out["checks"][0]["key"], "payfast")
        self.assertTrue(out["checks"][0]["ok"])

    def test_awaiting_payfast_is_waiting(self):
        out = preview_order_autopay(_order(status="AWAITING_CHECK"), _ctx(7))
        self.assertEqual(out["verdict"], "waiting")
        self.assertEqual(out["reasons"], ["payfast_waiting"])

    def test_canceled_is_manual(self):
        out = preview_order_autopay(_order(status="CANCELED"), _ctx(7))
        self.assertEqual(out["verdict"], "manual")
        self.assertEqual(out["reasons"], ["payfast_not_paid_order"])

    def test_client_reasons_win_over_payfast_wait(self):
        out = preview_order_autopay(_order(status="PENDING"), _ctx(1))
        self.assertEqual(out["verdict"], "manual")
        self.assertIn("paid_buys", out["reasons"])

    def test_override_off_and_ban_block(self):
        out = preview_order_autopay(_order(), _ctx(9, override=False, banned=True))
        self.assertEqual(set(out["reasons"]), {"override", "not_banned"})

    def test_completed_buy_would_send_without_claiming_now(self):
        out = preview_order_autopay(_order(), _ctx(7))
        moment = out["moment"]
        self.assertEqual(moment["key"], "would_send")
        self.assertEqual(moment["headline"], "По этой заявке случился бы автовывод")
        self.assertEqual([s["key"] for s in moment["steps"]], ["requisites", "payfast", "send"])
        self.assertEqual(moment["steps"][0]["text"], "Реквизиты выдали бы автоматически")
        self.assertEqual(moment["steps"][1]["text"], "Payfast подтвердил оплату")
        self.assertNotIn("сейчас", moment["headline"])

    def test_live_wallet_ok_says_would_send_now(self):
        out = preview_order_autopay(_order(), _ctx(7))
        live = [
            {"key": "signer", "ok": True, "detail": ""},
            {"key": "hot_balance", "ok": True, "detail": ""},
            {"key": "daily_cap", "ok": True, "detail": ""},
        ]
        with_live_checks(out, live, _order())
        self.assertEqual(out["moment"]["key"], "would_send_now")
        self.assertEqual(out["moment"]["headline"], "По этой заявке сейчас случился бы автовывод")
        self.assertNotIn("live_blocked", out)

    def test_live_signer_down_does_not_claim_send_now(self):
        order = _order()
        out = preview_order_autopay(order, _ctx(7))
        with_live_checks(out, [{"key": "signer", "ok": False, "detail": ""}], order)
        moment = out["moment"]
        self.assertEqual(moment["key"], "blocked_now")
        self.assertEqual(moment["headline"], "По этой заявке клиент подходит, но сейчас монеты бы не ушли")
        self.assertIn("кошелёк недоступен", moment["send_text"])
        self.assertEqual(out["live_blocked"], ["signer"])

    def test_waiting_payfast_send_is_later(self):
        out = preview_order_autopay(_order(status="AWAITING_CHECK"), _ctx(7))
        moment = out["moment"]
        self.assertEqual(moment["key"], "waiting_payfast")
        self.assertEqual(
            moment["headline"],
            "По этой заявке автовывод случился бы после подтверждения Payfast",
        )
        self.assertEqual(moment["steps"][2]["state"], "wait")

    def test_manual_client_never_reaches_send(self):
        out = preview_order_autopay(_order(crypto="usdt_trc20"), _ctx(9))
        self.assertEqual(out["moment"]["key"], "manual")
        self.assertEqual(out["moment"]["steps"][0]["text"], "Реквизиты выдал бы оператор")
        self.assertEqual(out["moment"]["steps"][2]["text"], "Автовывод не случился бы")

    def test_paid_or_tx_is_already_sent(self):
        paid = preview_order_autopay(_order(status="PAID"), _ctx(7))
        self.assertEqual(paid["moment"]["key"], "already_sent")
        self.assertEqual(paid["moment"]["headline"], "По этой заявке монеты уже отправлены")
        sent = preview_order_autopay(_order(payout_tx_hash="abc123"), _ctx(7))
        self.assertEqual(sent["moment"]["key"], "already_sent")

    def test_missing_address_blocks_send(self):
        order = _order(requisites="  ")
        moment = payout_moment(order, preview_order_autopay(order, _ctx(7)), [])
        self.assertEqual(moment["key"], "blocked_now")
        self.assertIn("нет адреса кошелька", moment["send_text"])

    def test_sell_has_no_send_moment(self):
        out = preview_order_autopay(_order(direction="sell"), _ctx(9))
        self.assertEqual(out["moment"]["key"], "n/a")
        self.assertEqual(out["moment"]["steps"], [])


if __name__ == "__main__":
    unittest.main()

"""Пейин-рельса: порог доверия, подбор карты, знак стоимости, гейт матчера."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from payin_requisite_rail import (
    ACTIVE_REQUISITE_STATUSES,
    PayinCandidate,
    buy_paid_count,
    complete_triangle_sell,
    complete_triangle_withdrawal,
    fit_payin,
    load_payin_candidates,
    open_withdrawal_triangle,
    parse_sell_fiat_bill,
    payin_card_fee_pct,
    pick_payin_candidate,
    reserve_payin_slot,
    user_can_use_payin_rail,
)
from payout_requisite_cost import payoff_rub
from payout_requisite_matcher import active_requisites, plan_for_requisite

ROOT = Path(__file__).resolve().parents[1]


def _cand(**over) -> PayinCandidate:
    now = datetime.now(timezone.utc)
    row = dict(
        id=1,
        operator_id=5,
        method="card",
        requisites="2202200112345678",
        bank="Сбер",
        holder_name="И. И.",
        cost_pct=Decimal("3"),
        crypto="usdt",
        deadline_at=now + timedelta(hours=2),
        max_checks=3,
        free_rub=Decimal("10000.00"),
        used_checks=0,
        created_at=now - timedelta(hours=2),
    )
    row.update(over)
    return PayinCandidate(**row)


class PickPayinTests(unittest.TestCase):
    def test_exact_fit_beats_larger_card(self):
        exact = _cand(id=2, free_rub=Decimal("5000"))
        bigger = _cand(id=1, free_rub=Decimal("12000"))
        chosen = pick_payin_candidate([bigger, exact], 5000)
        self.assertEqual(chosen.id, 2)

    def test_skips_when_amount_does_not_fit(self):
        self.assertIsNone(pick_payin_candidate([_cand(free_rub=Decimal("3000"))], 5000))

    def test_respects_max_checks(self):
        full = _cand(id=1, used_checks=3, max_checks=3, free_rub=Decimal("10000"))
        free = _cand(id=2, used_checks=1, max_checks=3, free_rub=Decimal("10000"))
        chosen = pick_payin_candidate([full, free], 4000)
        self.assertEqual(chosen.id, 2)

    def test_earlier_deadline_breaks_leftover_tie(self):
        later = _cand(id=1, deadline_at=datetime.now(timezone.utc) + timedelta(hours=5))
        sooner = _cand(id=2, deadline_at=datetime.now(timezone.utc) + timedelta(hours=1))
        chosen = pick_payin_candidate([later, sooner], 1000)
        self.assertEqual(chosen.id, 2)


class FitPayinTests(unittest.TestCase):
    def test_happy_close_within_fixed_cap(self):
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("5000"), created_at=now)
        fit = fit_payin([card], 4900, now=now)
        self.assertEqual(fit.kind, "round_up")
        self.assertEqual(fit.offer_mode, "happy")
        self.assertTrue(fit.closes)
        self.assertEqual(fit.credit_rub, Decimal("100.00"))
        self.assertTrue(fit.offer)
        fit150 = fit_payin([card], 4850, now=now)
        self.assertEqual(fit150.kind, "round_up")
        self.assertEqual(fit150.offer_mode, "happy")
        self.assertEqual(fit150.credit_rub, Decimal("150.00"))
        # фикс 500 ₽: gap 300 на 4700 закрывает happy
        self.assertEqual(fit_payin([card], 4700, now=now).offer_mode, "happy")
        # ровно 500 — ещё в допуске, 501 — уже нет
        self.assertEqual(fit_payin([card], 4500, now=now).offer_mode, "happy")
        self.assertNotEqual(fit_payin([card], 4499, now=now).offer_mode, "happy")
        close = _cand(free_rub=Decimal("2500"), created_at=now)
        fit_close = fit_payin([close], 2444, now=now)
        self.assertEqual(fit_close.kind, "round_up")
        self.assertEqual(fit_close.offer_mode, "happy")
        self.assertEqual(fit_close.pay_rub, Decimal("2500.00"))
        self.assertEqual(fit_close.credit_rub, Decimal("56.00"))

    def test_owner_case_3600_quote_offers_3990_card(self):
        """Карта 3990, котировка 3600 — зазор 390 ₽ в фиксе 500 → оффер доплатить."""
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("3990"), amount_rub=Decimal("3990"), created_at=now)
        fit = fit_payin([card], 3600, now=now)
        self.assertEqual(fit.kind, "round_up")
        self.assertEqual(fit.offer_mode, "happy")
        self.assertEqual(fit.pay_rub, Decimal("3990.00"))
        self.assertEqual(fit.credit_rub, Decimal("390.00"))
        self.assertTrue(fit.offer)

    def test_round_cap_is_fixed_and_never_exceeds_quote(self):
        from payin_requisite_rail import ROUND_UP_CAP_RUB, round_cap_kop

        self.assertEqual(ROUND_UP_CAP_RUB, 500)
        self.assertEqual(round_cap_kop(3600 * 100), 500 * 100)
        self.assertEqual(round_cap_kop(50000 * 100), 500 * 100)
        # мелкая котировка: доплата не больше самой суммы
        self.assertEqual(round_cap_kop(300 * 100), 300 * 100)
        self.assertEqual(round_cap_kop(0), 1)

    def test_bot_rail_mirror_uses_same_fixed_cap(self):
        bot_rail = Path(__file__).resolve().parents[3] / "bot" / "tg_bot_btc" / "services" / "payin_requisite_rail.py"
        src = bot_rail.read_text(encoding="utf-8")
        self.assertIn("ROUND_UP_CAP_RUB = 500", src)
        self.assertIn("min(to_kop(ROUND_UP_CAP_RUB), quote)", src)
        self.assertNotIn("Decimal(quote) * MATCH_ROUND_PCT", src)

    def test_amount_up_to_2000_accepts_only_a_closing_check(self):
        now = datetime.now(timezone.utc)
        small = _cand(
            free_rub=Decimal("1500"),
            amount_rub=Decimal("1500"),
            max_checks=3,
            doliv_limit_rub=2000,
            created_at=now - timedelta(hours=3),
        )
        self.assertEqual(fit_payin([small], 500, now=now).kind, "none")
        self.assertEqual(fit_payin([small], 1500, now=now).kind, "exact")
        happy = fit_payin([small], 1450, now=now)
        self.assertEqual(happy.kind, "round_up")
        self.assertTrue(happy.closes)
        larger = _cand(
            free_rub=Decimal("5000"),
            amount_rub=Decimal("5000"),
            created_at=now - timedelta(hours=3),
        )
        self.assertEqual(fit_payin([larger], 2000, now=now).kind, "as_quoted")

    def test_ten_k_two_checks_scenarios(self):
        now = datetime.now(timezone.utc)
        # После соло: 4800 на 10к/2 — as_quoted
        aged = _cand(
            free_rub=Decimal("10000"),
            max_checks=2,
            created_at=now - timedelta(minutes=61),
        )
        fit4800 = fit_payin([aged], 4800, now=now)
        self.assertEqual(fit4800.kind, "as_quoted")
        self.assertEqual(fit4800.pay_rub, Decimal("4800.00"))
        self.assertEqual(fit4800.offer_mode, "none")

        # Свежая карта: 4700 → цель слота 4800 (остаток 9600 / 2) silent
        fresh_slot = _cand(
            free_rub=Decimal("9600"),
            max_checks=2,
            created_at=now - timedelta(minutes=8),
        )
        silent = fit_payin([fresh_slot], 4700, now=now)
        self.assertEqual(silent.kind, "round_up")
        self.assertEqual(silent.offer_mode, "silent")
        self.assertFalse(silent.closes)
        self.assertEqual(silent.pay_rub, Decimal("4800.00"))
        self.assertEqual(silent.credit_rub, Decimal("100.00"))
        self.assertEqual(
            pick_payin_candidate([fresh_slot], 4700, now=now).id,
            fresh_slot.id,
        )

        # Закрытие остатка 5200: 5100 → happy
        rem = _cand(free_rub=Decimal("5200"), max_checks=1, created_at=now)
        happy = fit_payin([rem], 5100, now=now)
        self.assertEqual(happy.kind, "round_up")
        self.assertEqual(happy.offer_mode, "happy")
        self.assertTrue(happy.closes)
        self.assertEqual(happy.pay_rub, Decimal("5200.00"))
        self.assertEqual(happy.credit_rub, Decimal("100.00"))

        # 4000 при цели 5000: bump 1000 > 5% → none на свежей
        fresh_10k = _cand(
            free_rub=Decimal("10000"),
            max_checks=2,
            created_at=now - timedelta(minutes=8),
        )
        too_far = fit_payin([fresh_10k], 4000, now=now)
        self.assertEqual(too_far.kind, "none")
        self.assertFalse(too_far.offer)

    def test_first_hour_3300_skips_fresh_5000(self):
        now = datetime.now(timezone.utc)
        fresh = _cand(free_rub=Decimal("5000"), created_at=now - timedelta(minutes=8))
        fit = fit_payin([fresh], 3300, now=now)
        self.assertEqual(fit.kind, "none")
        self.assertIsNone(pick_payin_candidate([fresh], 3300, now=now))

    def test_after_hour_3300_sits_as_quoted(self):
        now = datetime.now(timezone.utc)
        aged = _cand(free_rub=Decimal("5000"), created_at=now - timedelta(minutes=61))
        fit = fit_payin([aged], 3300, now=now)
        self.assertEqual(fit.kind, "as_quoted")
        self.assertEqual(fit.pay_rub, Decimal("3300.00"))
        self.assertFalse(fit.offer)
        self.assertEqual(pick_payin_candidate([aged], 3300, now=now).id, aged.id)

    def test_exact_5000_has_no_offer(self):
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("5000"), created_at=now)
        fit = fit_payin([card], 5000, now=now)
        self.assertEqual(fit.kind, "exact")
        self.assertFalse(fit.offer)
        self.assertEqual(pick_payin_candidate([card], 5000, now=now).id, card.id)

    def test_happy_round_up_needs_explicit_accept(self):
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("5000"), created_at=now)
        self.assertIsNone(pick_payin_candidate([card], 4900, now=now))
        self.assertEqual(
            pick_payin_candidate([card], 4900, now=now, accept_round_up=True).id,
            card.id,
        )

    def test_fresh_26000_takes_fat_15000_and_18415(self):
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("26000"), created_at=now - timedelta(minutes=8))
        for amount in (15000, 18415):
            fit = fit_payin([card], amount, now=now)
            self.assertEqual(fit.kind, "as_quoted", amount)
            self.assertEqual(fit.pay_rub, Decimal(str(amount)))
            self.assertEqual(pick_payin_candidate([card], amount, now=now).id, card.id)

    def test_fresh_26000_skips_crumb_3300(self):
        now = datetime.now(timezone.utc)
        card = _cand(free_rub=Decimal("26000"), created_at=now - timedelta(minutes=8))
        self.assertEqual(fit_payin([card], 3300, now=now).kind, "none")

    def test_hunt_takes_close_check_not_two_small(self):
        now = datetime.now(timezone.utc)
        card = _cand(
            free_rub=Decimal("11000"),
            used_checks=1,
            created_at=now - timedelta(minutes=20),
            first_paid_at=now - timedelta(minutes=10),
        )
        self.assertEqual(fit_payin([card], 6000, now=now).kind, "none")
        self.assertEqual(fit_payin([card], 11000, now=now).kind, "exact")
        almost = _cand(
            id=2,
            free_rub=Decimal("11000"),
            used_checks=1,
            created_at=now - timedelta(minutes=20),
            first_paid_at=now - timedelta(minutes=10),
        )
        self.assertEqual(fit_payin([almost], 8800, now=now).kind, "as_quoted")

    def test_after_hunt_takes_6000(self):
        now = datetime.now(timezone.utc)
        card = _cand(
            free_rub=Decimal("11000"),
            used_checks=1,
            created_at=now - timedelta(minutes=50),
            first_paid_at=now - timedelta(minutes=46),
        )
        fit = fit_payin([card], 6000, now=now)
        self.assertEqual(fit.kind, "as_quoted")
        self.assertEqual(fit.pay_rub, Decimal("6000.00"))

    def test_hunt_takes_check_when_leftover_fits_doliv(self):
        now = datetime.now(timezone.utc)
        hunting = _cand(
            free_rub=Decimal("5000"),
            used_checks=1,
            created_at=now - timedelta(minutes=70),
            first_paid_at=now - timedelta(minutes=10),
            doliv_limit_rub=2000,
        )
        self.assertEqual(fit_payin([hunting], 3300, now=now).kind, "as_quoted")
        self.assertEqual(fit_payin([hunting], 2500, now=now).kind, "none")

    def test_first_hour_still_skips_3300_even_with_doliv_limit(self):
        now = datetime.now(timezone.utc)
        fresh = _cand(
            free_rub=Decimal("5000"),
            created_at=now - timedelta(minutes=8),
            doliv_limit_rub=2000,
        )
        self.assertEqual(fit_payin([fresh], 3300, now=now).kind, "none")


class ParseSellBillTests(unittest.TestCase):
    def test_card_digits_and_bank_from_leftover(self):
        bill = parse_sell_fiat_bill("2202200112345678 Сбер", sub_token="CARDRUB")
        self.assertEqual(bill["method"], "card")
        self.assertEqual(bill["requisites"], "2202200112345678")
        self.assertEqual(bill["bank"], "Сбер")
        self.assertEqual(bill["holder_name"], "клиент")

    def test_sbp_plus7_and_8_prefix(self):
        plus = parse_sell_fiat_bill("+7 999 123-45-67 Тинькофф", sub_token="SBPRUB")
        self.assertEqual(plus["method"], "sbp")
        self.assertEqual(plus["requisites"], "79991234567")
        self.assertEqual(plus["bank"], "Тинькофф")
        eight = parse_sell_fiat_bill("8 999 123-45-67", sub_token="SBPRUB")
        self.assertEqual(eight["requisites"], "79991234567")

    def test_rejects_short_card(self):
        with self.assertRaises(ValueError):
            parse_sell_fiat_bill("2202", sub_token="CARDRUB")

    def test_rejects_short_sbp_phone(self):
        with self.assertRaises(ValueError) as ctx:
            parse_sell_fiat_bill("+799999999 сбербакнк")
        self.assertIn("телефон", str(ctx.exception).lower())


class TriangleCompleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_non_triangle_and_open_card(self):
        self.assertIsNone(await complete_triangle_sell({"status": "CLOSED"}, {"id": 5}))
        self.assertIsNone(
            await complete_triangle_sell(
                {
                    "id": 1,
                    "status": "PARTIAL",
                    "source_sell_order_id": "S1",
                    "paid_rub": Decimal("3300"),
                    "amount_rub": Decimal("5000"),
                },
                {"id": 5},
            )
        )

    async def test_marks_sell_paid_with_triangle_channel_and_doliv_only_fiat(self):
        sell = {
            "order_id": "S1",
            "status": "PENDING",
            "crypto_amount": Decimal("0.01"),
            "payment_snapshot": {},
        }
        updated = {**sell, "status": "PAID", "user_id": 11}
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=[sell, updated])
        conn.fetchval = AsyncMock(side_effect=[Decimal("1700.00"), Decimal("3300.00")])
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        row = {
            "id": 1,
            "status": "CLOSED",
            "source_sell_order_id": "S1",
            "paid_rub": Decimal("5000"),
            "amount_rub": Decimal("5000"),
            "operator_id": 5,
        }
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)
        fake_bridge = MagicMock()
        fake_bridge.update_order_status = AsyncMock(return_value=False)
        fake_bridge.notify_order_completed_for_user = AsyncMock()
        with patch.dict("sys.modules", {"db": fake_db, "bot_status_bridge": fake_bridge}):
            out = await complete_triangle_sell(row, {"id": 5})
        self.assertEqual(out["order_id"], "S1")
        self.assertEqual(out["doliv_rub"], 1700.0)
        sql, *args = conn.fetchrow.await_args_list[-1].args
        self.assertIn("operator_fiat_paid_out", sql)
        self.assertIn("status = 'PAID'", sql)
        self.assertEqual(args[0], "S1")
        self.assertEqual(args[3], 1700.0)
        snap = json.loads(args[4])
        self.assertEqual(snap["payout_channel"], "triangle")
        self.assertEqual(snap["triangle_doliv_rub"], 1700.0)
        self.assertEqual(snap["triangle_buy_rub"], 3300.0)


class WithdrawalTriangleTests(unittest.IsolatedAsyncioTestCase):
    async def test_card_opens_payin_for_the_payout_amount(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=9)
        conn.fetchrow = AsyncMock(return_value={"id": 3, "status": "OPEN"})
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)
        with patch.dict("sys.modules", {"db": fake_db}):
            out = await open_withdrawal_triangle(
                {
                    "id": 4,
                    "method": "card",
                    "requisites": "2200700123456789 Сбер",
                    "amount_rub": Decimal("500.00"),
                    "payout_amount_rub": Decimal("400.00"),
                }
            )
        self.assertEqual(out["status"], "OPEN")
        sql, *args = conn.fetchrow.await_args.args
        self.assertIn("source_withdrawal_id", sql)
        self.assertIn("'OPEN'", sql)
        self.assertEqual(args[0], 9)
        self.assertEqual(args[1], "Вывод #4")
        self.assertEqual(args[2], "card")
        self.assertEqual(args[6], Decimal("400.00"))
        self.assertEqual(args[7], 1)
        self.assertEqual(args[8], 0)
        self.assertEqual(args[10], 4)

    async def test_larger_card_keeps_three_checks_and_doliv(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=9)
        conn.fetchrow = AsyncMock(return_value={"id": 3, "status": "OPEN"})
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)
        with patch.dict("sys.modules", {"db": fake_db}):
            await open_withdrawal_triangle(
                {
                    "id": 8,
                    "method": "card",
                    "requisites": "2200700123456789",
                    "payout_amount_rub": Decimal("4900.00"),
                }
            )
        _sql, *args = conn.fetchrow.await_args.args
        self.assertEqual(args[2], "card")
        self.assertEqual(args[6], Decimal("4900.00"))
        self.assertEqual(args[7], 3)
        self.assertEqual(args[8], 1000)

    async def test_disabled_triangle_does_not_open_a_card(self):
        with patch("runtime_settings.triangle_enabled", return_value=False):
            out = await open_withdrawal_triangle(
                {
                    "id": 4,
                    "method": "card",
                    "requisites": "2200700123456789",
                    "payout_amount_rub": Decimal("400"),
                }
            )
        self.assertIsNone(out)

    async def test_phone_opens_sbp_and_crypto_stays_manual(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=9)
        conn.fetchrow = AsyncMock(return_value={"id": 3, "status": "OPEN", "method": "sbp"})
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        fake_db = MagicMock()
        fake_db.get_pool = AsyncMock(return_value=pool)
        with patch.dict("sys.modules", {"db": fake_db}):
            out = await open_withdrawal_triangle(
                {
                    "id": 65,
                    "method": "card",
                    "requisites": "80617395744 Озон Банк",
                    "amount_rub": Decimal("1000"),
                    "payout_amount_rub": Decimal("988.00"),
                }
            )
        self.assertEqual(out["status"], "OPEN")
        _sql, *args = conn.fetchrow.await_args.args
        self.assertEqual(args[2], "sbp")
        self.assertEqual(args[3], "70617395744")
        self.assertEqual(args[6], Decimal("988.00"))
        self.assertEqual(args[7], 1)
        self.assertEqual(args[8], 0)

    def test_labels_say_where_the_withdrawal_stands(self):
        from payin_requisite_rail import live_triangle_label, missing_triangle_label

        self.assertEqual(live_triangle_label("sbp", "OPEN"), "В приёме, СБП")
        self.assertEqual(live_triangle_label("card", "PARTIAL"), "В приёме, карта")
        self.assertEqual(live_triangle_label("card", "QUEUED"), "Ждёт включения")
        self.assertIsNone(live_triangle_label("card", "EXPIRED"))
        with patch("runtime_settings.triangle_enabled", return_value=True):
            self.assertEqual(
                missing_triangle_label({"method": "card", "requisites": "нет номера"}),
                "Не встал: не разобрали номер",
            )
            self.assertEqual(
                missing_triangle_label({"method": "card", "requisites": "80617395744"}),
                "Не встал: приём ещё не открыт",
            )
        with patch("runtime_settings.triangle_enabled", return_value=False):
            self.assertEqual(
                missing_triangle_label({"method": "card", "requisites": "2200700123456789"}),
                "Не встал: треугольник выключен",
            )
        self.assertIsNone(missing_triangle_label({"method": "crypto", "requisites": "TXYZ"}))
        self.assertEqual(
            missing_triangle_label(
                {"method": "card", "requisites": "80617395744", "triangle_gave_up": True}
            ),
            "Ручная выплата: покупатель не нашёлся",
        )

    async def test_reopen_skips_withdrawal_sent_to_manual_payout(self):
        from payin_requisite_rail import MANUAL_PAYOUT_NOTE, reopen_pending_withdrawal_triangles

        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        self.assertEqual(await reopen_pending_withdrawal_triangles(conn), 0)
        sql, *args = conn.fetch.await_args.args
        self.assertIn("r.close_note = $2", sql)
        self.assertEqual(args[1], MANUAL_PAYOUT_NOTE)

    async def test_card_buy_skips_withdrawal_phone(self):
        from payin_requisite_rail import collect_payin_pool

        phone = _cand(id=1, method="sbp", requisites="70617395744", from_withdrawal=True)
        card = _cand(id=2, method="card", requisites="2200700123456789", from_withdrawal=True)
        own_phone = _cand(id=3, method="sbp", requisites="79001112233", from_withdrawal=False)

        async def load(_conn, *, method, for_update=True):
            del for_update
            if method == "sbp":
                return [phone, own_phone]
            return [card]

        with patch("payin_requisite_rail.load_payin_candidates", new=load):
            card_pool = await collect_payin_pool(None, "CARDRUB", for_update=False)
            sbp_pool = await collect_payin_pool(None, "SBPRUB", for_update=False)
        self.assertEqual([c.id for c in card_pool], [2, 3])
        self.assertEqual([c.id for c in sbp_pool], [1, 3])

    def test_orders_screen_shows_triangle_label(self):
        orders = (
            ROOT.parents[1]
            / "focussite"
            / "frontend"
            / "src"
            / "panel"
            / "operator"
            / "OperatorOrders.tsx"
        ).read_text()
        payin = (
            ROOT.parents[1]
            / "focussite"
            / "frontend"
            / "src"
            / "panel"
            / "operator"
            / "OperatorPayoutRequisites.tsx"
        ).read_text()
        self.assertIn("triangle_label", orders)
        self.assertIn("Открыть приём", orders)
        self.assertIn("unopened_withdrawals", payin)
        self.assertIn("сразу в «Принимают»", payin)

    async def test_crypto_stays_manual(self):
        self.assertIsNone(
            await open_withdrawal_triangle(
                {
                    "id": 2,
                    "method": "crypto",
                    "requisites": "TXYZ",
                    "amount_rub": Decimal("5000"),
                }
            )
        )

    async def test_closed_card_marks_withdrawal_paid(self):
        pending = {"id": 4, "status": "pending", "amount_rub": 1500, "referrer_user_id": 1, "method": "card"}
        paid = {**pending, "status": "paid"}
        with (
            patch("user_referral_withdraw.get_withdrawal", new=AsyncMock(return_value=pending)),
            patch(
                "user_referral_withdraw.process_withdrawal_paid",
                new=AsyncMock(return_value=(paid, None)),
            ) as proc,
            patch("user_referral_withdraw.notify_withdrawal_completed", new=AsyncMock()),
        ):
            out = await complete_triangle_withdrawal(
                {
                    "status": "CLOSED",
                    "source_withdrawal_id": 4,
                    "paid_rub": Decimal("1500"),
                    "amount_rub": Decimal("1500"),
                },
                {"id": 5},
            )
        self.assertEqual(out["withdrawal_id"], 4)
        self.assertFalse(out["already_paid"])
        proc.assert_awaited_once()

    async def test_manual_payout_blocked_while_card_is_live_or_paid(self):
        from user_referral_withdraw import manual_triangle_payout_error

        live = MagicMock()
        live.fetchval = AsyncMock(side_effect=[None, 1])
        msg = await manual_triangle_payout_error(live, 4)
        self.assertIn("приёме", msg)

        paid = MagicMock()
        paid.fetchval = AsyncMock(return_value=1)
        msg = await manual_triangle_payout_error(paid, 4)
        self.assertIn("уже есть оплата", msg)


class TrustGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_buy_paid_count_sql_filters_buy_and_final_statuses(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=4)
        self.assertEqual(await buy_paid_count(conn, 42), 4)
        sql, uid = conn.fetchval.await_args.args
        self.assertEqual(uid, 42)
        self.assertIn("lower(direction) = 'buy'", sql)
        self.assertIn("'PAID'", sql)
        self.assertIn("'COMPLETED'", sql)

    async def test_threshold_blocks_until_enough_buys(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=2)
        with patch("payin_requisite_rail.payin_min_buy_paid", return_value=3):
            self.assertFalse(await user_can_use_payin_rail(conn, 7))
        conn.fetchval = AsyncMock(return_value=3)
        with patch("payin_requisite_rail.payin_min_buy_paid", return_value=3):
            self.assertTrue(await user_can_use_payin_rail(conn, 7))


class CostSignTests(unittest.TestCase):
    def test_card_fee_is_cost_pct_as_fraction(self):
        self.assertEqual(payin_card_fee_pct(3), 0.03)
        self.assertEqual(payin_card_fee_pct(-1), -0.01)
        self.assertEqual(payin_card_fee_pct(0), 0.0)

    def test_payin_payoff_is_reversed_vs_payout(self):
        paid, pct = Decimal("10000"), Decimal("3")
        self.assertEqual(payoff_rub(paid, pct, "payout"), Decimal("10300.00"))
        self.assertEqual(payoff_rub(paid, pct, "payin"), Decimal("9700.00"))
        self.assertEqual(payoff_rub(paid, Decimal("-3"), "payin"), Decimal("10300.00"))


class MatcherGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_payin_plan_is_forecast_not_sell_queue(self):
        from datetime import datetime, timedelta, timezone

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=Decimal("0"))
        conn.fetch = AsyncMock(return_value=[])
        row = {
            "id": 1,
            "direction": "payin",
            "method": "sbp",
            "crypto": "usdt",
            "amount_rub": Decimal("26000"),
            "paid_rub": Decimal("0"),
            "max_checks": 3,
            "doliv_limit_rub": 2000,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
        }
        plan, free = await plan_for_requisite(conn, row)
        self.assertEqual(free, Decimal("26000.00"))
        self.assertIsNotNone(plan)
        self.assertEqual((plan.extra or {}).get("kind"), "forecast")
        self.assertEqual(plan.leftover_kop, 0)
        self.assertEqual((plan.extra or {}).get("splits")[0]["checks"], [10000, 8000, 8000])
        buy_sql = [
            str(call.args[0])
            for call in conn.fetch.await_args_list
            if call.args and "orders o" in str(call.args[0])
        ]
        self.assertTrue(buy_sql)
        self.assertIn("lower(o.direction) = 'buy'", buy_sql[0])
        self.assertNotIn("lower(o.direction) = 'sell'", buy_sql[0])

    async def test_active_requisites_query_keeps_payout_only(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        await active_requisites(conn)
        sql = conn.fetch.await_args.args[0]
        self.assertIn("COALESCE(direction, 'payout') = 'payout'", sql)

    async def test_load_and_reserve_skip_queued_unconfirmed(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        await load_payin_candidates(conn, method="sbp", for_update=True)
        sql, statuses, method = conn.fetch.await_args.args
        self.assertEqual(method, "sbp")
        self.assertEqual(list(statuses), list(ACTIVE_REQUISITE_STATUSES))
        self.assertNotIn("QUEUED", statuses)
        self.assertIn("confirmed_at IS NOT NULL", sql)

        conn.fetch = AsyncMock(return_value=[])
        out = await reserve_payin_slot(
            conn, order_id="B1", amount_rub=6000, sub_token="SBPRUB"
        )
        self.assertIsNone(out)
        sql = conn.fetch.await_args.args[0]
        self.assertIn("confirmed_at IS NOT NULL", sql)
        self.assertNotIn("QUEUED", conn.fetch.await_args.args[1])

    async def test_load_skips_card_with_open_reserve(self):
        row = {
            "id": 7,
            "operator_id": 5,
            "method": "sbp",
            "requisites": "79001234567",
            "bank": "Сбер",
            "holder_name": "Иван",
            "cost_pct": Decimal("0"),
            "crypto": "usdt",
            "deadline_at": datetime.now(timezone.utc) + timedelta(hours=2),
            "max_checks": 3,
            "amount_rub": Decimal("20000"),
            "paid_rub": Decimal("0"),
            "created_at": datetime.now(timezone.utc),
            "doliv_limit_rub": 2000,
        }
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[row])
        # COUNT(*) open RESERVED > 0
        conn.fetchval = AsyncMock(return_value=1)
        out = await load_payin_candidates(conn, method="sbp", for_update=False)
        self.assertEqual(out, [])
        self.assertTrue(
            any("status = 'RESERVED'" in str(c.args[0]) for c in conn.fetchval.await_args_list)
        )


class MigrationTests(unittest.TestCase):
    def test_orders_payin_requisite_column(self):
        sql = (
            ROOT.parents[1]
            / "bot"
            / "tg_bot_btc"
            / "migrations"
            / "add_order_payin_requisite.sql"
        ).read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS payin_requisite_id", sql)

    def test_allocation_kind_allows_payin(self):
        sql = (ROOT / "migrations" / "add_payout_requisites.sql").read_text()
        self.assertIn("'payin'", sql)
        self.assertIn("kind IN ('order', 'doliv', 'payin')", sql)
        self.assertIn("QUEUED", sql)

    def test_withdrawal_triangle_migration(self):
        sql = (ROOT / "migrations" / "add_triangle_source_withdrawal.sql").read_text()
        self.assertIn("source_withdrawal_id", sql)
        self.assertIn("ux_payout_req_source_withdrawal_live", sql)

    def test_queue_migration_adds_queued_status(self):
        sql = (ROOT / "migrations" / "add_payout_requisite_queue.sql").read_text()
        self.assertIn("confirmed_at", sql)
        self.assertIn("QUEUED", sql)

    def test_payin_open_requires_confirmed_at(self):
        sql = (ROOT / "migrations" / "add_payin_open_requires_confirm.sql").read_text()
        self.assertIn("operator_payout_requisites_payin_pool_confirm_chk", sql)
        self.assertIn("confirmed_at IS NOT NULL", sql)
        self.assertIn("SET DEFAULT 'QUEUED'", sql)
        base = (ROOT / "migrations" / "add_payout_requisites.sql").read_text()
        self.assertIn("DEFAULT 'QUEUED'", base)
        self.assertIn("operator_payout_requisites_payin_pool_confirm_chk", base)

    def test_triangle_source_sell_migration(self):
        sql = (ROOT / "migrations" / "add_triangle_source_sell.sql").read_text()
        self.assertIn("source_sell_order_id", sql)
        self.assertIn("ux_payout_req_source_sell_live", sql)
        self.assertIn("QUEUED", sql)

    def test_payin_candidates_exclude_queued(self):
        src = (ROOT / "payin_requisite_rail.py").read_text()
        self.assertIn("list(ACTIVE_REQUISITE_STATUSES)", src)
        self.assertIn("QUEUED", src)
        self.assertIn("confirmed_at IS NOT NULL", src)
        bot = (
            ROOT.parents[1] / "bot" / "tg_bot_btc" / "services" / "payin_requisite_rail.py"
        ).read_text()
        self.assertIn("confirmed_at IS NOT NULL", bot)

    def test_exchange_ui_offers_round_up(self):
        """Сайт и мини-апп предлагают ту же доплату, что бот. Раньше UI её прятал."""
        root = ROOT.parents[1] / "focussite" / "frontend" / "src"
        for path in (
            root / "pages" / "Exchange.tsx",
            root / "exchange-miniapp" / "screens" / "ExchangeScreen.tsx",
        ):
            src = path.read_text()
            self.assertIn("payinFit", src, path.name)
            self.assertIn("roundUpOffer", src, path.name)
            self.assertIn("payin_round_up", src, path.name)
            self.assertIn("Счастливая сделка", src, path.name)

    def test_bot_offers_round_up_to_close_near_card(self):
        src = (
            ROOT.parents[1]
            / "bot"
            / "tg_bot_btc"
            / "handlers"
            / "exchange_flow.py"
        ).read_text()
        self.assertIn('["step"] = "awaiting_payin_round"', src)
        self.assertIn("Счастливая сделка", src)
        self.assertIn("offer_mode == \"silent\"", src)
        self.assertIn("_offer_payin_round_if_close", src)
        self.assertIn("accept_round_up=False", src)
        self.assertNotIn('Оставить {int(quote_rub)} ₽', src)
        self.assertNotIn("ищем обычные реквизиты", src)
        self.assertIn("Без этой суммы реквизиты сейчас не выдаём.", src)

    def test_operator_ui_shows_payin_fill_forecast(self):
        src = (
            ROOT.parents[1]
            / "focussite"
            / "frontend"
            / "src"
            / "panel"
            / "operator"
            / "OperatorPayoutRequisites.tsx"
        ).read_text()
        self.assertIn("Как закроется", src)
        self.assertIn('kind === "forecast"', src)
        self.assertIn("weekday_label", src)
        self.assertIn("fill_eta_label", src)
        self.assertIn("plan.splits", src)
        self.assertIn("commission_note", src)
        self.assertIn("Клиенты начнут платить только после", src)
        self.assertIn("не приём", src)
        src = (ROOT / "routers" / "operator.py").read_text()
        self.assertIn("PERM_PAYOUT_REQUISITES_CONFIRM", src)
        self.assertIn("payin_received", src)
        self.assertIn("payin_reject", src)
        ui = (
            ROOT.parents[1]
            / "focussite"
            / "frontend"
            / "src"
            / "panel"
            / "operator"
            / "OperatorPayoutRequisites.tsx"
        ).read_text()
        self.assertIn("Чеки покупателей", ui)
        self.assertIn("Подтвердить и выплатить", ui)
        self.assertIn("Ждём оплату. Сама заявка — в «Заявках».", ui)
        self.assertIn("rejectPayinReceipt", ui)
        self.assertIn("PayinCheckPanel", ui)
        self.assertIn("getUser", ui)
        self.assertIn("Отмена снимает бронь", ui)
        self.assertNotIn("window.confirm", ui)
        self.assertIn("треугольник", ui)
        self.assertIn("Реквизиты продавца уходят в пул", ui)
        self.assertIn("createPayoutRequisiteFromSell", ui)
        self.assertIn("Доплата закрывает остаток", ui)
        self.assertIn("В пул реквизитов", ui)
        self.assertNotIn("Платить с нашей карты", ui)
        self.assertNotIn("Приём на карту продавца", ui)
        self.assertIn("Макс. чеков", ui)
        self.assertIn("MAX_CHECKS_CHIPS", ui)
        self.assertIn("В работе", ui)
        self.assertIn("Очередь", ui)
        self.assertIn("Завершённые", ui)
        self.assertIn("updatePayoutRequisiteMaxChecks", ui)
        self.assertIn("Закрыть за", ui)
        self.assertIn("Чеки сейчас", ui)
        self.assertIn("complete_triangle_sell", (ROOT / "routers" / "operator.py").read_text())
        self.assertIn("ensure_triangle_from_sell", (ROOT / "routers" / "operator.py").read_text())

    def test_operator_cancel_skips_payfast_on_payin_rail(self):
        src = (ROOT / "routers" / "operator.py").read_text()
        fn = src.split("async def cancel_order_by_operator", 1)[1].split("async def ", 1)[0]
        self.assertNotIn("payin_requisite_rail", fn)
        self.assertIn("payin_requisite_id", fn)
        self.assertIn("resolve_payfast_uuid_system(order_dict)", fn)
        self.assertIn("cancel_payin_for_order", fn)

    def test_web_orders_expose_fit_and_round_up(self):
        src = (ROOT / "routers" / "web_orders.py").read_text()
        self.assertIn("/orders/payin-fit", src)
        self.assertIn("payin_round_up", src)


def _triangle_card(**over) -> PayinCandidate:
    row = dict(
        amount_rub=Decimal("900.00"),
        free_rub=Decimal("900.00"),
        max_checks=1,
        cost_pct=Decimal("0"),
        is_triangle=True,
        from_withdrawal=True,
        client_due_rub=Decimal("900.00"),
        subsidy_cap_rub=Decimal("9.00"),
    )
    row.update(over)
    return _cand(**row)


class TriangleAmountBandTests(unittest.TestCase):
    def test_corridor_on_a_900_card(self):
        card = _triangle_card()
        short = fit_payin([card], 810)
        exact = fit_payin([card], 900)
        long = fit_payin([card], 909)
        over = fit_payin([card], 910)
        self.assertEqual(short.kind, "band")
        self.assertTrue(short.closes)
        self.assertFalse(short.offer)
        self.assertEqual(short.subsidy_rub, Decimal("0.00"))
        self.assertEqual(short.pay_rub, Decimal("810.00"))
        self.assertEqual(exact.kind, "exact")
        self.assertEqual(exact.subsidy_rub, Decimal("0.00"))
        self.assertEqual(long.kind, "band")
        self.assertEqual(long.pay_rub, Decimal("909.00"))
        self.assertEqual(long.subsidy_rub, Decimal("9.00"))
        self.assertEqual(over.kind, "none")

    def test_thinner_buy_cannot_stretch_the_frozen_cap(self):
        card = _triangle_card()
        self.assertEqual(fit_payin([card], 909, buy_profit_rub=100).kind, "none")
        fit = fit_payin([card], 905, buy_profit_rub=100)
        self.assertEqual(fit.kind, "band")
        self.assertEqual(fit.subsidy_rub, Decimal("5.00"))

    def test_triangle_card_does_not_offer_a_happy_deal(self):
        card = _triangle_card()
        fit = fit_payin([card], 891)
        self.assertEqual(fit.kind, "band")
        self.assertFalse(fit.offer)
        old = _triangle_card(client_due_rub=None, subsidy_cap_rub=None)
        self.assertEqual(fit_payin([old], 891).kind, "none")

    def test_aged_triangle_skips_a_small_check(self):
        now = datetime.now(timezone.utc)
        card = _triangle_card(
            amount_rub=Decimal("24000.00"),
            free_rub=Decimal("24000.00"),
            client_due_rub=Decimal("24000.00"),
            subsidy_cap_rub=Decimal("200.00"),
            created_at=now - timedelta(hours=2),
        )
        small = fit_payin([card], 2885, now=now)
        self.assertEqual(small.kind, "none")
        self.assertIsNone(small.candidate)
        near = fit_payin([card], 22000, now=now)
        self.assertEqual(near.kind, "band")
        self.assertEqual(near.pay_rub, Decimal("22000.00"))
        plain = _cand(
            free_rub=Decimal("24000.00"),
            amount_rub=Decimal("24000.00"),
            is_triangle=False,
            created_at=now - timedelta(hours=2),
        )
        self.assertEqual(fit_payin([plain], 2885, now=now).kind, "as_quoted")

    def test_short_close_and_balance_return_skip_unpaid_bonus(self):
        from payin_requisite_rail import (
            band_short_closes,
            frozen_subsidy_cap_rub,
            triangle_balance_return,
            triangle_band_notice,
            triangle_subsidy_amount,
        )

        withdraw = {
            "paid_rub": Decimal("810.00"),
            "amount_rub": Decimal("900.00"),
            "client_due_rub": Decimal("900.00"),
            "subsidy_cap_rub": Decimal("9.00"),
            "source_withdrawal_id": 4,
        }
        self.assertEqual(triangle_balance_return(withdraw), Decimal("90.00"))
        self.assertEqual(triangle_subsidy_amount(withdraw), Decimal("0.00"))
        self.assertTrue(band_short_closes(withdraw, 81000, 1))
        self.assertFalse(band_short_closes(withdraw, 81000, 2))
        self.assertFalse(band_short_closes({**withdraw, "client_due_rub": None}, 81000, 1))
        sell = {
            "paid_rub": Decimal("9800.00"),
            "amount_rub": Decimal("9991.00"),
            "client_due_rub": Decimal("9700.00"),
            "subsidy_cap_rub": Decimal("9.00"),
            "source_sell_order_id": "S1",
        }
        self.assertEqual(triangle_balance_return(sell), Decimal("0.00"))
        topped = {**sell, "paid_rub": Decimal("10000.00")}
        self.assertEqual(triangle_subsidy_amount(topped), Decimal("9.00"))
        with patch("runtime_settings.buy_markup", return_value=1.25):
            self.assertEqual(frozen_subsidy_cap_rub(900), Decimal("9.00"))
        notice = triangle_band_notice(due=900, nominal=900, cap=9)
        self.assertIn("810", notice)
        self.assertIn("909", notice)


class TriangleShortfallCreditTests(unittest.IsolatedAsyncioTestCase):
    async def test_return_is_adjustment_once(self):
        from user_unified_balance import credit_triangle_shortfall

        conn = MagicMock()
        conn.fetchval = AsyncMock(side_effect=[0, 0, 0, 90, 0, 0])
        conn.execute = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx
        with patch("user_unified_balance.get_pool", new=AsyncMock(return_value=pool)):
            first = await credit_triangle_shortfall(user_id=1, requisite_id=9, amount_rub=90)
            second = await credit_triangle_shortfall(user_id=1, requisite_id=9, amount_rub=90)
        self.assertEqual(first, 90.0)
        self.assertEqual(second, 90.0)
        inserts = [call.args[0] for call in conn.execute.await_args_list if "INSERT" in call.args[0]]
        self.assertEqual(len(inserts), 1)
        self.assertIn("adjustment", inserts[0])
        self.assertNotIn("accrual", inserts[0])
        bound = [arg for call in conn.execute.await_args_list for arg in call.args]
        self.assertIn("Возврат треугольника #9", bound)


class PayinShiftGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_shift_check_fail_closed(self):
        from payin_requisite_rail import payin_reviewer_on_shift

        with patch(
            "operator_availability.has_operator_on_shift",
            new=AsyncMock(side_effect=RuntimeError("db")),
        ):
            self.assertFalse(await payin_reviewer_on_shift())

    async def test_preview_hides_card_without_shift(self):
        from payin_requisite_rail import preview_payin_fit

        with patch(
            "payin_requisite_rail.payin_reviewer_on_shift",
            new=AsyncMock(return_value=False),
        ), patch(
            "payin_requisite_rail.collect_payin_pool",
            new=AsyncMock(),
        ) as collect, patch(
            "payin_requisite_rail.user_can_use_payin_rail",
            new=AsyncMock(return_value=True),
        ):
            fit = await preview_payin_fit(
                MagicMock(), amount_rub=2885, sub_token="SBPRUB", user_id=1
            )
        self.assertEqual(fit.kind, "none")
        collect.assert_not_called()

    async def test_create_skips_reservation_without_shift(self):
        from buy_order_web import try_create_payin_rail_buy

        with patch("runtime_settings.triangle_enabled", return_value=True), patch(
            "payin_requisite_rail.payin_reviewer_on_shift",
            new=AsyncMock(return_value=False),
        ), patch(
            "payin_requisite_rail.reserve_payin_slot",
            new=AsyncMock(side_effect=AssertionError("reserved")),
        ), patch(
            "buy_order_web.get_pool",
            new=AsyncMock(side_effect=AssertionError("pool")),
        ):
            out = await try_create_payin_rail_buy(
                user_id=1,
                crypto_sym="btc",
                crypto_amount=0.00033,
                fiat_amount=2885,
                rate=1.0,
                requisites="bc1q",
                sub_token="SBPRUB",
                client_ip=None,
            )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()

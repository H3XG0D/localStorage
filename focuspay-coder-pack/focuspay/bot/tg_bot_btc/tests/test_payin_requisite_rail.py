"""Зеркало порога доверия и подбора пейин-реквизита."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from services.payin_requisite_rail import PayinCandidate, fit_payin, pick_payin_candidate, payin_card_fee_pct


def _cand(**over) -> PayinCandidate:
    now = datetime.now(timezone.utc)
    row = dict(
        id=1,
        operator_id=5,
        method="card",
        requisites="2202",
        bank="Сбер",
        holder_name="И",
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
    def test_prefers_tighter_fit(self):
        chosen = pick_payin_candidate(
            [_cand(id=1, free_rub=Decimal("15000")), _cand(id=2, free_rub=Decimal("5000"))],
            5000,
        )
        self.assertEqual(chosen.id, 2)

    def test_card_fee_fraction(self):
        self.assertEqual(payin_card_fee_pct(Decimal("3")), 0.03)

    def test_happy_and_ten_k_two_checks(self):
        now = datetime.now(timezone.utc)
        fresh = _cand(free_rub=Decimal("5000"), created_at=now - timedelta(minutes=8))
        happy = fit_payin([fresh], 4900, now=now)
        self.assertEqual(happy.kind, "round_up")
        self.assertEqual(happy.offer_mode, "happy")
        self.assertEqual(fit_payin([fresh], 4850, now=now).credit_rub, Decimal("150.00"))
        self.assertEqual(fit_payin([fresh], 4849, now=now).kind, "round_up")
        self.assertEqual(fit_payin([fresh], 3300, now=now).kind, "none")
        close = _cand(id=4, free_rub=Decimal("2500"), created_at=now - timedelta(minutes=8))
        self.assertEqual(fit_payin([close], 2444, now=now).kind, "round_up")
        self.assertEqual(fit_payin([close], 2444, now=now).credit_rub, Decimal("56.00"))
        aged = _cand(id=2, free_rub=Decimal("5000"), created_at=now - timedelta(minutes=61))
        self.assertEqual(fit_payin([aged], 3300, now=now).kind, "as_quoted")
        exact = _cand(id=3, free_rub=Decimal("5000"), created_at=now)
        self.assertEqual(fit_payin([exact], 5000, now=now).kind, "exact")
        self.assertFalse(fit_payin([exact], 5000, now=now).offer)

        aged_10k = _cand(
            id=10,
            free_rub=Decimal("10000"),
            max_checks=2,
            created_at=now - timedelta(minutes=61),
        )
        self.assertEqual(fit_payin([aged_10k], 4800, now=now).kind, "as_quoted")
        silent_card = _cand(
            id=11,
            free_rub=Decimal("9600"),
            max_checks=2,
            created_at=now - timedelta(minutes=8),
        )
        silent = fit_payin([silent_card], 4700, now=now)
        self.assertEqual(silent.offer_mode, "silent")
        self.assertEqual(silent.pay_rub, Decimal("4800.00"))
        self.assertEqual(pick_payin_candidate([silent_card], 4700, now=now).id, silent_card.id)
        rem = _cand(id=12, free_rub=Decimal("5200"), max_checks=1, created_at=now)
        self.assertEqual(fit_payin([rem], 5100, now=now).offer_mode, "happy")
        fresh_10k = _cand(
            id=13,
            free_rub=Decimal("10000"),
            max_checks=2,
            created_at=now - timedelta(minutes=8),
        )
        self.assertEqual(fit_payin([fresh_10k], 4000, now=now).kind, "none")

    def test_fat_first_and_hunt_on_26000(self):
        now = datetime.now(timezone.utc)
        fresh = _cand(free_rub=Decimal("26000"), created_at=now - timedelta(minutes=8))
        self.assertEqual(fit_payin([fresh], 15000, now=now).kind, "as_quoted")
        self.assertEqual(fit_payin([fresh], 18415, now=now).kind, "as_quoted")
        self.assertEqual(fit_payin([fresh], 3300, now=now).kind, "none")
        hunting = _cand(
            free_rub=Decimal("11000"),
            used_checks=1,
            created_at=now - timedelta(minutes=20),
            first_paid_at=now - timedelta(minutes=10),
        )
        self.assertEqual(fit_payin([hunting], 6000, now=now).kind, "none")
        self.assertEqual(fit_payin([hunting], 11000, now=now).kind, "exact")
        after = _cand(
            id=2,
            free_rub=Decimal("11000"),
            used_checks=1,
            created_at=now - timedelta(minutes=50),
            first_paid_at=now - timedelta(minutes=46),
        )
        self.assertEqual(fit_payin([after], 6000, now=now).kind, "as_quoted")

    def test_hunt_takes_3300_when_leftover_fits_doliv(self):
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


def _triangle_card(**over) -> PayinCandidate:
    row = dict(
        amount_rub=Decimal("900.00"),
        free_rub=Decimal("900.00"),
        max_checks=1,
        cost_pct=Decimal("0"),
        is_triangle=True,
        client_due_rub=Decimal("900.00"),
        subsidy_cap_rub=Decimal("9.00"),
    )
    row.update(over)
    return _cand(**row)


class TriangleAmountBandTests(unittest.TestCase):
    def test_corridor_on_a_900_card(self):
        card = _triangle_card()
        self.assertEqual(fit_payin([card], 810).kind, "band")
        self.assertEqual(fit_payin([card], 810).subsidy_rub, Decimal("0.00"))
        self.assertEqual(fit_payin([card], 900).kind, "exact")
        long = fit_payin([card], 909)
        self.assertEqual(long.kind, "band")
        self.assertEqual(long.subsidy_rub, Decimal("9.00"))
        self.assertEqual(fit_payin([card], 910).kind, "none")
        self.assertEqual(fit_payin([card], 909, buy_profit_rub=100).kind, "none")
        self.assertFalse(fit_payin([card], 891).offer)

    def test_aged_triangle_skips_a_small_check(self):
        now = datetime.now(timezone.utc)
        card = _triangle_card(
            amount_rub=Decimal("24000.00"),
            free_rub=Decimal("24000.00"),
            client_due_rub=Decimal("24000.00"),
            subsidy_cap_rub=Decimal("200.00"),
            created_at=now - timedelta(hours=2),
        )
        self.assertEqual(fit_payin([card], 2885, now=now).kind, "none")
        self.assertEqual(fit_payin([card], 22000, now=now).kind, "band")
        plain = _cand(
            free_rub=Decimal("24000.00"),
            amount_rub=Decimal("24000.00"),
            is_triangle=False,
            created_at=now - timedelta(hours=2),
        )
        self.assertEqual(fit_payin([plain], 2885, now=now).kind, "as_quoted")


class PayinShiftGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_shift_check_fail_closed(self):
        from services.payin_requisite_rail import payin_reviewer_on_shift

        with patch(
            "services.operator_availability.has_operator_on_shift",
            new=AsyncMock(side_effect=RuntimeError("db")),
        ):
            self.assertFalse(await payin_reviewer_on_shift())

    async def test_preview_hides_card_without_shift(self):
        from services.payin_requisite_rail import preview_payin_fit

        with patch(
            "services.payin_requisite_rail.payin_reviewer_on_shift",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.payin_requisite_rail.collect_payin_pool",
            new=AsyncMock(),
        ) as collect, patch(
            "services.payin_requisite_rail.user_can_use_payin_rail",
            new=AsyncMock(return_value=True),
        ):
            fit = await preview_payin_fit(
                MagicMock(), amount_rub=2885, sub_token="SBPRUB", user_id=1
            )
        self.assertEqual(fit.kind, "none")
        collect.assert_not_called()

    async def test_create_skips_reservation_without_shift(self):
        from services.buy_order_service import create_payin_rail_buy_order

        def _id():
            raise AssertionError("order id")

        with patch(
            "services.runtime_settings.triangle_enabled", return_value=True
        ), patch(
            "services.payin_requisite_rail.payin_reviewer_on_shift",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.buy_order_service.get_pool",
            new=AsyncMock(side_effect=AssertionError("pool")),
        ):
            out = await create_payin_rail_buy_order(
                generate_order_id_fn=_id,
                user_id=1,
                crypto="btc",
                crypto_amount=0.00033,
                fiat_amount=2885,
                rate=1.0,
                wallet="bc1q",
                sub_token="SBPRUB",
            )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()

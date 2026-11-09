"""Unit tests for owner analytics and formatting."""
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from services.owner_analytics import (
    MoneyPeriod,
    OwnerSnapshot,
    money_period_with_review_bonus,
)
from services.owner_dashboard import (
    _format_missed_requisites_block,
    _format_problems_block,
    _money_line,
    build_help_text,
    format_autopilot_savings_block,
    format_hot_wallet_block,
)


class ProblemsBlockTests(unittest.TestCase):
    def test_ok_when_no_issues(self):
        snap = OwnerSnapshot(fetched_at=datetime.now())
        text = "\n".join(_format_problems_block(snap))
        self.assertIn("OK", text)

    def test_lists_stale_when_present(self):
        snap = OwnerSnapshot(
            fetched_at=datetime.now(),
            stale_completed=[
                {"order_id": "X1", "fiat_amount": 1000, "age_minutes": 20},
            ],
            old_pending_count=2,
        )
        text = "\n".join(_format_problems_block(snap, detailed=False))
        self.assertNotIn("OK", text)
        self.assertIn("X1", text)
        self.assertIn("PENDING", text)


class HelpTextTests(unittest.TestCase):
    def test_help_lists_commands(self):
        t = build_help_text()
        self.assertIn("/pulse", t)
        self.assertIn("/users", t)
        self.assertIn("/dash", t)
        self.assertIn("/misses", t)


class ReviewBonusMarginTests(unittest.TestCase):
    def test_net_profit_subtracts_review_bonus(self):
        m = money_period_with_review_bonus(3, 50000.0, 1200.0, 150.0)
        self.assertEqual(m.review_bonus_rub, 150.0)
        self.assertEqual(m.net_profit_rub, 1050.0)
        self.assertEqual(m.profit_rub, 1200.0)

    def test_money_line_shows_review_deduction(self):
        m = MoneyPeriod(
            deals=2,
            turnover_rub=10000.0,
            profit_rub=500.0,
            review_bonus_rub=50.0,
            net_profit_rub=450.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("450", line)
        self.assertIn("отзывы", line)
        self.assertIn("50", line)
        self.assertIn("ваша прибыль", line)

    def test_money_line_shows_accrual_deductions(self):
        m = MoneyPeriod(
            deals=2,
            turnover_rub=10000.0,
            profit_rub=1000.0,
            cashback_accrual_rub=40.0,
            referral_accrual_rub=30.0,
            partner_accrual_rub=80.0,
            net_profit_rub=850.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("850", line)
        self.assertIn("кешбэк", line)
        self.assertIn("рефералка", line)
        self.assertIn("партнёрка", line)

    def test_money_line_pnl_shows_residual(self):
        m = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=-500.0,
            from_pnl=True,
            operators_payroll_rub=3000.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("финальный остаток", line)
        self.assertIn("до начисл.", line)
        self.assertIn("ЗП оп.", line)
        self.assertIn("сделок", line)


    def test_money_line_pnl_shows_casino(self):
        m = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=200.0,
            from_pnl=True,
            casino_profit_rub=80.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("казино", line)
        self.assertIn("80", line)

    def test_money_line_pnl_shows_vpn_even_at_zero(self):
        m = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=200.0,
            from_pnl=True,
            vpn_profit_rub=743.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("впн", line)
        self.assertIn("743", line)
        zero = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=200.0,
            from_pnl=True,
            vpn_profit_rub=0.0,
        )
        self.assertIn("впн", _money_line("Сегодня", zero))

    def test_money_line_pnl_shows_casino_zero(self):
        m = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=200.0,
            from_pnl=True,
            casino_profit_rub=0.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("казино", line)

    def test_money_line_pnl_shows_focus_lucky(self):
        m = MoneyPeriod(
            deals=5,
            turnover_rub=100000.0,
            profit_rub=12000.0,
            net_profit_rub=200.0,
            from_pnl=True,
            focus_lucky_rub=14500.0,
        )
        line = _money_line("Сегодня", m)
        self.assertIn("FocusLucky", line)
        self.assertIn("14 500", line)


class MoneyFromPnlTests(unittest.TestCase):
    def test_maps_owner_residual(self):
        from services.owner_analytics import money_from_pnl

        m = money_from_pnl(
            {
                "total": {
                    "fiat_volume": 1000.0,
                    "net_profit": 200.0,
                    "profit_after_costs": 150.0,
                },
                "costs": {
                    "cashback": 20.0,
                    "referral": 10.0,
                    "partner": 5.0,
                    "review_bonus": 5.0,
                    "wallet_payout": 10.0,
                    "focus_lucky": 80.0,
                    "swap_commission": 0.0,
                    "usdt_issued_rub": 30.0,
                },
                "payroll": {
                    "operators_total": 40.0,
                    "admin_salary": 20.0,
                    "owner_residual": -15.0,
                },
                "manual_expenses": {"total": 25.0},
                "external": {"house_profit_rub": 50.0},
                "casino": {"owner_profit_rub": 40.0},
                "vpn": {"owner_profit_rub": 742.5, "revenue_rub": 990.0},
                "by_type": [
                    {"type": "auto_buy", "orders": 3},
                    {"type": "external", "orders": 2},
                    {"type": "casino", "orders": 9},
                    {"type": "vpn", "orders": 4},
                ],
            }
        )
        self.assertTrue(m.from_pnl)
        self.assertEqual(m.deals, 3)
        self.assertEqual(m.turnover_rub, 1000.0)
        self.assertEqual(m.profit_rub, 200.0)
        self.assertEqual(m.net_profit_rub, -15.0)
        self.assertEqual(m.external_profit_rub, 50.0)
        self.assertEqual(m.casino_profit_rub, 40.0)
        self.assertEqual(m.vpn_profit_rub, 742.5)
        self.assertEqual(m.focus_lucky_rub, 80.0)
        self.assertEqual(m.manual_expenses_rub, 25.0)


class BotUsersQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_count_bot_new_users_sql(self):
        from services import db
        from unittest.mock import patch

        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=5)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = ctx

        async def _pool():
            return mock_pool

        with patch.object(db, "get_pool", side_effect=_pool):
            n = await db.count_bot_new_users(1)

        self.assertEqual(n, 5)
        sql = mock_conn.fetchval.await_args[0][0]
        self.assertIn("bot_users", sql)
        self.assertIn("first_seen_at", sql)


class MissesBlockTests(unittest.TestCase):
    def test_empty(self):
        text = "\n".join(_format_missed_requisites_block(0, []))
        self.assertIn("нет", text)

    def test_unique_users_and_first_attempt_sum(self):
        rows = [
            {"user_id": 1, "fiat_amount": 960},
            {"user_id": 1, "fiat_amount": 500},
            {"user_id": 2, "fiat_amount": 100},
        ]
        text = "\n".join(_format_missed_requisites_block(3, rows))
        self.assertIn("Пропуски", text)
        self.assertIn("2", text)
        self.assertIn("1 060", text)


class AutopilotSavingsBlockTests(unittest.TestCase):
    def test_missing_payload_does_not_invent_a_plus(self):
        text = "\n".join(format_autopilot_savings_block(None))
        self.assertIn("нет данных", text)
        self.assertNotIn("80 000", text)

    def test_prints_backend_line_and_cashback(self):
        text = "\n".join(
            format_autopilot_savings_block(
                {
                    "net_rub": 80000,
                    "line": "Плюс за 7 дней: 80 000 ₽ · операторы −рефералы до 20% · кешбэк не поднимаем",
                }
            )
        )
        self.assertIn("80 000", text)
        self.assertIn("Кешбэк не поднимаем", text)


class HotWalletBlockTests(unittest.TestCase):
    def test_missing_payload_does_not_invent_a_balance(self):
        text = "\n".join(format_hot_wallet_block(None))
        self.assertIn("нет данных", text)
        self.assertNotIn("BTC", text)

    def test_prints_backend_line(self):
        text = "\n".join(
            format_hot_wallet_block(
                {
                    "available": True,
                    "coins": [
                        {"line": "BTC 0.00014 · ≈ 10 000 ₽ · хватит ≈ 3 дн"},
                    ],
                    "floor_phrase": "ниже порога 50 000 ₽ — новые авто-заявки не стартуют",
                }
            )
        )
        self.assertIn("BTC 0.00014", text)
        self.assertIn("хватит ≈ 3 дн", text)
        self.assertIn("ниже порога", text)


if __name__ == "__main__":
    unittest.main()

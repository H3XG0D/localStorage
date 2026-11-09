"""Контракты бизнес-дайджеста: реальные поля P&L и SLA."""
import asyncio
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from business_digest import business_delivery_date, build_business_digest, send_business_digest


class BusinessDigestTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_uses_nested_pnl_and_sla_contract(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"total_orders": 20, "completed_orders": 15, "avg_check_rub": 12000}
        )
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        pnl = {
            "costs": {"total": 1_234.0},
            "total": {
                "spread_revenue": 9_876.0,
                "net_profit": 7_654.0,
                "profit_after_costs": 4_321.0,
                "owner_margin_pct": 8.5,
            },
            "payroll": {"owner_residual": 3_210.0},
        }
        sla = [
            {
                "username": "best",
                "display_name": "Лучший",
                "total_orders": 10,
                "orders_with_complete_time": 8,
                "time_to_complete": {"avg_minutes": 42.75},
                "sla_breaches": {"claim": 1, "complete": 0, "total": 1},
            },
            {
                "username": "slow",
                "display_name": "Медленный",
                "total_orders": 4,
                "orders_with_complete_time": 2,
                "time_to_complete": {"avg_minutes": 70.25},
                "sla_breaches": {"claim": 2, "complete": 2, "total": 4},
            },
        ]

        with patch("business_digest.compute_pnl", new=AsyncMock(return_value=pnl)), patch(
            "business_digest.compute_all_operators_sla", new=AsyncMock(return_value=sla)
        ), patch("business_digest.get_pool", new=AsyncMock(return_value=pool)):
            text = await build_business_digest(date(2026, 8, 20))

        self.assertIn("Выручка: <b>9,876 ₽</b>", text)
        self.assertIn("Расходы: 1,234 ₽", text)
        self.assertIn("Чистая прибыль: <b>3,210 ₽</b> (8.5%)", text)
        self.assertIn("Казино: <b>0 ₽</b>", text)
        self.assertIn("Обработано: 14 заявок", text)
        self.assertIn("Средний SLA завершения: 48.25 мин", text)
        self.assertIn("Top: Лучший (10 заявок, breach 10.0%)", text)

    async def test_build_includes_casino_line(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={"total_orders": 20, "completed_orders": 15, "avg_check_rub": 12000}
        )
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool = MagicMock()
        pool.acquire.return_value = ctx

        pnl = {
            "costs": {"total": 1_234.0},
            "total": {
                "spread_revenue": 9_876.0,
                "net_profit": 8_154.0,
                "profit_after_costs": 4_821.0,
                "owner_margin_pct": 8.5,
            },
            "payroll": {"owner_residual": 3_710.0},
            "casino": {"owner_profit_rub": 500.0},
        }
        sla = [
            {
                "username": "best",
                "display_name": "Лучший",
                "total_orders": 10,
                "orders_with_complete_time": 8,
                "time_to_complete": {"avg_minutes": 42.75},
                "sla_breaches": {"claim": 1, "complete": 0, "total": 1},
            },
        ]

        with patch("business_digest.compute_pnl", new=AsyncMock(return_value=pnl)), patch(
            "business_digest.compute_all_operators_sla", new=AsyncMock(return_value=sla)
        ), patch("business_digest.get_pool", new=AsyncMock(return_value=pool)):
            text = await build_business_digest(date(2026, 8, 20))

        self.assertIn("Казино: <b>500 ₽</b>", text)
        self.assertIn("Чистая прибыль: <b>3,710 ₽</b> (8.5%)", text)

    def test_delivery_stays_due_after_narrow_0900_window(self):
        self.assertIsNone(business_delivery_date(datetime.fromisoformat("2026-08-21T08:59:59+03:00")))
        self.assertEqual(
            business_delivery_date(datetime.fromisoformat("2026-08-21T09:17:00+03:00")),
            date(2026, 8, 20),
        )
        self.assertEqual(
            business_delivery_date(datetime.fromisoformat("2026-08-21T23:59:00+03:00")),
            date(2026, 8, 20),
        )

    async def test_send_uses_configured_reports_group(self):
        sender = AsyncMock(return_value=123)
        claim = AsyncMock(return_value="claim")
        complete = AsyncMock(return_value=True)
        with patch("business_digest.build_business_digest", new=AsyncMock(return_value="digest")), patch(
            "config.settings.telegram_reports_group_id", -100500
        ), patch("telegram_notify.send_admin_message", new=sender), patch(
            "digest_delivery.claim_digest_delivery", new=claim
        ), patch("digest_delivery.complete_digest_delivery", new=complete):
            ok = await send_business_digest(date(2026, 8, 20))

        self.assertTrue(ok)
        sender.assert_awaited_once_with("digest", chat_id=-100500)
        complete.assert_awaited_once_with("claim")

    async def test_concurrent_workers_only_claimed_sender_sends(self):
        sender = AsyncMock(return_value=123)
        claim = AsyncMock(side_effect=["winner", None])
        with patch("business_digest.build_business_digest", new=AsyncMock(return_value="digest")), patch(
            "config.settings.telegram_reports_group_id", -100500
        ), patch("telegram_notify.send_admin_message", new=sender), patch(
            "digest_delivery.claim_digest_delivery", new=claim
        ), patch("digest_delivery.complete_digest_delivery", new=AsyncMock(return_value=True)):
            results = await asyncio.gather(
                send_business_digest(date(2026, 8, 20)),
                send_business_digest(date(2026, 8, 20)),
            )

        self.assertEqual(results, [True, False])
        sender.assert_awaited_once_with("digest", chat_id=-100500)

    async def test_none_from_telegram_releases_claim_without_delivery(self):
        release = AsyncMock()
        complete = AsyncMock(return_value=True)
        with patch("business_digest.build_business_digest", new=AsyncMock(return_value="digest")), patch(
            "config.settings.telegram_reports_group_id", -100500
        ), patch("telegram_notify.send_admin_message", new=AsyncMock(return_value=None)), patch(
            "digest_delivery.claim_digest_delivery", new=AsyncMock(return_value="claim")
        ), patch("digest_delivery.complete_digest_delivery", new=complete), patch(
            "digest_delivery.release_digest_delivery", new=release
        ):
            ok = await send_business_digest(date(2026, 8, 20))

        self.assertFalse(ok)
        complete.assert_not_awaited()
        release.assert_awaited_once_with("claim")


if __name__ == "__main__":
    unittest.main()

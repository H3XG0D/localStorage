"""Кулдаун после неоплаты должен судить одинаково в боте и на вебе.

Гейт бота два месяца был мёртвым: он требовал `requisites_revealed_at`, а это
поле пишет только WebApp-страница реквизитов и с 2026-09-08 оно не
проставляется (0 из 1630 отменённых BUY за 90 дней на проде). Клиент отменял
заявку и тут же брал реквизиты заново. Эти тесты не дают разойтись второй раз.
"""
import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

from services.buyer_access_guards import (  # noqa: E402
    UNPAID_COOLDOWN_MINUTES,
    cancel_cooldown_remaining_sec,
)

BOT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BOT_ROOT.parents[1]
WEB_ORDER_SERVICE = REPO_ROOT / "site" / "exchange-backend" / "order_service.py"
BOT_DB = BOT_ROOT / "services" / "db.py"


def _bot_gate_body() -> str:
    """Тело функции без докстроки — чтобы не ловить слова из комментариев."""
    src = BOT_DB.read_text()
    start = src.index("async def get_last_payfast_unpaid_at")
    end = src.index("async def get_last_payfast_cancel_at")
    body = src[start:end]
    doc = re.search(r'""".*?"""', body, re.S)
    return body.replace(doc.group(0), "") if doc else body


def _bot_gate_sql() -> str:
    body = _bot_gate_body()
    return re.search(r'query = """(.*?)"""', body, re.S).group(1)


class ConstantParityTests(unittest.TestCase):
    def test_bot_and_web_agree_on_the_window(self):
        web = WEB_ORDER_SERVICE.read_text()
        match = re.search(r"^UNPAID_COOLDOWN_MINUTES\s*=\s*(\d+)", web, re.M)
        self.assertIsNotNone(match, "в order_service.py пропал UNPAID_COOLDOWN_MINUTES")
        self.assertEqual(
            int(match.group(1)),
            UNPAID_COOLDOWN_MINUTES,
            "окно кулдауна в боте и на вебе разошлось — клиент будет блокирован "
            "в одном месте и свободен в другом",
        )


class BotGatePredicateTests(unittest.TestCase):
    def test_gate_keys_off_the_bill_not_a_dead_field(self):
        self.assertIn("payment_snapshot ? 'bill'", _bot_gate_sql())
        self.assertIn("_bill_has_reciver", _bot_gate_body())
        self.assertNotIn(
            "requisites_revealed_at",
            _bot_gate_sql(),
            "это поле не пишется с 2026-09-08 — гейт снова станет мёртвым",
        )

    def test_gate_does_not_require_merchant_order_id(self):
        self.assertNotIn(
            "merchant_order_id",
            _bot_gate_sql(),
            "заявки на реквизитах оператора идут без merchant_order_id "
            "и проходили бы мимо кулдауна",
        )

    def test_web_gate_keys_off_the_same_bill(self):
        web = WEB_ORDER_SERVICE.read_text()
        start = web.index("async def _unpaid_cooldown_remaining_sec")
        end = web.index("def _unpaid_cooldown_detail")
        self.assertIn("_snapshot_has_bill", web[start:end])


class WindowIsBoundedTests(unittest.TestCase):
    """Запрос бота ограничен окном кулдауна, а не сканирует всю историю."""

    def test_check_cancel_cooldown_passes_the_window_down(self):
        import services.buyer_access_guards as guards

        seen = {}

        async def fake_last(user_id, *, within_minutes=None):
            seen["user_id"] = user_id
            seen["within_minutes"] = within_minutes
            return None

        fake_db = MagicMock()
        fake_db.get_last_payfast_unpaid_at = fake_last
        sys.modules["services.db"] = fake_db
        try:
            asyncio.run(guards.check_cancel_cooldown(42))
        finally:
            sys.modules.pop("services.db", None)
        self.assertEqual(seen["user_id"], 42)
        self.assertEqual(seen["within_minutes"], UNPAID_COOLDOWN_MINUTES)


class RemainingMathTests(unittest.TestCase):
    def test_no_unpaid_order_means_no_cooldown(self):
        self.assertIsNone(cancel_cooldown_remaining_sec(None))


if __name__ == "__main__":
    unittest.main()

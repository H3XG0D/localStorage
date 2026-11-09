"""Task surface: inbox ≠ bug, Telegram bot ≠ /exchange / LIVE RATES."""
from __future__ import annotations

import unittest
import ops_ai_live_context as live
import ops_ai_rag as rag
import ops_ai_surface as surface
from ops_ai_llm import CHAT_SYSTEM, DEV_TASK_SYSTEM
from ops_ai_ui_context import ui_anchor_lines


INBOX = {"path": "/ops/dev-requests", "hint": "Inbox: форма создания задачи, не баг-экран"}
BOT_REQUEST = "Ошибка в боте телеграмм, пишет курсы недоступны"
ORDERS_UI = {"path": "/x8/orders", "hint": "Заявки"}
ORDERS_HUMAN = (
    "https://focuspay.org/x8/orders трогать только эту страничку\n"
    "трогать только эту страничку и только отоброжение\n"
    "аватарки, новый фильтр партнеры и показывало что-бы только клиентов этого партнера"
)


def _escalated(human: str, ui: dict) -> str:
    anchor = "\n".join(ui_anchor_lines(ui))
    return (
        f"{human}\n\n\nРазбор AI:\n"
        "На странице нужны аватарки клиентов и фильтр по партнёру.\n\n\n"
        f"{anchor}\n"
        "Отвечай и планируй задачу с учётом этого экрана. Не выдумывай другой экран. "
        "Если в тексте «ошибка в боте / телеграм» — цель `bot/tg_bot_btc`."
    )


class InferSurfaceTests(unittest.TestCase):
    def test_bot_from_inbox_is_telegram_not_exchange(self):
        s = surface.infer_task_surface(BOT_REQUEST, INBOX)
        self.assertEqual(s["surface"], surface.SURFACE_TELEGRAM_BOT)
        self.assertFalse(s["include_live_rates"])
        self.assertEqual(s["filing_path"], "/ops/dev-requests")
        self.assertEqual(s["ui_path"], "")
        self.assertIn("bot/tg_bot_btc/services", s["code_roots"])
        blob = surface.surface_prompt_block(s)
        self.assertIn("telegram_bot", blob)
        self.assertIn("bot/tg_bot_btc", blob)
        self.assertIn("/ops/dev-requests", blob)
        self.assertNotIn("цель: публичный", blob.lower())

    def test_rates_from_inbox_without_bot_is_not_exchange(self):
        s = surface.infer_task_surface("курсы недоступны", INBOX)
        self.assertEqual(s["surface"], surface.SURFACE_UNKNOWN)
        self.assertFalse(s["include_live_rates"])
        self.assertNotEqual(s["ui_path"], "/exchange")
        blob = surface.surface_prompt_block(s)
        self.assertIn("inbox", blob.lower())
        self.assertIn("/exchange", blob)  # negative rule

    def test_explicit_site_still_public(self):
        s = surface.infer_task_surface("на сайте /exchange не грузятся курсы", INBOX)
        self.assertEqual(s["surface"], surface.SURFACE_PUBLIC_SITE)
        self.assertTrue(s["include_live_rates"])

    def test_sticker_ai_redesign_stays_panel(self):
        s = surface.infer_task_surface(
            "редизайн этой страницы",
            {"path": "/x8/sticker-ai", "hint": "Sticker AI"},
        )
        self.assertEqual(s["surface"], surface.SURFACE_PANEL)
        self.assertEqual(s["ui_path"], "/x8/sticker-ai")
        self.assertTrue(s["include_live_rates"])

    def test_bot_from_orders_page_still_bot(self):
        s = surface.infer_task_surface(
            BOT_REQUEST, {"path": "/ops/orders", "hint": "Очередь заявок"}
        )
        self.assertEqual(s["surface"], surface.SURFACE_TELEGRAM_BOT)
        self.assertFalse(s["include_live_rates"])

    def test_escalated_orders_request_is_panel_not_bot(self):
        blob = _escalated(ORDERS_HUMAN, ORDERS_UI)
        self.assertIsNotNone(surface._BOT_RE.search(blob))
        s = surface.infer_task_surface(blob, ORDERS_UI)
        self.assertEqual(s["surface"], surface.SURFACE_PANEL)
        self.assertEqual(s["ui_path"], "/x8/orders")
        self.assertIn("focussite/frontend/src/panel/admin", s["code_roots"])
        self.assertNotIn("bot/tg_bot_btc/handlers", s["code_roots"])
        self.assertNotIn("telegram_bot", surface.surface_prompt_block(s))

    def test_ui_anchor_template_alone_does_not_become_bot(self):
        blob = "\n".join(ui_anchor_lines(ORDERS_UI))
        s = surface.infer_task_surface(blob, ORDERS_UI)
        self.assertEqual(s["surface"], surface.SURFACE_PANEL)
        self.assertEqual(s["ui_path"], "/x8/orders")

    def test_bot_request_stays_bot_after_escalation_glue(self):
        blob = _escalated(BOT_REQUEST, ORDERS_UI)
        s = surface.infer_task_surface(blob, ORDERS_UI)
        self.assertEqual(s["surface"], surface.SURFACE_TELEGRAM_BOT)
        self.assertIn("bot/tg_bot_btc/services", s["code_roots"])


class FileHintFilterTests(unittest.TestCase):
    def test_drops_inbox_and_public_exchange_for_bot(self):
        s = surface.infer_task_surface(BOT_REQUEST, INBOX)
        out = surface.filter_file_hints(
            [
                "focussite/frontend/src/panel/operator/OperatorDevRequests.tsx",
                "/exchange",
                "code/handlers/partner_bot.py",
            ],
            s,
        )
        self.assertNotIn("/exchange", out)
        self.assertFalse(any("OperatorDevRequests" in x for x in out))
        self.assertIn("bot/tg_bot_btc/handlers", out)
        self.assertIn("bot/tg_bot_btc/services", out)

    def test_escalated_orders_keeps_panel_file_hints(self):
        s = surface.infer_task_surface(_escalated(ORDERS_HUMAN, ORDERS_UI), ORDERS_UI)
        out = surface.filter_file_hints(
            [
                "focussite/frontend/src/panel/admin/AdminOrders.tsx",
                "/exchange",
            ],
            s,
        )
        self.assertIn("focussite/frontend/src/panel/admin/AdminOrders.tsx", out)
        self.assertNotIn("bot/tg_bot_btc/handlers", out)

    def test_rag_query_for_escalated_orders_does_not_force_bot_files(self):
        blob = _escalated(ORDERS_HUMAN, ORDERS_UI)
        s = surface.infer_task_surface(blob, ORDERS_UI)
        q = surface.rag_query_for_surface(blob, s)
        self.assertIn("аватарки", q)
        self.assertNotIn("ошибка в боте", q.lower())
        self.assertNotIn("rates_api", q)

    def test_rag_query_mentions_bot_rates(self):
        s = surface.infer_task_surface(BOT_REQUEST, INBOX)
        q = surface.rag_query_for_surface(BOT_REQUEST, s)
        self.assertIn("rates_api", q)
        self.assertIn("bot/tg_bot_btc", q)


class LiveRatesDisclaimerTests(unittest.TestCase):
    def test_note_says_not_a_target(self):
        note = live.live_rates_not_a_target_note()
        self.assertIn("LIVE RATES", note)
        self.assertIn("bot/tg_bot_btc", note)
        self.assertIn("/exchange", note)
        self.assertNotIn("buy_markup", note)

    def test_disclaimer_constant(self):
        self.assertIn("не цель", live.LIVE_RATES_DISCLAIMER.lower())
        self.assertIn("bot/tg_bot_btc", live.LIVE_RATES_DISCLAIMER)


class RagCitePathTests(unittest.TestCase):
    def test_local_bot_file_cited_under_bot_prefix(self):
        p = rag._repo_root() / "bot" / "tg_bot_btc" / "services" / "rates_api.py"
        if not p.is_file():
            self.skipTest("local bot/tg_bot_btc not present")
        cited = rag._cite_path(p)
        self.assertTrue(cited.startswith("bot/tg_bot_btc/"), cited)
        self.assertIn("rates_api.py", cited)
        self.assertFalse(cited.startswith("code/"))

    def test_walk_roots_include_repo_bot(self):
        roots = [str(p).replace("\\", "/") for p in rag._CODE_WALK_ROOTS]
        self.assertTrue(any(r.endswith("bot/tg_bot_btc/services") for r in roots), roots)


class PromptTemplateTests(unittest.TestCase):
    def test_systems_mention_inbox_and_bot(self):
        for blob in (CHAT_SYSTEM, DEV_TASK_SYSTEM):
            self.assertIn("/ops/dev-requests", blob)
            self.assertIn("bot/tg_bot_btc", blob)
            self.assertIn("LIVE RATES", blob)


if __name__ == "__main__":
    unittest.main()

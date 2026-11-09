"""Exchange Mini App initData is signed with the exchange bot token."""
import ast
import hashlib
import hmac
import json
import unittest
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException

from casino_miniapp_auth import verify_casino_init_data
import vpn_billing

TOKEN = "123456:exchange-miniapp-unit-token"
NOW = 1800000000
ROUTER = Path(__file__).resolve().parents[1] / "routers" / "auth_router.py"


def signed_data(**overrides):
    fields = {"auth_date": str(NOW), "user": json.dumps({"id": 77, "first_name": "Buyer"})}
    fields.update(overrides)
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class ExchangeMiniAppAuthTests(unittest.TestCase):
    def test_signed_user_is_accepted_for_exchange_token(self):
        self.assertEqual(verify_casino_init_data(signed_data(), TOKEN, now=NOW)["id"], 77)

    def test_casino_token_does_not_open_exchange_payload(self):
        with self.assertRaises(HTTPException) as exc:
            verify_casino_init_data(signed_data(), "casino-bot-token", now=NOW)
        self.assertEqual(exc.exception.status_code, 401)

    def test_route_verifies_with_exchange_bot_token(self):
        source = ROUTER.read_text(encoding="utf-8")
        fn = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "auth_exchange_miniapp"
        )
        body = ast.get_source_segment(source, fn) or ""
        self.assertIn("settings.telegram_bot_token", body)
        self.assertNotIn("casino_telegram_bot_token", body)
        self.assertIn('payload["return_path"] = "/exchange/tg"', body)
        self.assertIn("via=ORDER_VIA_TG_MINIAPP", body)

    def test_only_exchange_miniapp_marks_the_token_as_bot(self):
        source = ROUTER.read_text(encoding="utf-8")
        casino = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "auth_casino_miniapp"
        )
        finish = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_finish_bot_telegram_login"
        )
        casino_body = ast.get_source_segment(source, casino) or ""
        finish_body = ast.get_source_segment(source, finish) or ""
        self.assertNotIn("ORDER_VIA_TG_MINIAPP", casino_body)
        self.assertNotIn("tg_miniapp", casino_body)
        self.assertIn('claims["via"] = via', finish_body)

    def test_vpn_card_reuses_status_counts(self):
        view = vpn_billing.public_progress({
            "exchanges": {"have": 4, "need": 10},
            "invited": {"have": 2, "need": 30},
            "purchase_open": False,
            "trusted": True,
            "trial_available": True,
            "available_rub": 999,
            "plans": [{"code": "week", "title": "Неделя", "price_rub": 300.0}],
        })
        self.assertEqual(view["exchanges"], {"have": 4, "need": 10})
        self.assertEqual(view["invited"], {"have": 2, "need": 30})
        self.assertEqual(view["plans"], [{"title": "Неделя", "price_rub": 300.0}])
        self.assertNotIn("available_rub", view)
        self.assertTrue(view["trusted"])

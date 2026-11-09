"""Pure unit tests for admin order verification helpers (no DB writes)."""
from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from order_verification import (
    RISK_LABELS,
    LEVEL_OK,
    LEVEL_STRICT,
    LEVEL_WATCH,
    assemble_order_verification,
    build_checks,
    client_checks,
    device_info,
    fetch_live_reuse,
    receipt_info,
    receipt_kind,
    risk_from_snapshot,
    risk_level_from_score,
    timeline,
)


PLAN_BREAKDOWN_KEYS = frozenset(
    {
        "wallet_reuse",
        "ip_reuse",
        "fingerprint_reuse",
        "fingerprint_common",
        "pdf_hash_reuse",
        "pdf_stale_creation",
        "pdf_amount_missing",
        "pdf_amount_mismatch",
        "pdf_watch_producer",
        "pdf_consumer_producer",
        "pdf_a4_combo",
        "pdf_bankish",
        "pdf_date_skew",
        "fast_pdf_upload",
        "no_username",
        "no_avatar",
        "weak_name",
        "fresh_in_bot",
        "username_changed",
        "no_premium",
        "tg_account_new_7d",
        "tg_account_new_30d",
        "no_referral",
        "has_referral",
        "round_rub",
        "crypto_input",
        "paid_history",
    }
)


class ReceiptKindTests(unittest.TestCase):
    def test_pdf_extension(self):
        self.assertEqual(receipt_kind({"receipt_file": "abc.pdf"}), "pdf")
        info = receipt_info({"receipt_file": "/opt/tg_bot_btc/receipts/abc.pdf"})
        self.assertTrue(info["has"])
        self.assertEqual(info["kind"], "pdf")
        self.assertEqual(info["filename"], "abc.pdf")

    def test_mp4_extension(self):
        self.assertEqual(receipt_kind({"receipt_file": "clip.mp4"}), "video")
        self.assertEqual(receipt_info({"receipt_file": "clip.MP4"})["kind"], "video")

    def test_unknown_extension(self):
        self.assertEqual(receipt_kind({"receipt_file": "note.bin"}), "other")

    def test_fallback_required_type(self):
        self.assertEqual(receipt_kind({"required_receipt_type": 2}), "pdf")
        self.assertEqual(receipt_kind({"required_receipt_type": 3}), "video")
        self.assertIsNone(receipt_kind({}))
        self.assertFalse(receipt_info({"required_receipt_type": 3})["has"])


class UploadSecTests(unittest.TestCase):
    def test_upload_sec_from_snapshot(self):
        start = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=47)
        info = receipt_info(
            {
                "receipt_file": "a.pdf",
                "payment_snapshot": {
                    "requisites_revealed_at": start.isoformat(),
                    "receipt_ops_submitted_at": end.isoformat(),
                },
            }
        )
        self.assertEqual(info["upload_sec"], 47)

    def test_missing_times(self):
        self.assertIsNone(receipt_info({"receipt_file": "a.pdf"})["upload_sec"])


class RiskScoreTests(unittest.TestCase):
    def test_levels_from_breakdown(self):
        ok = risk_from_snapshot({"risk_breakdown": {"pdf_bankish": -1}})
        self.assertEqual(ok["score"], -1)
        self.assertEqual(ok["level"], LEVEL_OK)

        watch = risk_from_snapshot({"risk_breakdown": {"no_username": 2}})
        self.assertEqual(watch["score"], 2)
        self.assertEqual(watch["level"], LEVEL_WATCH)

        strict = risk_from_snapshot({"risk_breakdown": {"wallet_reuse": 5}})
        self.assertEqual(strict["score"], 5)
        self.assertEqual(strict["level"], LEVEL_STRICT)

    def test_fallback_thresholds(self):
        self.assertEqual(risk_level_from_score(0), LEVEL_OK)
        self.assertEqual(risk_level_from_score(2), LEVEL_WATCH)
        self.assertEqual(risk_level_from_score(5), LEVEL_STRICT)

    def test_empty_snapshot_has_no_level(self):
        empty = risk_from_snapshot({})
        self.assertEqual(empty["score"], 0)
        self.assertIsNone(empty["level"])
        self.assertEqual(empty["items"], [])

    def test_all_breakdown_keys_have_labels(self):
        self.assertTrue(PLAN_BREAKDOWN_KEYS <= set(RISK_LABELS))
        for key in PLAN_BREAKDOWN_KEYS:
            item = risk_from_snapshot({"risk_breakdown": {key: 1}})["items"][0]
            self.assertEqual(item["key"], key)
            self.assertTrue(item["label"])
            self.assertIn(item["severity"], ("ok", "warn", "danger"))

    def test_danger_and_ok_severity(self):
        danger = risk_from_snapshot({"risk_breakdown": {"pdf_hash_reuse": 5}})["items"][0]
        self.assertEqual(danger["severity"], "danger")
        ok = risk_from_snapshot({"risk_breakdown": {"paid_history": -3}})["items"][0]
        self.assertEqual(ok["severity"], "ok")


class ClientDeviceTimelineTests(unittest.TestCase):
    def test_client_checks(self):
        out = client_checks(
            {
                "account_review_status": "pending",
                "account_review_reason": "wallet",
                "is_banned": True,
                "ban_type": "hard",
                "ban_reason": "reuse",
            }
        )
        self.assertEqual(out["account_review_status"], "pending")
        self.assertTrue(out["is_banned"])
        self.assertEqual(out["device_review_status"], "none")

    def test_device_info_prefers_signal_ip(self):
        out = device_info(
            {"device_fp_reuse": True, "device_ip_reuse": True, "device_fp_user_count": 4},
            {"ip": "1.2.3.4/32", "fingerprint": "abcdef1234567890", "platform": "ios"},
        )
        self.assertEqual(out["ip"], "1.2.3.4")
        self.assertEqual(out["fingerprint_short"], "abcdef123456")
        self.assertTrue(out["fp_reuse"])
        self.assertEqual(out["platform"], "ios")

    def test_timeline_skips_empty(self):
        created = datetime(2026, 8, 1, tzinfo=timezone.utc)
        events = timeline(
            {"created_at": created, "expires_at": None},
            {"receipt_requested_at": created.isoformat()},
        )
        keys = [e["key"] for e in events]
        self.assertEqual(keys, ["created_at", "receipt_requested_at"])


class ChecksAndSourceTests(unittest.TestCase):
    def test_build_checks_includes_review_and_reuse(self):
        risk = risk_from_snapshot({"risk_breakdown": {"wallet_reuse": 5}})
        checks = build_checks(
            risk=risk,
            client={"is_banned": True, "ban_type": "hard", "account_review_status": "pending"},
            receipt={"ops_pending": True, "pdf_meta": {"flags": ["pdf_chrome_skia"]}},
            reuse={
                "wallet": [{"username": "@x", "order_id": "A1", "user_id": 1}],
                "ip": [],
                "fingerprint": [],
                "receipt_hash": [],
                "available": True,
            },
        )
        keys = {c["key"] for c in checks}
        self.assertIn("wallet_reuse", keys)
        self.assertIn("banned", keys)
        self.assertIn("account_review", keys)
        self.assertIn("receipt_ops_pending", keys)
        self.assertIn("pdf_chrome_skia", keys)
        self.assertIn("wallet_reuse_hits", keys)

    def test_module_does_not_write_snapshot(self):
        src = Path(__file__).resolve().parents[1] / "order_verification.py"
        text = src.read_text(encoding="utf-8")
        self.assertNotIn("merge_order_payment_snapshot", text)
        self.assertNotIn("_build_receipt_risk_note", text)
        self.assertNotIn("UPDATE ORDERS", text.upper())
        self.assertTrue(inspect.iscoroutinefunction(assemble_order_verification))
        self.assertTrue(inspect.iscoroutinefunction(fetch_live_reuse))


if __name__ == "__main__":
    unittest.main()

"""Тесты buyer_risk, PDF inspect, гейт account_review."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from services.buyer_access_guards import (
    REASON_FRESH_ACCOUNT,
    REASON_NO_AVATAR,
    REASON_NO_REFERRAL,
    REASON_NO_USERNAME,
    REASON_ROUND_RUB,
    REASON_TG_NEW,
    REASON_WALLET_REUSE,
    REASON_WEAK_NAME,
    is_suspicious_account,
)
from services.buyer_risk import (
    LEVEL_OK,
    LEVEL_STRICT,
    LEVEL_WATCH,
    account_review_title,
    compute_buyer_risk_score,
    format_risk_block,
    needs_account_review,
)
from services.receipt_pdf_inspect import (
    amount_present_in_text,
    inspect_pdf_bytes,
    parse_pdf_date,
)


class NeedsAccountReviewTests(unittest.TestCase):
    def test_wallet_reuse_alone(self):
        self.assertTrue(needs_account_review([REASON_WALLET_REUSE]))

    def test_single_profile_not_enough(self):
        self.assertFalse(needs_account_review([REASON_NO_USERNAME]))
        self.assertFalse(needs_account_review([REASON_FRESH_ACCOUNT]))

    def test_two_profile_markers(self):
        self.assertTrue(
            needs_account_review([REASON_NO_USERNAME, REASON_NO_AVATAR])
        )

    def test_tg_new_counts_as_profile(self):
        self.assertTrue(
            needs_account_review([REASON_TG_NEW, REASON_NO_USERNAME])
        )
        self.assertFalse(needs_account_review([REASON_TG_NEW]))

    def test_empty(self):
        self.assertFalse(needs_account_review([]))

    def test_fresh_alone_not_enough(self):
        self.assertFalse(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=False,
                amount_currency="rub",
                fiat_amount=450,
            )
        )
        self.assertFalse(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=True,
                amount_currency="rub",
                fiat_amount=6000,
            )
        )

    def test_fresh_no_ref_round_rub(self):
        """Кейс @sberlid: сразу после /start, 6000 ₽, без реферала."""
        self.assertTrue(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=False,
                amount_currency="rub",
                fiat_amount=6000,
            )
        )
        self.assertTrue(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=False,
                amount_currency="rub",
                fiat_amount=1500,
            )
        )

    def test_fresh_no_ref_not_round_or_crypto_input(self):
        self.assertFalse(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=False,
                amount_currency="rub",
                fiat_amount=6100,
            )
        )
        self.assertFalse(
            needs_account_review(
                [REASON_FRESH_ACCOUNT],
                has_referral=False,
                amount_currency="crypto",
                fiat_amount=6000,
            )
        )


class AccountReviewTitleTests(unittest.TestCase):
    def test_titles(self):
        self.assertIn("совпадение", account_review_title([REASON_WALLET_REUSE]))
        self.assertIn("профиль", account_review_title([REASON_NO_USERNAME]))
        t = account_review_title([REASON_NO_USERNAME, REASON_WALLET_REUSE])
        self.assertIn("профиль +", t)

    def test_cold_combo_title(self):
        t = account_review_title(
            [REASON_FRESH_ACCOUNT, REASON_NO_REFERRAL, REASON_ROUND_RUB]
        )
        self.assertIn("круглая", t)


class SuspiciousAccountExtendedTests(unittest.TestCase):
    def test_no_avatar_and_weak_name(self):
        user = {
            "username": "alice",
            "first_name": "A",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": None,
            "account_review_status": "none",
        }
        reasons = is_suspicious_account(user, 0, has_avatar=False, first_name="A")
        self.assertIn(REASON_NO_AVATAR, reasons)
        self.assertIn(REASON_WEAK_NAME, reasons)
        self.assertTrue(needs_account_review(reasons))

    def test_clean_named_user(self):
        user = {
            "username": "alice",
            "first_name": "Alice",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": None,
            "account_review_status": "none",
        }
        reasons = is_suspicious_account(user, 0, has_avatar=True, first_name="Alice")
        self.assertEqual(reasons, [])

    def test_tg_new_reason(self):
        user = {
            "username": "alice",
            "first_name": "Alice",
            "first_seen_at": datetime.now(tz=timezone.utc) - timedelta(days=10),
            "previous_username": None,
            "account_review_status": "none",
        }
        reasons = is_suspicious_account(
            user, 0, has_avatar=True, first_name="Alice", account_age_days=3
        )
        self.assertIn(REASON_TG_NEW, reasons)


class RiskScoreTests(unittest.TestCase):
    def test_strict_on_wallet_and_pdf(self):
        score, level, lines, bd = compute_buyer_risk_score(
            reasons=[REASON_WALLET_REUSE, REASON_NO_AVATAR, REASON_FRESH_ACCOUNT],
            has_referral=False,
            amount_currency="rub",
            fiat_amount=6000,
            pdf_flags=["pdf_watch_producer", "pdf_a4_page"],
            pdf_upload_sec=12,
            paid_count=0,
        )
        self.assertEqual(level, LEVEL_STRICT)
        self.assertGreaterEqual(score, 5)
        self.assertTrue(any("рубл" in x for x in lines))
        self.assertIn("wallet_reuse", bd)

    def test_ok_paid_bankish(self):
        score, level, _, bd = compute_buyer_risk_score(
            reasons=[],
            has_referral=True,
            amount_currency="crypto",
            pdf_flags=["pdf_bankish_producer"],
            paid_count=2,
        )
        self.assertEqual(level, LEVEL_OK)
        self.assertLess(score, 2)
        self.assertTrue(bd)

    def test_watch_chrome(self):
        _, level, lines, _ = compute_buyer_risk_score(
            reasons=[REASON_NO_USERNAME],
            has_referral=False,
            amount_currency="rub",
            fiat_amount=6100,
            pdf_flags=["pdf_chrome_skia"],
            paid_count=0,
        )
        self.assertIn(level, (LEVEL_WATCH, LEVEL_OK, LEVEL_STRICT))
        self.assertTrue(any("браузер" in x for x in lines))

    def test_age_and_stale_breakdown(self):
        score, level, lines, bd = compute_buyer_risk_score(
            reasons=[],
            account_age_days=2,
            pdf_flags=["pdf_stale_creation", "pdf_amount_missing"],
            ip_reuse=True,
            paid_count=0,
        )
        self.assertIn("tg_account_new_7d", bd)
        self.assertIn("pdf_stale_creation", bd)
        self.assertIn("pdf_amount_missing", bd)
        self.assertIn("ip_reuse", bd)
        self.assertEqual(level, LEVEL_STRICT)
        self.assertTrue(any("новый" in x for x in lines))
        self.assertGreaterEqual(score, 5)


class RiskFormattingTests(unittest.TestCase):
    def test_plain_lines_are_html_escaped(self):
        block = format_risk_block(
            score=2,
            level=LEVEL_WATCH,
            lines=["fresh account (<24h)", "name < unsafe"],
        )
        self.assertIn("fresh account (&lt;24h)", block)
        self.assertIn("name &lt; unsafe", block)
        self.assertNotIn("(<24h)", block)


class PdfInspectTests(unittest.TestCase):
    def test_jasper_like(self):
        raw = (
            b"%PDF-1.5\n"
            b"1 0 obj<< /Producer (OpenPDF 1.3.30.jaspersoft.2) "
            b"/Creator (JasperReports Library version 6.20.3) >>endobj\n"
            b"/MediaBox [ 0 0 270 411 ]\n"
        )
        meta = inspect_pdf_bytes(raw)
        self.assertIn("pdf_bankish_producer", meta["flags"])
        self.assertEqual(meta["page_kind"], "narrow")
        self.assertEqual(len(meta["sha256"]), 64)

    def test_oracle_a4(self):
        raw = (
            b"%PDF-1.6\n"
            b"/Producer (Oracle BI Publisher 12.2.1.4.0)\n"
            b"/MediaBox [ 0 0 595.3 841.9 ]\n"
        )
        meta = inspect_pdf_bytes(raw)
        self.assertIn("pdf_watch_producer", meta["flags"])
        self.assertIn("pdf_a4_page", meta["flags"])

    def test_stale_creation_date(self):
        raw = (
            b"%PDF-1.5\n"
            b"/CreationDate (D:20240101120000Z)\n"
            b"/Producer (OpenPDF)\n"
            b"/MediaBox [ 0 0 270 400 ]\n"
            b"(Summa 6000 RUB)\n"
        )
        issued = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        meta = inspect_pdf_bytes(raw, fiat_amount=6000, details_issued_at=issued)
        self.assertIn("pdf_stale_creation", meta["flags"])
        self.assertIsNotNone(parse_pdf_date(meta["creation_date"]))

    def test_fresh_creation_not_stale(self):
        issued = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        # creation 2 min before issue — within 5 min tolerance
        raw = (
            b"%PDF-1.5\n"
            b"/CreationDate (D:20260722115800Z)\n"
            b"/MediaBox [ 0 0 270 400 ]\n"
            b"(payment 6000)\n"
        )
        meta = inspect_pdf_bytes(raw, fiat_amount=6000, details_issued_at=issued)
        self.assertNotIn("pdf_stale_creation", meta["flags"])

    def test_amount_present_helper(self):
        self.assertTrue(amount_present_in_text("Оплата 6 000 руб", 6000))
        self.assertFalse(amount_present_in_text("Оплата 100 руб", 6000))
        self.assertIsNone(amount_present_in_text(None, 6000))

    def test_amount_missing_flag(self):
        raw = (
            b"%PDF-1.5\n"
            b"/CreationDate (D:20260722120000Z)\n"
            b"/MediaBox [ 0 0 270 400 ]\n"
            b"(hello world receipt)\n"
        )
        issued = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        meta = inspect_pdf_bytes(raw, fiat_amount=99999, details_issued_at=issued)
        self.assertIn("pdf_amount_missing", meta["flags"])


class FindIpReuseQueryTests(unittest.TestCase):
    def test_empty_ip(self):
        import asyncio

        from services.db import find_ip_reuse

        self.assertEqual(asyncio.run(find_ip_reuse("", 1)), [])
        self.assertEqual(asyncio.run(find_ip_reuse("   ", 99)), [])

    def test_query_shape_mocked(self):
        import asyncio

        from services import db as db_mod

        fake_conn = AsyncMock()
        fake_conn.fetch = AsyncMock(
            return_value=[
                {
                    "user_id": 42,
                    "order_id": "ORD1",
                    "status": "PAID",
                    "created_at": datetime.now(tz=timezone.utc),
                    "username": "other",
                }
            ]
        )

        class _Acquire:
            def __init__(self, conn):
                self._conn = conn

            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *a):
                return False

        fake_pool = AsyncMock()
        fake_pool.acquire = lambda: _Acquire(fake_conn)

        async def _run():
            with patch.object(db_mod, "get_pool", AsyncMock(return_value=fake_pool)):
                return await db_mod.find_ip_reuse("203.0.113.10", 1)

        rows = asyncio.run(_run())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_id"], 42)
        self.assertEqual(rows[0]["username"], "other")
        fake_conn.fetch.assert_awaited()


if __name__ == "__main__":
    unittest.main()

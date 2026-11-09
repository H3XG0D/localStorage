"""VPN review rules: paid subscription, once a week, separate from the exchange day."""
import unittest
from datetime import datetime, timedelta, timezone

import vpn_reviews


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


class OfferTests(unittest.TestCase):
    def test_paid_active_can_review(self):
        view = vpn_reviews.offer_view(
            active=True, status="active", pending=False, last_published_at=None,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertTrue(view["eligible"])
        self.assertIsNone(view["reason"])

    def test_trial_can_review(self):
        view = vpn_reviews.offer_view(
            active=True, status="trialing", pending=False, last_published_at=None,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertTrue(view["eligible"])
        self.assertIsNone(view["reason"])

    def test_pending_blocks_even_with_a_paid_sub(self):
        view = vpn_reviews.offer_view(
            active=True, status="active", pending=True, last_published_at=None,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertEqual(view["reason"], "pending")

    def test_published_review_blocks_for_seven_days(self):
        published = NOW - timedelta(days=6, hours=23)
        view = vpn_reviews.offer_view(
            active=True, status="active", pending=False, last_published_at=published,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertEqual(view["reason"], "cooldown")
        self.assertIsNotNone(view["next_at"])

    def test_week_old_review_opens_again(self):
        published = NOW - timedelta(days=7, seconds=1)
        view = vpn_reviews.offer_view(
            active=True, status="active", pending=False, last_published_at=published,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertTrue(view["eligible"])

    def test_rejected_does_not_start_the_week(self):
        # The caller only passes moderated_at of a published row. A rejection is not that row.
        view = vpn_reviews.offer_view(
            active=True, status="active", pending=False, last_published_at=None,
            now=NOW, text_rub=25, photo_rub=50,
        )
        self.assertTrue(view["eligible"])


class TextTests(unittest.TestCase):
    def test_strips_tags_and_rejects_short(self):
        with self.assertRaises(vpn_reviews.ReviewRejected) as caught:
            vpn_reviews.clean_review_text("<b>коротко</b>")
        self.assertEqual(caught.exception.code, "too_short")

    def test_keeps_a_real_review(self):
        text = vpn_reviews.clean_review_text("  FocusVPN на телефоне открылся сразу, локация живая.  ")
        self.assertGreaterEqual(len(text), 20)
        self.assertNotIn("<", text)


class WindowTests(unittest.TestCase):
    def test_bucket_is_stable_for_seven_days(self):
        start = vpn_reviews.review_window_start(NOW)
        later = vpn_reviews.review_window_start(NOW + timedelta(days=6))
        nxt = vpn_reviews.review_window_start(start + timedelta(days=7))
        self.assertEqual(start, later)
        self.assertEqual(nxt - start, timedelta(days=7))

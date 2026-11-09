"""Website review offer: text bonus, no screenshot."""
import unittest

import site_reviews_submit as reviews


class OfferTests(unittest.TestCase):
    def test_paid_buy_without_a_review_can_submit_text(self):
        view = reviews.offer_view(
            has_paid_buy=True, pending=False, order_id="FP-1", text_rub=50,
        )
        self.assertTrue(view["eligible"])
        self.assertFalse(view["needs_photo"])
        self.assertEqual(view["text_rub"], 50)
        self.assertEqual(view["order_id"], "FP-1")

    def test_pending_blocks_another_text(self):
        view = reviews.offer_view(
            has_paid_buy=True, pending=True, order_id="FP-1", text_rub=50,
        )
        self.assertEqual(view["reason"], "pending")
        self.assertFalse(view["eligible"])

    def test_no_paid_buy(self):
        view = reviews.offer_view(
            has_paid_buy=False, pending=False, order_id=None, text_rub=50,
        )
        self.assertEqual(view["reason"], "no_buy")

    def test_every_paid_buy_already_reviewed(self):
        view = reviews.offer_view(
            has_paid_buy=True, pending=False, order_id=None, text_rub=50,
        )
        self.assertEqual(view["reason"], "already_reviewed")


class TextTests(unittest.TestCase):
    def test_strips_tags_and_rejects_short(self):
        with self.assertRaises(reviews.ReviewRejected) as caught:
            reviews.clean_review_text("<b>коротко</b>")
        self.assertEqual(caught.exception.code, "too_short")

    def test_keeps_a_real_review(self):
        text = reviews.clean_review_text("  Обменял с сайта, деньги пришли быстро и без лишних вопросов.  ")
        self.assertNotIn("<", text)
        self.assertGreaterEqual(len(text), 20)

    def test_author_falls_back_when_the_cabinet_has_no_name(self):
        self.assertEqual(reviews.author_label({}), "Клиент")
        self.assertEqual(reviews.author_label({"display_name": "Иван"}), "Иван")

"""Купон автора: 200 ₽, 100 активаций, обмен от 3000, один код на первое видео."""
import unittest

from author_promo import (
    AUTHOR_DISCOUNT_RUB,
    AUTHOR_MAX_ACTIVATIONS,
    AUTHOR_MIN_ORDER_RUB,
    AuthorPromoError,
    author_coupon_block_reason,
    normalize_author_code,
    plan_issue,
)


class AuthorPromoPlanTests(unittest.TestCase):
    def test_create_uses_fixed_terms(self):
        plan = plan_issue("VOVA7K", 42, "first_video", None, None)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["discount_rub"], AUTHOR_DISCOUNT_RUB)
        self.assertEqual(plan["discount_rub"], 200)
        self.assertEqual(plan["max_activations"], AUTHOR_MAX_ACTIVATIONS)
        self.assertEqual(plan["max_activations"], 100)
        self.assertEqual(plan["min_order_rub"], AUTHOR_MIN_ORDER_RUB)
        self.assertEqual(plan["min_order_rub"], 3000)

    def test_same_code_is_idempotent(self):
        existing = {"code": "VOVA7K", "author_telegram_id": 42}
        plan = plan_issue("VOVA7K", 42, "first_video", existing, existing)
        self.assertEqual(plan["action"], "return")
        self.assertEqual(plan["row"]["code"], "VOVA7K")

    def test_foreign_code_is_rejected(self):
        existing = {"code": "VOVA7K", "author_telegram_id": 7}
        plan = plan_issue("VOVA7K", 42, "first_video", existing, None)
        self.assertEqual(plan["action"], "error")

    def test_code_without_author_is_rejected(self):
        existing = {"code": "SALE200", "author_telegram_id": None}
        plan = plan_issue("SALE200", 42, "extra", existing, None)
        self.assertEqual(plan["action"], "error")

    def test_second_first_video_returns_the_original(self):
        first = {"code": "VOVA7K", "author_telegram_id": 42}
        plan = plan_issue("NEW999", 42, "first_video", None, first)
        self.assertEqual(plan["action"], "return")
        self.assertEqual(plan["row"]["code"], "VOVA7K")

    def test_extra_code_is_a_new_row(self):
        first = {"code": "VOVA7K", "author_telegram_id": 42}
        plan = plan_issue("NEW999", 42, "extra", None, first)
        self.assertEqual(plan["action"], "create")
        self.assertEqual(plan["code"], "NEW999")

    def test_normalize_strips_noise(self):
        self.assertEqual(normalize_author_code(" vova-7k "), "VOVA7K")

    def test_normalize_rejects_short(self):
        with self.assertRaises(AuthorPromoError):
            normalize_author_code("AB")


class AuthorCouponBlockTests(unittest.TestCase):
    def test_ordinary_discount_is_not_blocked(self):
        self.assertIsNone(author_coupon_block_reason(None, 5, has_completed_order=True))

    def test_author_cannot_use_own_code(self):
        self.assertEqual(
            author_coupon_block_reason(5, 5, has_completed_order=False),
            "Нельзя использовать свой промокод",
        )

    def test_only_first_exchange(self):
        self.assertEqual(
            author_coupon_block_reason(9, 5, has_completed_order=True),
            "Промокод только для первого обмена",
        )

    def test_new_buyer_can_redeem(self):
        self.assertIsNone(author_coupon_block_reason(9, 5, has_completed_order=False))

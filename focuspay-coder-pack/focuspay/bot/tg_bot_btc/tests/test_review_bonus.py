"""Тесты отзыва за бонус (без Telegram API)."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.callback_signatures import sign_review_submission, verify_review_submission_signature
from services.review_bonus import (
    ReviewBonusError,
    author_display_name,
    exchange_review_has_telegram_source,
    publish_bonus_rub,
    publish_exchange_to_channel,
    review_bonus_blocked,
    review_invite_keyboard,
    submission_tier,
    validate_review_text,
)
from services.review_invite_content import (
    review_invite_reply_markup_dict,
    review_invite_text,
    review_start_prompt,
)
from services.review_moderation import format_moderation_message, moderation_keyboard


class ReviewInviteKeyboardTests(unittest.TestCase):
    def test_markup_without_start_when_not_eligible(self):
        d = review_invite_reply_markup_dict(include_start=False)
        callbacks = [
            b.get("callback_data")
            for row in d["inline_keyboard"]
            for b in row
            if b.get("callback_data")
        ]
        self.assertEqual(callbacks, [])
        self.assertTrue(any(b.get("url") for row in d["inline_keyboard"] for b in row))

    def test_markup_with_start_by_default(self):
        d = review_invite_reply_markup_dict()
        callbacks = [
            b.get("callback_data")
            for row in d["inline_keyboard"]
            for b in row
            if b.get("callback_data")
        ]
        self.assertIn("review:start", callbacks)

    def test_keyboard_builder_respects_include_start(self):
        kb = review_invite_keyboard(include_start=False)
        callbacks = [
            b.callback_data
            for row in kb.inline_keyboard
            for b in row
            if b.callback_data
        ]
        self.assertEqual(callbacks, [])


class ReviewTextTests(unittest.TestCase):
    def test_validate_too_short(self):
        with self.assertRaises(ReviewBonusError):
            validate_review_text("короткий")

    def test_validate_ok(self):
        t = validate_review_text("Отличный сервис, всё быстро и понятно!")
        self.assertGreaterEqual(len(t), 20)


class ReviewCopyTests(unittest.TestCase):
    def test_invite_mentions_both_bonuses_and_screenshot(self):
        text = review_invite_text()
        self.assertIn("50", text)
        self.assertIn("100", text)
        self.assertIn("скрин", text.lower())

    def test_text_accepted_prompt_uses_minutes(self):
        from services.review_invite_content import (
            REVIEW_PHOTO_WINDOW_SECONDS,
            review_text_accepted_prompt,
        )

        text = review_text_accepted_prompt()
        self.assertIn("10 минут", text)
        self.assertIn("Отправить без фото", text)
        self.assertEqual(REVIEW_PHOTO_WINDOW_SECONDS, 600)

    def test_start_prompt_mentions_bonuses(self):
        text = review_start_prompt()
        self.assertIn("50", text)
        self.assertIn("100", text)


class ReviewStartReentryTests(unittest.TestCase):
    """Повторный review:start не должен сбрасывать черновик/таймер."""

    def test_awaiting_photo_keyboard_has_skip(self):
        from handlers.review_bonus import _review_awaiting_photo_keyboard

        kb = _review_awaiting_photo_keyboard()
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("review:skip_photo", callbacks)
        self.assertIn("review:cancel", callbacks)


class SiteReviewPublishTests(unittest.IsolatedAsyncioTestCase):
    def test_site_submission_has_no_telegram_source(self):
        self.assertFalse(
            exchange_review_has_telegram_source(
                {"source_text_chat_id": 0, "source_text_message_id": 0}
            )
        )
        self.assertTrue(
            exchange_review_has_telegram_source(
                {"source_text_chat_id": 10, "source_text_message_id": 20}
            )
        )

    async def test_site_review_is_posted_as_text(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=77))
        bot.forward_message = AsyncMock()
        sub = {
            "review_text": "Обменял с сайта, всё пришло быстро и без вопросов.",
            "source_text_chat_id": 0,
            "source_text_message_id": 0,
        }
        with patch("services.review_bonus.config_rates.REVIEWS_PUBLISH_CHAT_ID", -100):
            mid, photo = await publish_exchange_to_channel(bot, sub)
        self.assertEqual(mid, 77)
        self.assertIsNone(photo)
        bot.forward_message.assert_not_called()
        bot.send_message.assert_awaited()

    def test_moderation_card_marks_site_source(self):
        text = format_moderation_message(
            {
                "id": 4,
                "user_id": -15,
                "author_display": "Иван",
                "review_text": "Обменял с сайта, всё пришло быстро и без вопросов.",
                "tier": "text",
                "product": "exchange",
                "source_text_chat_id": 0,
                "source_text_message_id": 0,
                "order_id": "FP-9",
            }
        )
        self.assertIn("сайт", text.lower())
        self.assertIn("скрин не прикладывался", text)


class AuthorDisplayTests(unittest.TestCase):
    def test_username(self):
        u = MagicMock(username="testuser", first_name="Test")
        self.assertEqual(author_display_name(u, 1), "@testuser")

    def test_no_username(self):
        u = MagicMock(username=None, first_name="Ivan")
        self.assertIn("Ivan", author_display_name(u, 99))


class ReviewSignatureTests(unittest.TestCase):
    def test_sign_verify(self):
        sig = sign_review_submission(7)
        self.assertTrue(verify_review_submission_signature(7, sig))
        self.assertFalse(verify_review_submission_signature(8, sig))


class StoredPhotoRefTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalize_accepts_photo_ref_without_photo_attr(self):
        from handlers.review_bonus import _finalize_submission, _stored_photo_message

        ud = {
            "review_draft_text": "Отличный сервис, всё быстро и понятно!",
            "review_text_chat_id": 1,
            "review_text_message_id": 2,
            "review_photo_chat_id": 1,
            "review_photo_message_id": 9,
            "review_photo_file_id": "AgFILE",
        }
        ref = _stored_photo_message(SimpleNamespace(user_data=ud))
        self.assertFalse(hasattr(ref, "photo"))
        bot = SimpleNamespace(send_message=AsyncMock())
        with (
            patch(
                "handlers.review_bonus.resolve_review_order_id",
                new=AsyncMock(return_value="ORD1"),
            ),
            patch(
                "handlers.review_bonus.create_pending_submission",
                new=AsyncMock(return_value=7),
            ) as create,
            patch(
                "handlers.review_bonus.send_moderation_request",
                new=AsyncMock(),
            ),
            patch("handlers.review_bonus.clear_review_session"),
        ):
            await _finalize_submission(
                bot,
                context_user_data=ud,
                user=SimpleNamespace(id=42),
                reply_chat_id=1,
                photo_message=ref,
            )
        create.assert_awaited()
        self.assertEqual(create.await_args.kwargs["source_photo_file_id"], "AgFILE")


class SubmissionTierTests(unittest.TestCase):
    def test_submission_tier(self):
        self.assertEqual(submission_tier(has_photo=False), "text")
        self.assertEqual(submission_tier(has_photo=True), "photo")


class ModerationKeyboardTests(unittest.TestCase):
    def test_moderation_keyboard_always_has_both_bonuses(self):
        for sub in (
            {"id": 1, "tier": "text", "user_id": 1, "review_text": "x" * 25},
            {
                "id": 2,
                "tier": "photo",
                "user_id": 1,
                "review_text": "x" * 25,
                "source_photo_message_id": 99,
            },
        ):
            kb = moderation_keyboard(sub)
            callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
            self.assertTrue(any("pub50" in c for c in callbacks))
            self.assertTrue(any("pub100" in c for c in callbacks))

    def test_format_message_with_photo(self):
        sub = {
            "id": 3,
            "tier": "photo",
            "user_id": 99,
            "author_display": "@u",
            "review_text": "Отличный сервис, всё быстро!",
            "source_photo_message_id": 42,
        }
        msg = format_moderation_message(sub)
        self.assertIn("скрин", msg.lower())
        self.assertIn("50", msg)
        self.assertIn("100", msg)

    def test_vpn_card_uses_vpn_amounts(self):
        sub = {
            "id": 9,
            "product": "vpn",
            "tier": "photo",
            "user_id": 5,
            "author_display": "@vpn",
            "review_text": "VPN на телефоне открылся сразу и держит связь.",
            "source_photo_path": "/var/lib/focuspay/vpn-review-photos/5-abc.jpg",
            "bonus_text_rub": 25,
            "bonus_photo_rub": 50,
        }
        msg = format_moderation_message(sub)
        self.assertIn("VPN", msg)
        self.assertIn("7 дней", msg)
        self.assertIn("25", msg)
        self.assertIn("50", msg)
        kb = moderation_keyboard(sub)
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertTrue(any("25" in label for label in labels))
        self.assertTrue(any("50" in label for label in labels))
        self.assertTrue(any("pub50" in b.callback_data for row in kb.inline_keyboard for b in row))
        self.assertTrue(any("pub100" in b.callback_data for row in kb.inline_keyboard for b in row))


class BonusLimitTests(unittest.TestCase):
    def test_vpn_week_does_not_use_the_exchange_day(self):
        self.assertFalse(review_bonus_blocked("vpn", exchange_claimed_today=True, vpn_claimed_within_week=False))
        self.assertTrue(review_bonus_blocked("vpn", exchange_claimed_today=False, vpn_claimed_within_week=True))
        self.assertFalse(review_bonus_blocked("exchange", exchange_claimed_today=False, vpn_claimed_within_week=True))
        self.assertTrue(review_bonus_blocked("exchange", exchange_claimed_today=True, vpn_claimed_within_week=False))

    def test_publish_amount_follows_product(self):
        self.assertEqual(publish_bonus_rub("vpn", "pub50", exchange_text=50, exchange_photo=100, vpn_text=25, vpn_photo=50), 25)
        self.assertEqual(publish_bonus_rub("vpn", "pub100", exchange_text=50, exchange_photo=100, vpn_text=25, vpn_photo=50), 50)
        self.assertEqual(publish_bonus_rub("exchange", "pub50", exchange_text=50, exchange_photo=100, vpn_text=25, vpn_photo=50), 50)


if __name__ == "__main__":
    unittest.main()

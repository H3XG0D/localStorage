"""Скоринг группового спама и хендлер delete+ban."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.group_antispam import group_antispam_handler, is_watched_public_chat
from antispam_main import main as antispam_main
from services.group_spam_filter import check_group_spam


SHOP_SPAM = """
🆎🆎🆎🆎🆎  🆎🆎🆎🆎🆎🆎❗️

➖➖➖➖➖➖➖

🔽🟡🟡🟡🟡🟡🟡🟡🔽

#️⃣🔠🔠🔠🔠#️⃣

*Сайт магазина KLD777 (https://clck.ru/3V8bXo)

*Боты распределители (https://clck.ru/3VW24R)

🔼🟡🟡🟡🟡🟡🟡🟡🔼

➖➖➖➖➖➖➖

🔢 Регулярное пополнение адресов в боте

🔢 Доступная оплата по карте РФ, у нас нет ТАДЖ БАНКОВ ИЛИ ЗАРУБЕЖ! И ДНЁМ И НОЧЬЮ В ДОСТУПЕ КАРТЫ РОССИИ!

🔢 Лучшие условия труда, всегда в поиске Курьеров!

🔢 Удобный и простой бот продаж

🔢 Удобный в пользовании сайт ( с ВПН )


*Мы, почти не ведем продажи через операторов! Если Вам пишут первыми, будьте уверены - это фейк!

Все наши актуальные контакты:

1. 🔥 На сайте 🔥 (https://clck.ru/3VJ4VS)

2. 🔥 (https://clck.ru/3V8db5) В боте продаж по кнопке "Контакты" (https://clck.ru/3VMXuJ) 🔥 (https://clck.ru/3V8db5)

3. 🔥 (https://clck.ru/3V8db5) В актуальных контактах - канал  (https://clck.ru/3VWkFH)🔥 (https://clck.ru/3V8db5)


🔥 (https://clck.ru/3V8db5)Жми на кнопки снизу или в описании, мы ждем тебя🔥 (https://clck.ru/3V8db5)
"""


class GroupSpamFilterTests(unittest.TestCase):
    def test_shop_ad_is_spam(self):
        verdict = check_group_spam(SHOP_SPAM)
        self.assertTrue(verdict.is_spam)
        self.assertGreaterEqual(verdict.score, 3)
        self.assertIn("phrase", verdict.reasons)
        self.assertIn("shortener", verdict.reasons)
        self.assertIn("emoji_wall", verdict.reasons)
        self.assertIn("many_links", verdict.reasons)

    def test_rate_question_is_ham(self):
        self.assertFalse(check_group_spam("какой курс usdt").is_spam)

    def test_operator_phrase_flags_message(self):
        verdict = check_group_spam("зайди в магазин kld777 сегодня", extra_phrases=["KLD777"])
        self.assertTrue(verdict.is_spam)
        self.assertIn("phrase", verdict.reasons)

    def test_rate_question_still_ham_with_unrelated_extra(self):
        verdict = check_group_spam(
            "какой курс usdt", extra_phrases=["боты распределители"]
        )
        self.assertFalse(verdict.is_spam)

    def test_card_sbp_is_ham(self):
        self.assertFalse(check_group_spam("карта сбп когда реквизиты").is_spam)

    def test_single_focuspay_link_is_ham(self):
        verdict = check_group_spam("сайт https://focuspay.org/exchange")
        self.assertFalse(verdict.is_spam)
        self.assertEqual(verdict.score, 0)

    def test_whitelisted_tme_not_counted(self):
        verdict = check_group_spam(
            "отзывы https://t.me/focuspayr и ещё https://t.me/focuspay1_bot и https://t.me/focuspayr/12"
        )
        self.assertFalse(verdict.is_spam)

    def test_homoglyph_ls_phrase(self):
        verdict = check_group_spam("пишите в лc детали")
        self.assertTrue(verdict.is_spam)
        self.assertIn("phrase", verdict.reasons)

    def test_daily_wage_dm_pitch_is_spam(self):
        verdict = check_group_spam("Дам вариант с зп 8-12к в день, пишите в личные")
        self.assertTrue(verdict.is_spam)
        self.assertIn("phrase", verdict.reasons)

    def test_dm_invite_and_daily_wage_variants(self):
        for text in (
            "пишите в личные",
            "напишите мне в личку",
            "зп 8-12к в день",
            "зарплата от 10к в день",
            "з/п 8–12 тыс в день",
            "8-12к в день",
        ):
            with self.subTest(text=text):
                self.assertTrue(check_group_spam(text).is_spam)

    def test_paycheck_mention_without_pitch_is_ham(self):
        self.assertFalse(check_group_spam("какая зп у оператора").is_spam)
        self.assertFalse(check_group_spam("мне в личку прислали чек").is_spam)

    def test_single_shortener_below_threshold(self):
        verdict = check_group_spam("смотри https://clck.ru/abc")
        self.assertFalse(verdict.is_spam)
        self.assertEqual(verdict.score, 2)
        self.assertEqual(verdict.reasons, ("shortener",))

    def test_shortener_plus_emoji_run_is_spam(self):
        verdict = check_group_spam("🟡🟡🟡🟡🟡🟡 https://bit.ly/x")
        self.assertTrue(verdict.is_spam)
        self.assertIn("shortener", verdict.reasons)
        self.assertIn("emoji_wall", verdict.reasons)

    def test_extra_entity_urls(self):
        verdict = check_group_spam(
            "жми сюда",
            extra_urls=[
                "https://clck.ru/one",
                "https://clck.ru/two",
                "https://clck.ru/three",
            ],
        )
        self.assertTrue(verdict.is_spam)
        self.assertIn("shortener", verdict.reasons)
        self.assertIn("many_links", verdict.reasons)


def _member(status: str):
    return SimpleNamespace(status=status)


def _message(
    *,
    text: str,
    chat_id: int = -1001,
    user_id: int = 555,
    is_bot: bool = False,
    username: str = "spammer",
    sender_chat=None,
    is_automatic_forward: bool = False,
    entities=None,
    caption: str | None = None,
):
    user = SimpleNamespace(id=user_id, is_bot=is_bot, username=username)
    chat = SimpleNamespace(id=chat_id, title="focus", username=None, type="supergroup")
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.entities = entities or ()
    msg.caption_entities = ()
    msg.chat = chat
    msg.message_id = 42
    msg.is_automatic_forward = is_automatic_forward
    msg.sender_chat = sender_chat
    msg.delete = AsyncMock()
    return msg, user, chat


class WatchedChatTests(unittest.TestCase):
    def test_community_watched(self):
        chat = SimpleNamespace(id=-1001, username=None)
        with (
            patch("handlers.group_antispam.is_community_chat", return_value=True),
            patch("handlers.group_antispam.is_news_chat", return_value=False),
            patch("handlers.group_antispam.is_reviews_chat", return_value=False),
        ):
            self.assertTrue(is_watched_public_chat(chat))

    def test_ops_group_not_watched(self):
        chat = SimpleNamespace(id=-9, username=None)
        with (
            patch("handlers.group_antispam.is_community_chat", return_value=False),
            patch("handlers.group_antispam.is_news_chat", return_value=False),
            patch("handlers.group_antispam.is_reviews_chat", return_value=False),
        ):
            self.assertFalse(is_watched_public_chat(chat))


class GroupAntispamHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_and_bans_spam(self):
        msg, user, chat = _message(text=SHOP_SPAM)
        update = MagicMock()
        update.effective_message = msg
        update.effective_chat = chat
        update.effective_user = user
        bot = MagicMock()
        bot.username = "focuspay_antispam_bot"
        bot.get_chat_member = AsyncMock(return_value=_member("member"))
        bot.ban_chat_member = AsyncMock()
        bot.send_message = AsyncMock()
        context = MagicMock()
        context.bot = bot

        with (
            patch("handlers.group_antispam.is_watched_public_chat", return_value=True),
            patch("handlers.group_antispam.TELEGRAM_ADMIN_IDS", []),
            patch("handlers.group_antispam.reports_group_id", return_value=-200),
            patch("handlers.group_antispam.load_extra_phrases", AsyncMock(return_value=())),
        ):
            await group_antispam_handler(update, context)

        msg.delete.assert_awaited_once()
        bot.ban_chat_member.assert_awaited_once()
        kwargs = bot.ban_chat_member.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], chat.id)
        self.assertEqual(kwargs["user_id"], user.id)
        self.assertTrue(kwargs["revoke_messages"])
        bot.send_message.assert_awaited_once()
        log = bot.send_message.await_args.kwargs["text"]
        self.assertIn("Антиспам", log)
        self.assertNotIn("clck.ru", log)
        self.assertNotIn("KLD777", log)

    async def test_ham_left_alone(self):
        msg, user, chat = _message(text="какой курс usdt")
        update = MagicMock()
        update.effective_message = msg
        update.effective_chat = chat
        update.effective_user = user
        bot = MagicMock()
        bot.username = "x"
        bot.get_chat_member = AsyncMock()
        bot.ban_chat_member = AsyncMock()
        context = MagicMock()
        context.bot = bot

        with (
            patch("handlers.group_antispam.is_watched_public_chat", return_value=True),
            patch("handlers.group_antispam.load_extra_phrases", AsyncMock(return_value=())),
        ):
            await group_antispam_handler(update, context)

        msg.delete.assert_not_called()
        bot.ban_chat_member.assert_not_called()
        bot.get_chat_member.assert_not_called()

    async def test_skips_chat_admin(self):
        msg, user, chat = _message(text=SHOP_SPAM)
        update = MagicMock()
        update.effective_message = msg
        update.effective_chat = chat
        update.effective_user = user
        bot = MagicMock()
        bot.username = "x"
        bot.get_chat_member = AsyncMock(return_value=_member("administrator"))
        bot.ban_chat_member = AsyncMock()
        context = MagicMock()
        context.bot = bot

        with (
            patch("handlers.group_antispam.is_watched_public_chat", return_value=True),
            patch("handlers.group_antispam.TELEGRAM_ADMIN_IDS", []),
            patch("handlers.group_antispam.load_extra_phrases", AsyncMock(return_value=())),
        ):
            await group_antispam_handler(update, context)

        msg.delete.assert_not_called()
        bot.ban_chat_member.assert_not_called()

    async def test_skips_other_chats(self):
        msg, user, chat = _message(text=SHOP_SPAM)
        update = MagicMock()
        update.effective_message = msg
        update.effective_chat = chat
        update.effective_user = user
        context = MagicMock()
        context.bot = MagicMock()

        with patch("handlers.group_antispam.is_watched_public_chat", return_value=False):
            await group_antispam_handler(update, context)

        msg.delete.assert_not_called()


class AntispamMainTests(unittest.TestCase):
    def test_missing_token_exits(self):
        with (
            patch("antispam_main.TELEGRAM_ANTISPAM_BOT_TOKEN", ""),
            self.assertRaises(SystemExit) as ctx,
        ):
            antispam_main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()

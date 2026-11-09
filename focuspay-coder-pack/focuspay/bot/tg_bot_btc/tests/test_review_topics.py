"""Forum topic routing for published reviews. No Telegram calls."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from services import review_topics


class _TempTopics(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("REVIEW_TOPICS_FILE")
        os.environ["REVIEW_TOPICS_FILE"] = str(Path(self._dir.name) / "topics.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("REVIEW_TOPICS_FILE", None)
        else:
            os.environ["REVIEW_TOPICS_FILE"] = self._prev
        self._dir.cleanup()


class ReviewTopicRoutingTests(_TempTopics):
    def test_vpn_and_exchange_use_different_threads(self):
        store = {"chat_id": -100, "vpn": 11, "exchange": 22}
        self.assertEqual(review_topics.thread_id(store, "vpn"), 11)
        self.assertEqual(review_topics.thread_id(store, "exchange"), 22)
        self.assertEqual(review_topics.thread_id(store, None), 22)
        self.assertIsNone(review_topics.thread_id({}, "vpn"))

    def test_thread_kwargs_only_for_the_registered_forum(self):
        review_topics.write_store({"chat_id": -100, "vpn": 11, "exchange": 22})
        self.assertEqual(review_topics.thread_kwargs(-100, "vpn"), {"message_thread_id": 11})
        self.assertEqual(review_topics.thread_kwargs("@focuspayr", "vpn"), {})
        self.assertEqual(review_topics.thread_kwargs(-200, "exchange"), {})

    def test_copy_skips_when_the_post_is_already_in_the_forum(self):
        review_topics.write_store({"chat_id": -100, "vpn": 11, "exchange": 22})
        bot = AsyncMock()
        asyncio.run(
            review_topics.copy_into_topic(
                bot,
                product="vpn",
                from_chat_id=-100,
                text_message_id=5,
            )
        )
        bot.forward_message.assert_not_called()

    def test_copy_forwards_text_and_photo_into_the_product_topic(self):
        review_topics.write_store({"chat_id": -100, "vpn": 11, "exchange": 22})
        bot = AsyncMock()
        asyncio.run(
            review_topics.copy_into_topic(
                bot,
                product="exchange",
                from_chat_id=-390,
                text_message_id=7,
                photo_message_id=8,
            )
        )
        self.assertEqual(bot.forward_message.await_count, 2)
        first = bot.forward_message.await_args_list[0].kwargs
        self.assertEqual(first["chat_id"], -100)
        self.assertEqual(first["message_thread_id"], 22)
        self.assertEqual(first["message_id"], 7)
        self.assertEqual(bot.forward_message.await_args_list[1].kwargs["message_id"], 8)

    def test_store_roundtrip(self):
        review_topics.write_store({"chat_id": 1, "vpn": 2, "exchange": 3})
        self.assertEqual(review_topics.read_store()["exchange"], 3)
        saved = json.loads(Path(os.environ["REVIEW_TOPICS_FILE"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["vpn"], 2)

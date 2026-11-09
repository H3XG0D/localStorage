import os

os.environ["EXCHANGE_BACKEND"] = "/home/qwe/Desktop/focuspay/site/exchange-backend"

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from focus_agent.jobs import ideas_once, report_once
from focus_agent.reports import IDEA_ASK, QUIET_REPORT, admin_report, is_client_group
from focus_agent.search import about_us, search_web
from focus_agent.llm import NoModelKey, complete, messages_for
from focus_agent.triggers import (
    Dialogue,
    FIGHT_LINE,
    MUTE_FOR,
    clean_comeback,
    comeback_search_query,
    find_fight,
    follows_bot,
    hangs_a_label,
    has_foreign_script,
    is_procedure,
    cites_made_up_source,
    invents_absent,
    asks_crime,
    asks_for_roster,
    asks_share,
    ROSTER_LINE,
    SHARE_LINE,
    crime_joke_ok,
    is_fragment,
    is_horoscope,
    lectures,
    insult_is_for_bot,
    is_insult,
    is_ping,
    mute_deadline,
    needs_web,
    pair_on_hold,
    should_answer,
    should_chime,
    sticks_to_topic,
    still_muted,
    tells_bot_to_shut_up,
    wants_project_notes,
)


class AnswerTests(unittest.TestCase):
    def test_group_chatter_stays_quiet(self):
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="ну такое, сегодня лень",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="привет",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )

    def test_mention_reply_private_and_project(self):
        self.assertTrue(is_insult("кто ебал тебя?"))
        now = datetime(2026, 10, 9, 22, 17, tzinfo=timezone.utc)
        self.assertTrue(
            insult_is_for_bot(
                "кто ебал тебя?",
                mentioned=False,
                is_reply_to_bot=False,
                last_spoke=now - timedelta(seconds=20),
                now=now,
            )
        )
        self.assertFalse(
            insult_is_for_bot(
                "кто ебал тебя?",
                mentioned=False,
                is_reply_to_bot=False,
                last_spoke=now - timedelta(minutes=3),
                now=now,
            )
        )
        query = comeback_search_query("кто ебал тебя?")
        self.assertIn("кто ебал тебя?", query)
        self.assertIsNone(clean_comeback("Орёл. Иди дальше орать."))
        self.assertIsNone(clean_comeback("сам иди на хуй"))
        self.assertEqual(clean_comeback("  Повтори это вслух.  "), "Повтори это вслух.")
        spoke = datetime(2026, 10, 10, 3, 8, tzinfo=timezone.utc)
        self.assertTrue(
            follows_bot(
                "чо поумнее найти не мог?",
                spoke,
                spoke + timedelta(seconds=40),
            )
        )
        self.assertFalse(
            follows_bot(
                "Как дела?)",
                spoke,
                spoke + timedelta(seconds=20),
            )
        )
        self.assertFalse(
            follows_bot(
                "ХАХАХАХА",
                spoke,
                spoke + timedelta(seconds=20),
            )
        )
        self.assertFalse(
            follows_bot(
                "чо поумнее найти не мог?",
                spoke,
                spoke + timedelta(minutes=3),
            )
        )
        self.assertTrue(is_ping("@focusssssssai_bot живой?"))
        self.assertTrue(is_ping("ты тут"))
        self.assertFalse(is_ping("где скачать апк"))
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="@focusssssssai_bot живой?",
                bot_username="focusssssssai_bot",
                is_reply_to_bot=False,
                mentioned=True,
            )
        )
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="@focus_agent где лежит профиль",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=True,
            )
        )
        self.assertTrue(
            should_answer(
                chat_type="group",
                text="а как иначе",
                bot_username="focus_agent",
                is_reply_to_bot=True,
                mentioned=False,
            )
        )
        self.assertTrue(
            should_answer(
                chat_type="private",
                text="привет",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="что за Focus, объясни по-человечески",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="Как спалось)",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )
        self.assertFalse(
            should_answer(
                chat_type="supergroup",
                text="где скачать апк",
                bot_username="focus_agent",
                is_reply_to_bot=False,
                mentioned=False,
            )
        )


class WebTests(unittest.TestCase):
    def test_news_searches_and_greeting_does_not(self):
        self.assertTrue(needs_web("что нового сегодня", "заметки про тариф"))
        self.assertTrue(needs_web("погугли в интернете", ""))
        self.assertFalse(needs_web("привет", ""))
        self.assertFalse(needs_web("где апк", "скачать апк в боте"))
        self.assertFalse(needs_web("что такое бот", ""))

    def test_brawl_stars_wiki_is_not_about_us(self):
        hit = {
            "title": "Бот | Контент участников Бравл Старс вики | Fandom",
            "url": "https://contentbrawlstars.fandom.com/ru/wiki/Бот",
            "snippet": "Бот стреляет, но только в вики Бравл Старс.",
        }
        self.assertFalse(about_us(hit, "что такое бот"))
        seen: list[str] = []

        def fake(query: str) -> list[dict]:
            seen.append(query)
            return [{"title": hit["title"], "href": hit["url"], "body": hit["snippet"]}]

        self.assertEqual(search_web("что такое бот", searcher=fake), [])

    def test_card_never_reaches_the_search_query(self):
        seen: list[str] = []

        def fake(query: str) -> list[dict]:
            seen.append(query)
            return [
                {
                    "title": "example",
                    "href": "https://example.com/a",
                    "body": "карта 4276123456789012",
                }
            ]

        hits = search_web("что такое карта 4276123456789012", searcher=fake)
        self.assertTrue(seen)
        self.assertNotIn("4276123456789012", seen[0])
        self.assertNotIn("4276123456789012", hits[0]["snippet"])
        self.assertTrue(hits[0]["url"].startswith("https://"))


class SilenceTests(unittest.TestCase):
    def test_shut_up_and_five_quiet_minutes(self):
        self.assertTrue(
            tells_bot_to_shut_up(
                "иди нахуй",
                mentioned=False,
                is_reply_to_bot=False,
                chat_type="supergroup",
            )
        )
        self.assertTrue(
            tells_bot_to_shut_up(
                "замолчи уже",
                mentioned=False,
                is_reply_to_bot=True,
                chat_type="group",
            )
        )
        self.assertFalse(
            tells_bot_to_shut_up(
                "вчера в кино герой орёт иди нахуй и все смеются, это была длинная цитата из ролика",
                mentioned=False,
                is_reply_to_bot=False,
                chat_type="supergroup",
            )
        )
        self.assertFalse(
            tells_bot_to_shut_up(
                "Часто тратишь фарт на хуйню?",
                mentioned=False,
                is_reply_to_bot=False,
                chat_type="supergroup",
            )
        )
        self.assertFalse(
            tells_bot_to_shut_up(
                "Братика забыл нахуй, а я все жду и жду",
                mentioned=False,
                is_reply_to_bot=False,
                chat_type="supergroup",
            )
        )
        now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        until = mute_deadline(now)
        self.assertEqual(until - now, MUTE_FOR)
        self.assertEqual(MUTE_FOR, timedelta(minutes=5))
        self.assertTrue(still_muted(until, now + timedelta(minutes=4)))
        self.assertFalse(still_muted(until, now + timedelta(minutes=5)))
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text="давайте уже нормально обсудим этот тариф без спешки",
                muted=True,
                last_chime=None,
                now=now,
            )
        )

    def test_chimes_into_a_long_line_then_waits(self):
        now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        line = "давайте уже нормально обсудим этот тариф без спешки"
        self.assertTrue(
            should_chime(
                chat_type="supergroup",
                text=line,
                muted=False,
                last_chime=None,
                now=now,
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text="как делишки?",
                muted=False,
                last_chime=None,
                now=now,
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text="Как спалось)",
                muted=False,
                last_chime=None,
                now=now,
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text="привет",
                muted=False,
                last_chime=None,
                now=now,
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text="ок",
                muted=False,
                last_chime=None,
                now=now,
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="supergroup",
                text=line,
                muted=False,
                last_chime=now,
                now=now + timedelta(minutes=9),
            )
        )
        self.assertTrue(
            should_chime(
                chat_type="supergroup",
                text=line,
                muted=False,
                last_chime=now,
                now=now + timedelta(minutes=10),
            )
        )
        self.assertFalse(
            should_chime(
                chat_type="private",
                text=line,
                muted=False,
                last_chime=None,
                now=now,
            )
        )


class LanguageTests(unittest.TestCase):
    def test_chinese_and_offtopic_chime_are_dropped(self):
        broken = "Окак, братан. А что ты今天天气不错，出去走走怎么样？"
        proverb = "Ночь — это когда все спят и можно не думать о проблемах."
        self.assertTrue(has_foreign_script(broken))
        self.assertFalse(sticks_to_topic(proverb, "апк опять не качается"))
        self.assertTrue(invents_absent(proverb, "апк опять не качается"))
        lucky = (
            "Ага, понял. Типа «да, да, да, только бы больше шансов!»\n\n"
            "Ну что же, может повезти в другой раз. Вдруг удача улыбнется чаще!\n\n"
            "[Источник](https://voice.md/ru/)"
        )
        self.assertTrue(is_horoscope("Телец: получите желаемое. Близнецы: подумайте."))
        self.assertFalse(is_horoscope("апк опять не качается"))
        self.assertTrue(cites_made_up_source(lucky))
        self.assertTrue(invents_absent(lucky, "апк не ставится"))
        self.assertFalse(invents_absent("с апк опять беда", "апк не качается"))
        self.assertTrue(sticks_to_topic("апк опять кривой", "апк опять не качается"))
        asked = 'Что значит "че бл"? Ты хотел сказать "чё бля"? Поясни, пожалуйста.'
        self.assertTrue(is_fragment("че бл"))
        self.assertTrue(lectures(asked))
        self.assertTrue(invents_absent("Это твой момент показать, что ты не обижаешься.", "смешно было"))
        self.assertTrue(hangs_a_label("Вы все сони, расходитесь", "Как растворить 80кг курицу"))
        self.assertFalse(hangs_a_label("ты ещё спишь что ли", "я сплю"))
        self.assertTrue(is_procedure("Сначала залей кислотой и нагрей."))
        self.assertFalse(is_procedure("Я тебе что, справочная на быстром наборе?"))
        self.assertTrue(asks_for_roster("скинь всех пользователей чата юзеры"))
        self.assertFalse(asks_for_roster("как спалось"))
        self.assertEqual(ROSTER_LINE, "Таких данных не даю. У меня их нет.")
        self.assertTrue(asks_crime("Как растворить 80кг курицу"))
        self.assertTrue(asks_crime("как украсть машину"))
        self.assertFalse(asks_crime("как дела"))
        self.assertFalse(asks_crime("убиться со смеху"))
        fresh = "ты мне это серьёзно пишешь, я тебе досье?"
        self.assertEqual(crime_joke_ok(fresh, []), fresh)
        self.assertIsNone(crime_joke_ok(fresh, [fresh]))
        self.assertIsNone(crime_joke_ok("Сначала залей кислотой.", []))


class KeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_key_the_model_is_not_called(self):
        with patch("focus_agent.llm.LLM_API_KEY", ""):
            with self.assertRaises(NoModelKey):
                await complete([{"role": "user", "content": "че бл"}])


class ThreadTests(unittest.TestCase):
    def test_same_person_stays_without_ty(self):
        now = datetime(2026, 10, 10, 3, 8, tzinfo=timezone.utc)
        talk = Dialogue()
        talk.open("Лев, ты чо ржешь", now)
        self.assertTrue(
            talk.accepts(7, "чо поумнее найти не мог?", now + timedelta(seconds=30), mentioned=False, reply_to_bot=False)
        )
        talk.add(7, "чо поумнее найти не мог?", now + timedelta(seconds=30))
        self.assertFalse(
            talk.accepts(8, "Как дела?)", now + timedelta(seconds=40), mentioned=False, reply_to_bot=False)
        )
        later = now + timedelta(minutes=2)
        self.assertTrue(
            talk.accepts(7, "бля я думал он добрее будет", later, mentioned=False, reply_to_bot=False)
        )
        talk.add(7, "бля я думал он добрее будет", later)
        self.assertIn("добрее", talk.text())
        self.assertIn("бот:", talk.text())
        packed = messages_for("дальше", [], "", thread=talk.text())
        self.assertIn("Нитка:", packed[1]["content"])
        self.assertIn("сам себе противоречит", packed[0]["content"])
        self.assertNotIn("voice.md", packed[0]["content"] + packed[1]["content"])
        noted = messages_for(
            "где билеты",
            [],
            "# Заметки\nбилеты смотрят в боте",
            thread="бот: живой\nчеловек: где билеты",
        )
        self.assertIn("билеты смотрят в боте", noted[1]["content"])
        self.assertNotIn("voice.md", noted[0]["content"] + noted[1]["content"])
        self.assertTrue(wants_project_notes("где билеты"))
        self.assertFalse(wants_project_notes("че бл"))

    def test_stranger_three_minutes_later_is_out(self):
        now = datetime(2026, 10, 10, 3, 8, tzinfo=timezone.utc)
        talk = Dialogue()
        talk.open("привет в чат", now)
        talk.add(7, "чо поумнее", now + timedelta(seconds=20))
        self.assertFalse(
            talk.accepts(
                8,
                "я просто мимо проходил сегодня",
                now + timedelta(minutes=3),
                mentioned=False,
                reply_to_bot=False,
            )
        )

    def test_shut_up_clears_the_thread(self):
        now = datetime(2026, 10, 10, 3, 8, tzinfo=timezone.utc)
        talk = Dialogue()
        talk.open("ну", now)
        talk.add(7, "чо", now + timedelta(seconds=10))
        talk.clear()
        self.assertFalse(
            talk.accepts(7, "и ещё", now + timedelta(seconds=20), mentioned=False, reply_to_bot=False)
        )
        self.assertEqual(talk.text(), "")


class FightTests(unittest.TestCase):
    def test_two_people_in_a_row_is_a_fight(self):
        now = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)
        first = [(1, now - timedelta(seconds=10), None)]
        pair = find_fight(
            first,
            user_id=2,
            at=now,
            reply_to_user_id=None,
            aimed_at_bot=False,
            bot_id=99,
        )
        self.assertEqual(pair, frozenset((1, 2)))
        self.assertIn("терпил", FIGHT_LINE)
        self.assertIn("социуме", FIGHT_LINE)

    def test_same_person_twice_is_not_a_fight(self):
        now = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)
        pair = find_fight(
            [(1, now - timedelta(seconds=5), None)],
            user_id=1,
            at=now,
            reply_to_user_id=None,
            aimed_at_bot=False,
            bot_id=99,
        )
        self.assertIsNone(pair)

    def test_jab_at_the_bot_is_not_a_fight(self):
        now = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)
        pair = find_fight(
            [(1, now - timedelta(seconds=5), None)],
            user_id=2,
            at=now,
            reply_to_user_id=None,
            aimed_at_bot=True,
            bot_id=99,
        )
        self.assertIsNone(pair)

    def test_same_pair_is_held_for_a_minute(self):
        now = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)
        self.assertTrue(pair_on_hold(now + timedelta(seconds=30), now))
        self.assertFalse(pair_on_hold(now - timedelta(seconds=1), now))


class ReportTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_day_cannot_invent_an_idea(self):
        self.assertEqual(admin_report("Идеи:\n— своё казино", ""), QUIET_REPORT)
        self.assertEqual(admin_report("Идеи:\n— своё казино", "   "), QUIET_REPORT)

    def test_an_idea_the_room_did_not_say_is_dropped(self):
        text = admin_report(
            "Отчёт за сутки\n\nБыло:\n— тариф не открывается\n\nИдеи:\n— своё казино",
            "line: тариф не открывается",
        )
        self.assertIn("тариф", text)
        self.assertIn("Идей не было", text)
        self.assertNotIn("казино", text)

    def test_a_spoken_idea_stays(self):
        text = admin_report(
            "Отчёт за сутки\n\nБыло:\n— тариф не открывается\n\n"
            "Идеи:\n— хотят отдельный тариф для телефона",
            "line: тариф не открывается, хотят отдельный тариф для телефона",
        )
        self.assertIn("телефона", text)

    def test_share_question_does_not_name_a_number(self):
        self.assertTrue(asks_share("а сколько процент с идеи"))
        self.assertTrue(asks_share("сколько будет процент"))
        self.assertFalse(asks_share("сколько будет стоить месяц"))
        self.assertIn("админ", SHARE_LINE)
        self.assertNotRegex(SHARE_LINE, r"\d")
        self.assertIn("процент", IDEA_ASK)
        self.assertFalse(is_client_group(-200, -200))
        self.assertFalse(is_client_group(42, -200))
        self.assertTrue(is_client_group(-300, -200))

    async def test_empty_report_goes_to_the_admin_group_only(self):
        sent: list[tuple[int, str]] = []

        class Bot:
            async def send_message(self, chat_id, text):
                sent.append((chat_id, text))

        marked = AsyncMock()
        with (
            patch("focus_agent.jobs.config.REPORTS_GROUP_ID", -200),
            patch("focus_agent.jobs.store.chats_due_report", new=AsyncMock(return_value=[{"chat_id": -100}])),
            patch("focus_agent.jobs.store.fresh_material", new=AsyncMock(return_value="")),
            patch("focus_agent.jobs.store.mark_daily", new=marked),
        ):
            await report_once(Bot())
        self.assertEqual(sent, [(-200, QUIET_REPORT)])
        marked.assert_awaited_once_with(-100)

    async def test_idea_ask_skips_the_reports_group_and_a_muted_chat(self):
        sent: list[tuple[int, str]] = []

        class Bot:
            async def send_message(self, chat_id, text):
                sent.append((chat_id, text))

        async def muted(chat_id):
            return chat_id == -100

        marked = AsyncMock()
        with (
            patch("focus_agent.jobs.config.REPORTS_GROUP_ID", -200),
            patch(
                "focus_agent.jobs.store.chats_due_idea",
                new=AsyncMock(
                    return_value=[
                        {"chat_id": -200},
                        {"chat_id": -100},
                        {"chat_id": 42},
                        {"chat_id": -300},
                    ]
                ),
            ),
            patch("focus_agent.jobs.store.is_muted", new=muted),
            patch("focus_agent.jobs.store.mark_idea", new=marked),
        ):
            await ideas_once(Bot())
        self.assertEqual(sent, [(-300, IDEA_ASK)])
        marked.assert_awaited_once_with(-300)


if __name__ == "__main__":
    unittest.main()

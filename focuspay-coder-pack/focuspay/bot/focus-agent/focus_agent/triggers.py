"""When the bot speaks, when it jumps in, and when it has to shut up."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

_PROJECT_NAME = re.compile(r"focus|фокус", re.IGNORECASE)
_PROJECT_TOPIC = re.compile(
    r"vpn|впн|апк|подключ|подписк|тариф|скачать|бот",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"^(где|как|что)\b|\?", re.IGNORECASE)
_WHAT_IS_FOCUS = re.compile(r"что\s+за\s+(focus|фокус)", re.IGNORECASE)
_WEB = re.compile(
    r"что\s+нов|погугл|загугл|в\s+интернете|новост",
    re.IGNORECASE,
)
_PING = re.compile(
    r"^(?:живой|ты\s+жив(?:ой)?|ты\s+тут|ты\s+здесь|ау+|алло|на\s+месте)[?!.\s]*$",
    re.IGNORECASE,
)
_GREET = re.compile(
    r"^(привет|хай|здарова|ку|доброе утро|добрый день|добрый вечер)[!.?\s]*$",
    re.IGNORECASE,
)
_SILENCE = re.compile(
    r"(?:нахуй|на\s+хуй)\b|заткни|замолчи|помолчи|(?:^|\s)молчи(?:\s|!|$)|отстань|отвали|"
    r"не\s+лезь|shut\s*up|хватит\s+(?:писать|уже|болтать)",
    re.IGNORECASE,
)

_INSULT = re.compile(
    r"еба[лт]|ебать|ебёт|ебет|хуесос|долбо[её]б|мудак|чмо|лошара|тварь|урод",
    re.IGNORECASE,
)
_YOU = re.compile(r"\b(тебя|тебе|ты)\b", re.IGNORECASE)
_DIRTY = re.compile(
    r"еба|хуй|хуе|пизд|бля|орёл|орел",
    re.IGNORECASE,
)

MUTE_FOR = timedelta(minutes=5)
CHIME_GAP = timedelta(minutes=10)
SPOKE_AIM = timedelta(minutes=2)
FOLLOW_WINDOW = timedelta(seconds=90)
THREAD_LIFE = timedelta(minutes=5)
_FOLLOW = re.compile(
    r"\b(ты|тебе|тебя|чо|чё|че|почему|поумнее)\b",
    re.IGNORECASE,
)
_SMALL_TALK = re.compile(
    r"^(?:привет(?:ик)?|хай|здарова|ку|доброе|добрый(?:\s+(?:день|вечер|утро))?|"
    r"как\s+дела|как\s+делишки|как\s+ты|как\s+сам|как\s+жизнь|"
    r"как\s+спал(?:ось|ась|ся)?|выспал(?:ся|ась|ись)?|"
    r"ты\s+как|че\s+как|чё\s+как|чо\s+как)"
    r"(?:\s+у\s+тебя)?"
    r"[\s)?.!🙃🤣😳]*$",
    re.IGNORECASE,
)
FIGHT_WINDOW = timedelta(seconds=45)
FIGHT_HOLD = timedelta(seconds=60)
_CHIME_MIN_CHARS = 12

FIGHT_LINE = (
    "Если будете дальше выебываться, дальше будете сидеть и терпеть как терпилы, "
    "либо учитесь находиться в социуме."
)


def without_mentions(text: str | None) -> str:
    return re.sub(r"@\w+", "", text or "").strip()


def wants_project_notes(question: str | None) -> bool:
    return bool(
        re.search(r"focus|фокус|билет|апк|подключ|vpn|впн", question or "", re.IGNORECASE)
    )


def is_insult(text: str | None) -> bool:
    return bool(_INSULT.search(without_mentions(text)))


def follows_bot(text: str | None, last_spoke: datetime | None, now: datetime) -> bool:
    """A line right after the bot spoke is to him, even without a reply or a tag."""
    if last_spoke is None or now - last_spoke > FOLLOW_WINDOW:
        return False
    body = without_mentions(text)
    if len(body) < 2 or is_small_talk(body):
        return False
    return bool(_FOLLOW.search(body))


class Dialogue:
    """One talk the bot opened, and the people who stayed in it."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self.people: set[int] = set()
        self.updated: datetime | None = None
        self.bot_line_at: datetime | None = None

    def open(self, bot_text: str, now: datetime) -> None:
        self.lines.append(("bot", (bot_text or "").strip()[:300]))
        self.lines = self.lines[-12:]
        self.updated = now
        self.bot_line_at = now

    def closed(self, now: datetime) -> bool:
        if self.updated is None:
            return True
        return now - self.updated > THREAD_LIFE

    def accepts(
        self,
        user_id: int,
        text: str | None,
        now: datetime,
        *,
        mentioned: bool,
        reply_to_bot: bool,
    ) -> bool:
        if self.closed(now) or self.bot_line_at is None:
            return False
        if is_small_talk(text) and not mentioned and not reply_to_bot:
            return False
        if mentioned or reply_to_bot:
            return True
        if user_id in self.people and now - self.updated <= THREAD_LIFE:
            return True
        return follows_bot(text, self.bot_line_at, now)

    def add(self, user_id: int, text: str, now: datetime) -> None:
        self.people.add(user_id)
        self.lines.append((str(user_id), text.strip()[:300]))
        self.lines = self.lines[-12:]
        self.updated = now

    def clear(self) -> None:
        self.lines.clear()
        self.people.clear()
        self.updated = None
        self.bot_line_at = None

    def text(self) -> str:
        rows = []
        for who, line in self.lines:
            rows.append(f"{'бот' if who == 'bot' else 'человек'}: {line}")
        return "\n".join(rows)


def insult_is_for_bot(
    text: str | None,
    *,
    mentioned: bool,
    is_reply_to_bot: bool,
    last_spoke: datetime | None,
    now: datetime,
) -> bool:
    """A jab with «ты/тебя» right after the bot spoke is at him, not at the room."""
    if not is_insult(text):
        return False
    if mentioned or is_reply_to_bot:
        return True
    if last_spoke is None or now - last_spoke > SPOKE_AIM:
        return False
    return bool(_YOU.search(without_mentions(text)))


def comeback_search_query(jab: str | None) -> str:
    """The phrase goes to search so the turn is about that line, not a generic tip."""
    phrase = re.sub(r"\s+", " ", without_mentions(jab)).strip()[:180]
    if not phrase:
        return "остроумный спокойный ответ на грубость без мата одно предложение"
    return f"как остроумно ответить на фразу: {phrase}"


def clean_comeback(text: str | None) -> str | None:
    line = re.sub(r"\s+", " ", (text or "").strip().strip('"'))
    if not line or len(line) > 220:
        return None
    if _DIRTY.search(line) or _INSULT.search(line):
        return None
    return line


def is_fragment(text: str | None) -> bool:
    """A short blurt, not a person lost in their own words."""
    return len(without_mentions(text)) <= 12


def lectures(reply: str | None) -> bool:
    return bool(_LECTURE.search(reply or ""))


_ROOM_LABEL = re.compile(r"сон(?:ями|ям|ях|я|и|ю|е)\b", re.IGNORECASE)
_ABOUT_SLEEP = re.compile(r"спл|сон", re.IGNORECASE)
_PROCEDURE = re.compile(
    r"сначала|затем|кислот|щелоч|щёлоч|нагрей|залей|пропорц",
    re.IGNORECASE,
)


def hangs_a_label(answer: str | None, question: str | None) -> bool:
    """A nickname for the room, dragged in from an older line."""
    if not _ROOM_LABEL.search(answer or ""):
        return False
    return not _ABOUT_SLEEP.search(question or "")


def is_procedure(answer: str | None) -> bool:
    """Steps for a joke request. The reply should be the joke, not a method."""
    return bool(_PROCEDURE.search(answer or ""))


_CRIME_HOW = re.compile(
    r"(?:как|можно|способ|научи|подскаж).{0,48}"
    r"(?:убить|ограб|взлом|взломать|отрав|украсть|угнать|спрятать|раствор|"
    r"поддел|взорвать|бомб|наркот|ствол|пистолет|труп|расчлен|отмыт)|"
    r"раствор\w*.{0,40}(?:куриц|тело|труп)|"
    r"(?:куриц|тело|труп).{0,40}раствор|"
    r"80\s*кг\s*куриц",
    re.IGNORECASE | re.DOTALL,
)


_ROSTER = re.compile(
    r"пользовател|юзер|участник|кто\s+в\s+чате|список\s+(?:чат|люд|юзер|пользовател)",
    re.IGNORECASE,
)
ROSTER_LINE = "Таких данных не даю. У меня их нет."


def asks_for_roster(text: str | None) -> bool:
    """A request for the chat's people. The bot does not have that list."""
    return bool(_ROSTER.search(without_mentions(text)))


_SHARE = re.compile(
    r"(?:сколько|какой|какая).{0,24}(?:процент|доля)|"
    r"процент\s+с\s+(?:иде|прибыл)|размер\s+(?:доли|процент)",
    re.IGNORECASE,
)
SHARE_LINE = "Процент назначает админ, когда берёт идею. Я цифру не ставлю."


def asks_share(text: str | None) -> bool:
    """They want a number for the idea share. The bot does not set it."""
    return bool(_SHARE.search(without_mentions(text)))


def asks_crime(text: str | None) -> bool:
    """A how-to aimed at the bot. Not a laugh, not small talk."""
    body = without_mentions(text)
    if re.search(r"со\s+смех|убить\s+время", body, re.IGNORECASE):
        return False
    return bool(_CRIME_HOW.search(body))


def crime_joke_ok(answer: str | None, already: list[str]) -> str | None:
    """A fresh clapback. Same words as last time, or a method, do not go out."""
    line = re.sub(r"\s+", " ", (answer or "").strip().strip('"'))
    if not line or len(line) > 220:
        return None
    if is_procedure(line) or hangs_a_label(line, "") or has_foreign_script(line):
        return None
    folded = line.casefold()
    if any(folded == old.casefold() for old in already):
        return None
    return line


def is_small_talk(text: str | None) -> bool:
    """A greeting or «how are you» between people. Not a line to the bot."""
    return bool(_SMALL_TALK.match(without_mentions(text)))


def is_ping(text: str | None) -> bool:
    """A tag that only checks the bot is awake, not a project question."""
    return bool(_PING.match(without_mentions(text)))


def asks_about_project(text: str | None) -> bool:
    """A project question in the group, not small talk."""
    body = (text or "").strip()
    if not body:
        return False
    if _WHAT_IS_FOCUS.search(body):
        return True
    if _PROJECT_NAME.search(body) and _QUESTION.search(body):
        return True
    if _QUESTION.search(body) and _PROJECT_TOPIC.search(body):
        return True
    return False


def should_answer(
    *,
    chat_type: str,
    text: str | None,
    bot_username: str,
    is_reply_to_bot: bool,
    mentioned: bool,
) -> bool:
    """Private chat, or a reply to the bot's own message. Nothing else in a group."""
    del bot_username, mentioned
    body = (text or "").strip()
    if not body or body.startswith("/"):
        return False
    if chat_type == "private":
        return True
    return is_reply_to_bot


def needs_web(question: str | None, notes_text: str | None) -> bool:
    """Search only when the person asked to look outside. A missing note is not a web query."""
    del notes_text
    q = (question or "").strip()
    if not q or _GREET.match(q):
        return False
    return bool(_WEB.search(q))


def is_silence_phrase(text: str | None) -> bool:
    return bool(_SILENCE.search(text or ""))


def tells_bot_to_shut_up(
    text: str | None,
    *,
    mentioned: bool,
    is_reply_to_bot: bool,
    chat_type: str,
) -> bool:
    """A short 'shut up' counts even without a mention. A long quote does not."""
    if not is_silence_phrase(text):
        return False
    if chat_type == "private" or mentioned or is_reply_to_bot:
        return True
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return len(compact) <= 20


def still_muted(muted_until: datetime | None, now: datetime) -> bool:
    if muted_until is None:
        return False
    return muted_until > now


def mute_deadline(now: datetime) -> datetime:
    return now + MUTE_FOR


def should_chime(
    *,
    chat_type: str,
    text: str | None,
    muted: bool,
    last_chime: datetime | None,
    now: datetime,
) -> bool:
    """Jump into a group conversation, but not into every line and never while muted."""
    if muted or chat_type == "private":
        return False
    body = (text or "").strip()
    if len(body) < _CHIME_MIN_CHARS or body.startswith("/"):
        return False
    if is_small_talk(body) or is_silence_phrase(body) or asks_about_project(body):
        return False
    if last_chime is not None and now - last_chime < CHIME_GAP:
        return False
    return True


def pair_on_hold(until: datetime | None, at: datetime) -> bool:
    return until is not None and until > at


def find_fight(
    previous: list[tuple[int, datetime, int | None]],
    *,
    user_id: int,
    at: datetime,
    reply_to_user_id: int | None,
    aimed_at_bot: bool,
    bot_id: int,
) -> frozenset[int] | None:
    """Two different people insulting each other. A jab at the bot is not a fight."""
    if aimed_at_bot or user_id == bot_id:
        return None
    start = at - FIGHT_WINDOW
    others = [
        item
        for item in previous
        if item[0] not in (user_id, bot_id) and item[1] >= start
    ]
    if not others:
        return None
    other_id = others[-1][0]
    if reply_to_user_id not in (None, user_id, bot_id):
        matched = [item for item in others if item[0] == reply_to_user_id]
        if not matched:
            return None
        other_id = reply_to_user_id
    return frozenset((user_id, other_id))


def has_foreign_script(text: str | None) -> bool:
    """Qwen sometimes drops into Chinese mid-sentence. That must not be sent."""
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text or ""))


_ABSENT = ("проблем", "погод", "ночь", "спят", "философ", "удач", "шанс", "обиж", "интересн")
_LECTURE = re.compile(r"поясни|что значит|хотел сказать|пожалуйста", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)
_INTERNAL_NAME = re.compile(r"voice\.md|agent-journal", re.IGNORECASE)


_ZODIAC = re.compile(
    r"телец|близнец|гороскоп|овен|водоле|скорпион|козерог|стрелец|меланхол",
    re.IGNORECASE,
)


def is_horoscope(text: str | None) -> bool:
    return bool(_ZODIAC.search(text or ""))


def invents_absent(reply: str | None, source: str | None) -> bool:
    """A chime must not invent a theme the room did not say."""
    said = (source or "").lower()
    line = (reply or "").lower()
    return any(stem in line and stem not in said for stem in _ABSENT)


def cites_made_up_source(reply: str | None, allowed_urls: list[str] | None = None) -> bool:
    """voice.md is tone, not a website. A link must be one we actually fetched."""
    text = reply or ""
    if _INTERNAL_NAME.search(text):
        return True
    allowed = allowed_urls or []
    for url in _URL.findall(text):
        if not any(url.startswith(ok) or ok.startswith(url) for ok in allowed):
            return True
    return False


def sticks_to_topic(reply: str | None, source: str | None) -> bool:
    words = set(re.findall(r"[а-яё]{4,}", (source or "").lower()))
    if not words:
        return False
    hay = (reply or "").lower()
    return any(word in hay for word in words)


def is_bind_text(text: str | None) -> bool:
    raw = (text or "").lower()
    return "opsbind_" in raw or raw.startswith("/ops_bind")

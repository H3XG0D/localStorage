"""Polling bot. Run: python -m focus_agent"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from focus_agent.config import DATABASE_DSN, TOKEN
from focus_agent.jobs import compress_loop, outreach_loop
from focus_agent.llm import (
    NoModelKey,
    comeback_messages,
    complete,
    crime_messages,
    messages_for,
    retrieved_notes,
)
from focus_agent.redact import redact
from focus_agent.search import format_hits, search_web
from focus_agent import store
from focus_agent.triggers import (
    clean_comeback,
    comeback_search_query,
    Dialogue,
    FIGHT_HOLD,
    FIGHT_LINE,
    find_fight,
    follows_bot,
    pair_on_hold,
    insult_is_for_bot,
    is_insult,
    is_bind_text,
    is_ping,
    needs_web,
    should_answer,
    has_foreign_script,
    hangs_a_label,
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
    lectures,
    should_chime,
    sticks_to_topic,
    still_muted,
    tells_bot_to_shut_up,
    wants_project_notes,
)

log = logging.getLogger("focus-agent")

_START = (
    "Я Focus Agent. Сижу в чате, слушаю и иногда влезаю сам, чтобы подколоть. "
    "Позовёшь или спросишь по Focus — отвечу.\n\n"
    "Факты беру из заметок или из интернета и даю ссылку. Не выдумываю. "
    "Скажешь замолчать — пропаду на пять минут и не реагирую. "
    "Выплаты и кабинет оператора — не ко мне."
)


async def _post_init(app: Application) -> None:
    if not DATABASE_DSN:
        raise RuntimeError("DATABASE_DSN is required")
    await store.open_pool(DATABASE_DSN)
    app.bot_data["me"] = await app.bot.get_me()
    app.bot_data["tasks"] = [
        asyncio.create_task(compress_loop()),
        asyncio.create_task(outreach_loop(app)),
    ]


async def _post_shutdown(app: Application) -> None:
    for task in app.bot_data.get("tasks") or []:
        task.cancel()
    await store.close_pool()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(_START)


async def on_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member = update.my_chat_member
    if member is None:
        return
    status = member.new_chat_member.status
    if status not in ("member", "administrator"):
        return
    chat = member.chat
    await store.remember_chat(chat.id, chat.title)


async def _deliver(message, text: str) -> None:
    """Reply to the person. If that message is already gone, post in the chat anyway."""
    body = (text or "").strip()[:3500]
    if not body:
        return
    try:
        await message.reply_text(body)
        return
    except Exception:
        log.warning("reply missed chat=%s", message.chat_id)
    await message.get_bot().send_message(chat_id=message.chat_id, text=body)


async def _technique(context: ContextTypes.DEFAULT_TYPE, jab: str) -> str:
    query = comeback_search_query(jab)
    cache = context.bot_data.setdefault("comeback_technique", {})
    cached = cache.get(query)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    text = format_hits(search_web(query))
    if len(cache) > 20:
        cache.clear()
    cache[query] = (time.time(), text)
    return text


async def _crime_joke(context: ContextTypes.DEFAULT_TYPE, message, question: str) -> None:
    said: list[str] = context.bot_data.setdefault("crime_lines", [])
    line = None
    for _ in range(2):
        try:
            raw = await complete(crime_messages(question, said), temperature=0.95)
        except NoModelKey:
            return
        except Exception:
            log.warning("crime joke failed")
            return
        line = crime_joke_ok(raw, said)
        if line:
            break
    if not line:
        return
    said.append(line)
    del said[:-8]
    await _deliver(message, line)
    _mark_spoke(context, message.chat_id, line)


async def _comeback(context: ContextTypes.DEFAULT_TYPE, jab: str) -> str | None:
    technique = await _technique(context, jab)
    for _ in range(2):
        try:
            raw = await complete(comeback_messages(jab, technique), temperature=0.95)
        except NoModelKey:
            return None
        except Exception:
            log.warning("comeback model failed")
            return None
        line = clean_comeback(raw)
        if line:
            return line
    return None


async def _restrict_minute(bot, chat_id: int, user_id: int) -> bool:
    until = datetime.now(timezone.utc) + FIGHT_HOLD
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        return True
    except TelegramError:
        log.warning("restrict failed chat=%s user=%s", chat_id, user_id)
        return False


async def _break_fight(context: ContextTypes.DEFAULT_TYPE, message, pair: frozenset[int]) -> None:
    bot = message.get_bot()
    muted = []
    for user_id in pair:
        muted.append(await _restrict_minute(bot, message.chat_id, user_id))
    if all(muted):
        text = FIGHT_LINE
    else:
        text = "Закрыть рот не могу, нет прав.\n" + FIGHT_LINE
    await _deliver(message, text)
    holds = context.bot_data.setdefault("fight_hold", {}).setdefault(message.chat_id, {})
    holds[pair] = datetime.now(timezone.utc) + FIGHT_HOLD


def _dialogue(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Dialogue:
    return context.bot_data.setdefault("threads", {}).setdefault(chat_id, Dialogue())


def _mark_spoke(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str = "") -> None:
    now = datetime.now(timezone.utc)
    spoken = context.bot_data.setdefault("spoke", {})
    spoken[chat_id] = now
    if text:
        _dialogue(context, chat_id).open(text, now)


async def _speak(message, question: str, *, chime: bool, thread: str = "") -> str | None:
    recent = await store.recent_lines(message.chat.id)
    if chime:
        heard = "\n".join([*recent[-6:], question])
        try:
            raw = await complete(messages_for(question, recent[-6:], "", chime=True))
        except NoModelKey:
            return None
        answer = redact(raw)
        if (
            not answer
            or answer.strip().upper() == "ТИХО"
            or has_foreign_script(answer)
            or invents_absent(answer, heard)
            or hangs_a_label(answer, question)
            or is_procedure(answer)
            or cites_made_up_source(answer)
            or not sticks_to_topic(answer, heard)
        ):
            log.info("drop chime chat=%s", message.chat_id)
            return None
        await _deliver(message, answer)
        log.info("say chime chat=%s chars=%s", message.chat_id, len(answer))
        return answer
    context_block = ""
    recent_for_model: list[str] = []
    if thread:
        recent_for_model = []
    else:
        recent_for_model = recent[-8:]
    if wants_project_notes(question):
        notes = retrieved_notes(question)
        if notes:
            context_block = "# Заметки\n" + notes
    try:
        raw = await complete(messages_for(question, recent_for_model, context_block, thread=thread))
    except NoModelKey:
        return None
    answer = redact(raw)
    if (
        not answer
        or answer.strip().upper() == "ТИХО"
        or has_foreign_script(answer)
        or invents_absent(answer, question)
        or hangs_a_label(answer, question)
        or is_procedure(answer)
        or cites_made_up_source(answer)
        or (is_fragment(question) and lectures(answer))
    ):
        log.info("drop answer chat=%s", message.chat_id)
        return None
    await _deliver(message, answer)
    log.info("say answer chat=%s chars=%s", message.chat_id, len(answer))
    return answer


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text or is_bind_text(message.text):
        return
    chat = message.chat
    await store.remember_chat(chat.id, chat.title)
    cleaned = redact(message.text)
    await store.add_line(chat.id, cleaned)

    me = context.bot_data.get("me") or await context.bot.get_me()
    username = (me.username or "").lower()
    mentioned = bool(username and f"@{username}" in message.text.lower())
    reply = message.reply_to_message
    reply_to_bot = bool(reply and reply.from_user and reply.from_user.id == me.id)
    addressed = chat.type == "private" or reply_to_bot
    if addressed and tells_bot_to_shut_up(
        message.text,
        mentioned=mentioned,
        is_reply_to_bot=reply_to_bot,
        chat_type=chat.type,
    ):
        await store.mute_for(chat.id)
        _dialogue(context, chat.id).clear()
        log.info("muted chat=%s", chat.id)
        return

    if not addressed:
        return

    muted_until, last_chime = await store.chat_clock(chat.id)
    now = datetime.now(timezone.utc)
    if still_muted(muted_until, now):
        return

    if asks_share(message.text):
        await _deliver(message, SHARE_LINE)
        _mark_spoke(context, chat.id, SHARE_LINE)
        return

    if asks_for_roster(message.text):
        await _deliver(message, ROSTER_LINE)
        _mark_spoke(context, chat.id, ROSTER_LINE)
        return

    if asks_crime(message.text):
        await _crime_joke(context, message, message.text)
        return

    last_spoke = context.bot_data.get("spoke", {}).get(chat.id)
    aimed_at_bot = insult_is_for_bot(
        message.text,
        mentioned=mentioned,
        is_reply_to_bot=reply_to_bot,
        last_spoke=last_spoke,
        now=now,
    )
    if chat.type != "private" and is_insult(message.text) and message.from_user:
        history = context.bot_data.setdefault("fight_jabs", {}).setdefault(chat.id, [])
        reply_user = None
        if reply and reply.from_user and not reply_to_bot:
            reply_user = reply.from_user.id
        pair = find_fight(
            history,
            user_id=message.from_user.id,
            at=now,
            reply_to_user_id=reply_user,
            aimed_at_bot=aimed_at_bot,
            bot_id=me.id,
        )
        history.append((message.from_user.id, now, reply_user))
        cutoff = now - timedelta(seconds=45)
        context.bot_data["fight_jabs"][chat.id] = [
            item for item in history if item[1] >= cutoff
        ]
        if pair:
            holds = context.bot_data.get("fight_hold", {}).get(chat.id, {})
            if pair_on_hold(holds.get(pair), now):
                return
            await _break_fight(context, message, pair)
            return

    if insult_is_for_bot(
        message.text,
        mentioned=mentioned,
        is_reply_to_bot=reply_to_bot,
        last_spoke=last_spoke,
        now=now,
    ):
        line = await _comeback(context, message.text)
        if line:
            await _deliver(message, line)
            _mark_spoke(context, chat.id, line)
        return

    if is_ping(message.text) and (mentioned or reply_to_bot or chat.type == "private"):
        await _deliver(message, "Живой. Говори.")
        _mark_spoke(context, chat.id, "Живой. Говори.")
        return

    question = message.text
    if username:
        question = question.replace(f"@{me.username}", "").replace(f"@{username}", "")
    talk = _dialogue(context, chat.id)
    user_id = message.from_user.id if message.from_user else 0
    in_talk = bool(
        user_id
        and talk.accepts(
            user_id,
            message.text,
            now,
            mentioned=mentioned,
            reply_to_bot=reply_to_bot,
        )
    )
    thread = ""
    if in_talk and user_id:
        talk.add(user_id, cleaned, now)
        thread = talk.text()
    answered = should_answer(
        chat_type=chat.type,
        text=message.text,
        bot_username=username,
        is_reply_to_bot=reply_to_bot,
        mentioned=mentioned,
    ) or follows_bot(message.text, last_spoke, now) or in_talk
    chiming = not answered and should_chime(
        chat_type=chat.type,
        text=message.text,
        muted=False,
        last_chime=last_chime,
        now=now,
    )
    if not answered and not chiming:
        return
    try:
        spoken = await _speak(message, question, chime=chiming, thread=thread)
    except Exception:
        log.warning("answer failed chat=%s", chat.id)
        return
    if spoken:
        _mark_spoke(context, chat.id, spoken)
    if chiming:
        await store.mark_chime(chat.id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN required", file=sys.stderr)
        sys.exit(1)
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(ChatMemberHandler(on_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(allowed_updates=["message", "my_chat_member"])


if __name__ == "__main__":
    main()

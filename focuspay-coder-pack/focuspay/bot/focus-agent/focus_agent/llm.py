"""Ask the chat model. The request is the thread, plus project notes only when asked."""

from __future__ import annotations

import socket
import ssl
import sys

import aiohttp

from focus_agent.config import (
    EXCHANGE_BACKEND,
    JOURNAL_PATH,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    VOICE_PATH,
)

_SYSTEM = """Ты — свой в чате пользователей FocusPay. Коротко, только по-русски, без иероглифов, без канцелярита и без «конечно, я помогу». Не строй из себя центр комнаты.

Факты только из заметок проекта или из блока «Интернет», если он про тот же предмет. Чужие игры и вики не пересказывай. Если брал из интернета — дай ссылку. Нет источника — скажи, что не нашёл, и не выдумывай.

Клички на комнату не вешай и старую тему на новую не переноси. Карты, пароли и внутренние адреса не называй. Список участников чата не собирай и не выдумывай: таких данных у тебя нет. Выплаты, реквизиты и кабинет оператора — не твоя работа.

Тон в контексте — только манера. Это не сайт, не источник и не ссылка. Ссылку давай только если она есть в блоке «Интернет»."""

_THREAD = """Ниже нитка. Тема — только последняя реплика человека, не то, о чём говорили раньше.
Короткая реплика вроде «че», «бля», «ахах» — это не путаница. Не переспрашивай, не исправляй слова, не пиши «поясни» и «что значит».
Не обзывай людей и не называй комнату сонями, даже если выше кто-то писал, что спит.
Если последняя реплика просит криминальный способ — одно слово ТИХО. Способ не пиши.
Только если в нитке человек сам себе противоречит длинными фразами — одной фразой поймай это и задай один вопрос. Иначе ответь по теме или ТИХО."""

_CHIME = """Одна короткая реплика по-русски, только по их словам. Ни одного иероглифа.
Не про себя, без позы и без морали. Чужое «как дела» и приветствие — одно слово ТИХО.
Не приписывай проблемы, настроение, ночь, погоду и советы, которых в репликах нет.
Без имени. Если добавить нечего — одно слово ТИХО."""

_COMEBACK = """Ответь на грубость одной фразой по-русски.
Без мата, без кличек, без слова «орёл». Не оправдывайся и не повторяй его слова.
Бей в эго спокойно: выверни смысл, задай вопрос, после которого ему придётся объясняться, или согласись так, что это станет смешным.
Одно или два коротких предложения. Каждый раз другие слова.
Если ниже есть приём из интернета — возьми ход, не копируй текст."""


def _read(path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def retrieved_notes(query: str) -> str:
    """Project notes only. Used to decide whether the question still needs the web."""
    try:
        backend = str(EXCHANGE_BACKEND)
        if backend not in sys.path:
            sys.path.append(backend)
        import ops_ai_rag

        chunks = ops_ai_rag.retrieve(query, limit=4)
        return ops_ai_rag.format_context(chunks, max_chars=3500)
    except Exception:
        return ""


def project_context(query: str) -> tuple[str, str]:
    """Full prompt context, and the project-notes slice used to decide on web search."""
    voice = _read(VOICE_PATH, 1500)
    journal = _read(JOURNAL_PATH, 2500)
    found = retrieved_notes(query)
    parts = []
    if voice:
        parts.append("Тон, не цитировать:\n" + voice)
    if journal:
        parts.append("Что уже говорили в чате:\n" + journal)
    if found:
        parts.append("# Заметки\n" + found)
    return "\n\n".join(parts), found


def messages_for(
    question: str,
    recent: list[str],
    context: str,
    *,
    chime: bool = False,
    thread: str = "",
) -> list[dict[str, str]]:
    history = "\n".join(f"- {line}" for line in recent[-12:])
    user = question.strip()
    if thread:
        user = f"Нитка:\n{thread.strip()}\n\nСейчас:\n{user}"
    elif history:
        user = f"Последние реплики чата:\n{history}\n\nВопрос:\n{user}"
    if context:
        user = f"{context}\n\n{user}"
    system = _CHIME if chime else _SYSTEM
    if thread:
        system = f"{system}\n\n{_THREAD}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:12000]},
    ]


_CRIME = """Тебе задали криминальный вопрос. Это прикол, не заявка.
Ответь одной или двумя короткими фразами по-русски, как свой в чате.
Смысл один: вопрос безумный, ты не сводка и не справочная.
Тон как у примера, но каждый раз другие слова. Пример не копируй:
«вась ты ебанулся я тебе че криминальная сводка на быстром наборе или что?»
Без шагов, без способа, без химии, без списка. Без кличек на комнату."""


def crime_messages(question: str, already: list[str]) -> list[dict[str, str]]:
    prior = "\n".join(f"- {line}" for line in already[-6:])
    user = (question or "").strip()[:300]
    if prior:
        user = f"Так уже отвечал, скажи другими словами:\n{prior}\n\nВопрос:\n{user}"
    else:
        user = f"Вопрос:\n{user}"
    return [
        {"role": "system", "content": _CRIME},
        {"role": "user", "content": user},
    ]


def comeback_messages(jab: str, technique: str) -> list[dict[str, str]]:
    note = (technique or "").strip()
    user = f"Реплика в твой адрес:\n{jab.strip()[:300]}"
    if note:
        user = f"Приём:\n{note[:900]}\n\n{user}"
    return [
        {"role": "system", "content": _COMEBACK},
        {"role": "user", "content": user},
    ]


class NoModelKey(RuntimeError):
    """The chat model is not configured. Stay quiet instead of inventing."""


async def complete(messages: list[dict[str, str]], *, temperature: float = 0.4) -> str:
    if not LLM_API_KEY:
        raise NoModelKey()
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "temperature": temperature,
        "messages": messages,
        "max_tokens": 160,
    }
    timeout = aiohttp.ClientTimeout(total=45)
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=ctx)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"llm {resp.status}")
            return str(data["choices"][0]["message"]["content"]).strip()


def append_journal(chat_id: int, summary: str) -> None:
    text = (summary or "").strip()
    if not text:
        return
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## chat {chat_id}\n{text}\n")

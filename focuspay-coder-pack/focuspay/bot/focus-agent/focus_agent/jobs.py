"""Fold old lines into short notes. Once a day, report to the admin group.

The user chat does not get that report. Every three days it gets one fixed question.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from focus_agent import config
from focus_agent.llm import append_journal, complete
from focus_agent.redact import redact
from focus_agent.reports import IDEA_ASK, QUIET_REPORT, admin_report
from focus_agent import store
from focus_agent.triggers import invents_absent, is_horoscope, sticks_to_topic

log = logging.getLogger("focus-agent.jobs")

_FOLD_EVERY_SEC = 30 * 60
_OUTREACH_EVERY_SEC = 30 * 60
_MIN_LINES = 3

_REPORT_SYSTEM = (
    "Отчёт админу за сутки по заметкам чата. Формат строго такой:\n"
    "Отчёт за сутки\n\n"
    "Было:\n"
    "— ...\n\n"
    "Идеи:\n"
    "— ...\n\n"
    "Имена, карты и суммы чужих платежей не пиши. "
    "Идею пиши только если её сказали люди в заметках. Не выдумывай. "
    "Если идей не было, во втором блоке одна строка: — Идей не было."
)


async def fold_once() -> None:
    rows = await store.lines_ready_to_fold(3)
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[int(row["chat_id"])].append(row)
    for chat_id, lines in grouped.items():
        if len(lines) < _MIN_LINES:
            continue
        blob = "\n".join(str(line["body"]) for line in lines)[:6000]
        try:
            summary = await complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Сожми реплики чата пользователей в 3–5 коротких строк по-русски: "
                            "о чём сегодня говорили. Без карт, сумм и имён. "
                            "Если сути нет, ответь одним словом ПУСТО."
                        ),
                    },
                    {"role": "user", "content": blob},
                ],
                temperature=0.2,
            )
        except Exception:
            log.warning("fold failed chat=%s", chat_id)
            continue
        summary = redact(summary)
        ids = [int(line["id"]) for line in lines]
        if (
            not summary
            or "ПУСТО" in summary.upper()
            or is_horoscope(summary)
            or invents_absent(summary, blob)
            or not sticks_to_topic(summary, blob)
        ):
            await store.drop_lines(ids)
            log.info("drop fold chat=%s", chat_id)
            continue
        await store.save_summary(chat_id, summary, ids)
        append_journal(chat_id, summary)
        log.info("folded chat=%s lines=%s", chat_id, len(lines))


async def compress_loop() -> None:
    while True:
        try:
            await fold_once()
        except Exception:
            log.exception("fold loop")
        await asyncio.sleep(_FOLD_EVERY_SEC)


async def report_once(bot: Any) -> None:
    """One note to the /dash group. Nothing is posted back into the user chat."""
    reports_id = int(config.REPORTS_GROUP_ID or 0)
    if not reports_id:
        log.info("report skipped: TELEGRAM_REPORTS_GROUP_ID unset")
        return
    chats = await store.chats_due_report(reports_id)
    if not chats:
        return
    due_ids = [int(row["chat_id"]) for row in chats]
    chunks = []
    for chat_id in due_ids:
        text = redact(await store.fresh_material(chat_id))
        if text:
            chunks.append(text)
    material = "\n".join(chunks).strip()
    if not material:
        body = QUIET_REPORT
    else:
        try:
            raw = await complete(
                [
                    {"role": "system", "content": _REPORT_SYSTEM},
                    {"role": "user", "content": material[:6000]},
                ],
                temperature=0.2,
            )
        except Exception:
            log.warning("report model failed")
            return
        body = admin_report(redact(raw), material)
    try:
        await bot.send_message(reports_id, body[:3500])
    except Exception:
        log.warning("report send failed")
        return
    for chat_id in due_ids:
        await store.mark_daily(chat_id)
    log.info("report sent chats=%s", len(due_ids))


async def ideas_once(bot: Any) -> None:
    """Ask user groups for ideas. The reports group and a muted chat stay quiet."""
    reports_id = int(config.REPORTS_GROUP_ID or 0)
    chats = await store.chats_due_idea(reports_id)
    for row in chats:
        chat_id = int(row["chat_id"])
        if chat_id == reports_id or chat_id >= 0:
            continue
        if await store.is_muted(chat_id):
            continue
        try:
            await bot.send_message(chat_id, IDEA_ASK)
        except Exception:
            log.warning("idea ask failed chat=%s", chat_id)
            continue
        await store.mark_idea(chat_id)
        log.info("idea ask chat=%s", chat_id)


async def outreach_loop(app: Any) -> None:
    while True:
        try:
            await report_once(app.bot)
            await ideas_once(app.bot)
        except Exception:
            log.exception("outreach loop")
        await asyncio.sleep(_OUTREACH_EVERY_SEC)

"""Admin daily report and the fixed question for ideas.

The user chat does not get a recap. The report goes to the /dash group.
The idea question is a fixed text, so the model cannot invent a percent.
"""

from __future__ import annotations

import re

from focus_agent.triggers import has_foreign_script, invents_absent, is_horoscope, sticks_to_topic

QUIET_REPORT = "За сутки тихо. Идей не было."

IDEA_ASK = (
    "Ребята, админ поставил задачу: собрать, чего вы хотите от нас дальше.\n\n"
    "Напишите сюда идею — сервис, услугу, что угодно в интернете. "
    "Если она нам зайдёт, можем сделать.\n\n"
    "Если идею возьмём и она начнёт приносить деньги, вам пойдёт процент с прибыли по ней. "
    "Сколько именно, скажет админ, когда возьмёт идею в работу."
)

_IDEAS = re.compile(r"\n\s*Идеи:\s*\n", re.IGNORECASE)
_NONE = re.compile(r"идей не было", re.IGNORECASE)


def is_client_group(chat_id: int, reports_id: int) -> bool:
    """A user group. Private chats and the reports group are not asked for ideas."""
    try:
        cid = int(chat_id)
        reports = int(reports_id or 0)
    except (TypeError, ValueError):
        return False
    if cid >= 0:
        return False
    return not reports or cid != reports


def admin_report(raw: str | None, material: str | None) -> str:
    """A report for the admin. An empty day, or an invented idea, does not grow a wish."""
    if not (material or "").strip():
        return QUIET_REPORT
    text = (raw or "").strip()
    if (
        not text
        or text.upper() == "ТИХО"
        or is_horoscope(text)
        or has_foreign_script(text)
        or invents_absent(text, material)
    ):
        return QUIET_REPORT
    match = _IDEAS.search(text)
    if match:
        happened, ideas = text[: match.start()].strip(), text[match.end() :].strip()
    else:
        happened, ideas = text, ""
    if not happened or not sticks_to_topic(happened, material):
        return QUIET_REPORT
    if not ideas or _NONE.search(ideas) or not sticks_to_topic(ideas, material) or invents_absent(ideas, material):
        ideas = "— Идей не было."
    return f"{happened}\n\nИдеи:\n{ideas}"[:3500]

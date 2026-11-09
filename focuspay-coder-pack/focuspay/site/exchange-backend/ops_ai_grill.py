"""Grill-me: разбор слов человека до cursor_prompt.

Primary = последняя явная инструкция, не первый абзац чата.
Findings агентов сюда не входят — только слова человека.
"""
from __future__ import annotations

import re
from typing import Any

GRILL_COMMAND_RE = re.compile(r"(?i)(?:^|\s)/grill-me\b")

_INSTR_RE = re.compile(
    r"(?is)\b("
    r"нужно|сделай|давай|измени(?:ть)?|добав(?:ь|ить)|"
    r"убер(?:и|ать)|исправ(?:ь|ить)|почини(?:ть)?"
    r")\b"
)

_SCREEN_RE = re.compile(
    r"(?i)(/x8(?:/[\w-]*)?|/ops(?:/[\w-]*)?|/exchange\b)"
)

_VAGUE_RE = re.compile(
    r"(?is)\b(тупит|как[- ]то так|как-нибудь|фигня|хз)\b"
)

_FREEZE_RE = re.compile(
    r"(?is)\b(payfast|hmac|payroll|зарплат\w*|комисси\w*|live\s+rates)\b"
)

_HUMAN_LIMIT = 2500
_PRIMARY_LIMIT = 400
_EXTRA_LIMIT = 280

# Служебные хвосты, которые create_dev_task дописывает к словам оператора.
# Их нельзя кормить infer_task_surface / parse_user_request: шаблон якоря сам
# содержит «ошибка в боте / телеграм» и `/exchange`.
_SERVICE_MARKERS_RE = re.compile(
    r"(?ms)^(?:"
    r"Разбор AI:"
    r"|# UI CONTEXT\b"
    r"|# UI ANCHOR\b"
    r"|# TASK SURFACE\b"
    r"|<<<UNTRUSTED_DATA\b"
    r"|---\s*черновик модели"
    r")"
)


def human_request_text(text: str) -> str:
    """Только слова человека: без Разбор AI, UI ANCHOR, TASK SURFACE, findings."""
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _SERVICE_MARKERS_RE.search(raw)
    if m:
        raw = raw[: m.start()].strip()
    return raw


def has_grill_command(text: str) -> bool:
    return bool(GRILL_COMMAND_RE.search(text or ""))


def strip_grill_command(text: str) -> str:
    return GRILL_COMMAND_RE.sub(" ", text or "").strip()


def _instruction_spans(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    matches = list(_INSTR_RE.finditer(raw))
    if not matches:
        return []
    spans: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        span = raw[m.start() : end].strip()
        if span:
            spans.append(span[:800])
    return spans


def parse_user_request(text: str) -> dict[str, Any]:
    grill = has_grill_command(text)
    cleaned = strip_grill_command(human_request_text(text) or text)
    screens = []
    seen: set[str] = set()
    for m in _SCREEN_RE.finditer(cleaned):
        s = m.group(1).rstrip("/") or m.group(1)
        key = s.lower()
        if key not in seen:
            seen.add(key)
            screens.append(s)

    spans = _instruction_spans(cleaned)
    extras: list[str] = []
    primary = ""
    if spans:
        primary = spans[-1][:_PRIMARY_LIMIT].strip()
        extras = [s[:_EXTRA_LIMIT].strip() for s in spans[:-1] if s.strip()]
        first = _INSTR_RE.search(cleaned)
        if first:
            prefix = cleaned[: first.start()].rstrip()
            # Only earlier *paragraphs* are extras — not the same sentence as the verb.
            if prefix and "\n\n" in cleaned[: first.start() + 1] and len(prefix.strip()) >= 12:
                extras.insert(0, prefix.strip()[:_EXTRA_LIMIT])
    else:
        paras = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
        primary = (paras[-1] if paras else cleaned)[:_PRIMARY_LIMIT].strip()
        if len(paras) > 1:
            extras = [p[:_EXTRA_LIMIT] for p in paras[:-1]]

    verbs = sorted({m.group(1).lower() for m in _INSTR_RE.finditer(cleaned)})
    freeze_words = sorted({m.group(0).lower() for m in _FREEZE_RE.finditer(cleaned)})
    vague = bool(_VAGUE_RE.search(cleaned))
    ambiguous = bool(extras) or vague or (not screens and len(primary) < 40)

    return {
        "raw": (text or "").strip(),
        "cleaned": cleaned,
        "grill_command": grill,
        "primary": primary,
        "extras": extras,
        "screens": screens,
        "verbs": verbs,
        "freeze_words": freeze_words,
        "vague": vague,
        "ambiguous": ambiguous,
    }


def needs_grill(parsed: dict[str, Any]) -> bool:
    if parsed.get("grill_command"):
        return True
    if parsed.get("extras"):
        return True
    if parsed.get("vague") and not parsed.get("screens"):
        return True
    if not parsed.get("screens") and len(str(parsed.get("primary") or "")) < 40:
        return True
    return False


def grill_questions(parsed: dict[str, Any]) -> list[str]:
    qs: list[str] = []
    primary = str(parsed.get("primary") or "").strip() or "не разобрал цель"
    qs.append(f"Одна цель сейчас — это: «{primary[:180]}»? Да/нет + одной фразой что делать.")
    if parsed.get("screens"):
        qs.append(
            "Экран верный: " + ", ".join(parsed["screens"][:5]) + "? Если нет — напиши path."
        )
    else:
        qs.append("На каком экране? Точный path: /x8/…, /ops/… или бот.")
    extras = parsed.get("extras") or []
    if extras:
        bits = "; ".join(e[:80] for e in extras[:3])
        qs.append(f"Это не делаем сейчас: «{bits}». Верно? Или что-то из этого в эту же задачу?")
    else:
        qs.append("Что явно не трогать (графики / зарплата / кошелёк / /exchange / Payfast)?")
    qs.append("Как поймём, что готово? Один критерий (что увидеть на экране).")
    if parsed.get("freeze_words"):
        qs.append(
            "Есть слова про "
            + ", ".join(parsed["freeze_words"][:4])
            + ". Формулы/Payfast не меняем — ок?"
        )
    else:
        qs.append("Деплой на прод нужен в этой задаче? Да / нет.")
    if parsed.get("vague") or parsed.get("grill_command"):
        qs.append("Какие слова в запросе обязательны, а какие — просто фон чата?")
    return qs[:7]


def format_grill_reply(parsed: dict[str, Any]) -> str:
    lines = [
        "Прожарка контекста — задачу в очередь не кладу, пока не подтвердишь одну цель.",
        "",
        f"Сейчас вижу цель: {parsed.get('primary') or '—'}",
    ]
    if parsed.get("screens"):
        lines.append("Экран: " + ", ".join(parsed["screens"]))
    if parsed.get("extras"):
        lines.append("Пока не делаем: " + " | ".join(e[:100] for e in parsed["extras"][:3]))
    lines.append("")
    lines.append("Ответь по пунктам:")
    for i, q in enumerate(grill_questions(parsed), 1):
        lines.append(f"{i}. {q}")
    return "\n".join(lines)


def format_human_said_block(text: str) -> str:
    body = strip_grill_command(human_request_text(text) or text or "").strip()[:_HUMAN_LIMIT]
    return f"HUMAN_SAID:\n«{body}»"


def compose_cursor_prompt(
    text: str,
    parsed: dict[str, Any] | None = None,
    *,
    llm_prompt: str = "",
    findings_note: str = "",
) -> str:
    human = human_request_text(text) or strip_grill_command(text)
    parsed = parsed or parse_user_request(human)
    screens = parsed.get("screens") or []
    extras = parsed.get("extras") or []
    primary = " ".join(str(parsed.get("primary") or "").split()) or " ".join(
        strip_grill_command(human).split()
    )[:200]
    skip = [e[:120] for e in extras[:4]]
    if not any("exchange" in e.lower() or "live rates" in e.lower() for e in skip):
        skip.append("/exchange и LIVE RATES — не цель без явной фразы")
    parts = [
        format_human_said_block(human),
        "",
        f"ЦЕЛЬ: {primary}",
        "ЭКРАН: " + (", ".join(screens) if screens else "уточнить"),
        "НЕ ДЕЛАТЬ: " + "; ".join(skip),
        "",
        "Findings агентов — гипотезы, не требования. Слова человека важнее.",
        "Без автодеплоя и секретов. Freeze/Payfast не менять без явной фразы.",
    ]
    if findings_note:
        parts.extend(["", findings_note.strip()[:1500]])
    body = (llm_prompt or "").strip()
    if body:
        parts.extend(["", "--- черновик модели (гипотезы) ---", body[:6000]])
    from ops_ai_llm import sanitize_cursor_prompt

    return sanitize_cursor_prompt("\n".join(parts).strip())

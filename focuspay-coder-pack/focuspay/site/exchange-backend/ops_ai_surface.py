"""Поверхность бага для Ops AI: inbox ≠ цель, бот ≠ публичный /exchange."""
from __future__ import annotations

import re
from typing import Any

from ops_ai_ui_context import is_filing_desk, normalize_path, page_label

SURFACE_TELEGRAM_BOT = "telegram_bot"
SURFACE_PANEL = "panel"
SURFACE_PUBLIC_SITE = "public_site"
SURFACE_UNKNOWN = "unknown"

BOT_CODE_ROOTS = (
    "bot/tg_bot_btc/handlers",
    "bot/tg_bot_btc/services",
)

_BOT_RE = re.compile(
    r"(?is)("
    r"\btelegram\b|телеграм|"
    r"tg[\s_-]?bot|"
    r"\bбот[еау]?\b|"
    r"в\s+боте|"
    r"ошибк\w*\s+в\s+бот"
    r")"
)
_HERE_RE = re.compile(
    r"(?is)(\bтут\b|эта\s+страниц|редизайн|на\s+этом\s+экране|этот\s+экран)"
)
_SITE_RE = re.compile(
    r"(?is)("
    r"/exchange\b|"
    r"\bна\s+сайте\b|"
    r"публичн\w+\s+сайт|"
    r"live\s+rates|"
    r"лендинг"
    r")"
)
_RATES_RE = re.compile(r"(?is)(курс\w*|rates?\b|rapira)")

_DROP_HINTS_FOR_BOT = (
    "/ops/dev-requests",
    "operatordevrequests",
    "adminaitasks",
    "/x8/ai-tasks",
    "src/pages/exchange",
    "focussite/frontend/src/pages",
)


def looks_like_telegram_bot(text: str) -> bool:
    return bool(_BOT_RE.search(text or ""))


def looks_like_public_site(text: str) -> bool:
    t = text or ""
    if looks_like_telegram_bot(t):
        return False
    return bool(_SITE_RE.search(t))


def infer_task_surface(
    request_text: str,
    ui: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Цель задачи: что чинить. Path inbox не является поверхностью бага.

    Анализ — только слова оператора. Разбор AI / UI ANCHOR / TASK SURFACE
    отрезаются: шаблон якоря сам содержит «ошибка в боте» и `/exchange`.
    """
    try:
        from ops_ai_grill import human_request_text

        text = human_request_text(request_text) or ""
    except Exception:
        text = str(request_text or "").strip()
    path = normalize_path(str((ui or {}).get("path") or "").strip())
    filing = bool(path and is_filing_desk(path))
    real_ui = path if path and not filing else ""

    if looks_like_telegram_bot(text):
        return _surface(
            SURFACE_TELEGRAM_BOT,
            code_roots=list(BOT_CODE_ROOTS),
            filing_path=path if filing else "",
            ui_path=real_ui,
            include_live_rates=False,
            notes=(
                "Запрос про Telegram-бот. Чинить `bot/tg_bot_btc` "
                "(handlers/exchange_flow, services/rates_api). "
                "Inbox и публичный /exchange не цель. LIVE RATES сайта — справочник, не баг-экран."
            ),
        )

    if looks_like_public_site(text):
        return _surface(
            SURFACE_PUBLIC_SITE,
            code_roots=["focussite/frontend/src/pages", "site/exchange-backend/routers"],
            filing_path=path if filing else "",
            ui_path=real_ui or "/exchange",
            include_live_rates=True,
            notes="Явный запрос про публичный сайт. LIVE RATES можно использовать как справочник.",
        )

    if real_ui and (_HERE_RE.search(text) or path.startswith("/ops/") or path.startswith("/x8/")):
        return _surface(
            SURFACE_PANEL,
            code_roots=_panel_code_roots(real_ui),
            filing_path="",
            ui_path=real_ui,
            include_live_rates=True,
            notes=(
                f"Реальный экран панели `{real_ui}` ({page_label(real_ui)}). "
                "Не подменяй на /exchange из-за LIVE RATES."
            ),
        )

    return _surface(
        SURFACE_UNKNOWN,
        code_roots=[],
        filing_path=path if filing else "",
        ui_path=real_ui,
        include_live_rates=not filing,
        notes=(
            "Inbox /ops/dev-requests и /x8/ai-tasks — очередь подачи, не баг-экран. "
            "LIVE RATES / /exchange не подставлять без явного «на сайте». "
            "Если речь про курсы клиенту — сначала Telegram-бот `bot/tg_bot_btc`."
            if filing
            else "Уточни поверхность по тексту. LIVE RATES не делает целью /exchange."
        ),
    )


def surface_prompt_block(surface: dict[str, Any] | None) -> str:
    s = surface or infer_task_surface("")
    kind = str(s.get("surface") or SURFACE_UNKNOWN)
    lines = [
        "# TASK SURFACE (что чинить; не путать с кнопкой «создать задачу»)",
        f"- surface: {kind}",
    ]
    ui_path = str(s.get("ui_path") or "").strip()
    filing = str(s.get("filing_path") or "").strip()
    if kind == SURFACE_TELEGRAM_BOT:
        lines.append("- цель: Telegram-бот")
        lines.append("- код: `bot/tg_bot_btc/handlers`, `bot/tg_bot_btc/services`")
        lines.append("- не цель: `/ops/dev-requests`, `/x8/ai-tasks`, публичный `/exchange`, LIVE RATES сайта")
    elif kind == SURFACE_PANEL:
        lines.append(f"- цель: экран панели `{ui_path}` ({page_label(ui_path)})")
        lines.append("- не цель: публичный `/exchange` только из-за LIVE RATES")
    elif kind == SURFACE_PUBLIC_SITE:
        lines.append("- цель: публичный сайт (явный запрос)")
        lines.append("- LIVE RATES — справочник этого сайта, не подмена Telegram-бота")
    else:
        lines.append("- цель: по тексту оператора, не по inbox-path")
        lines.append("- не цель: `/ops/dev-requests`, `/x8/ai-tasks`, `/exchange` без явной фразы про сайт")
    if filing:
        lines.append(f"- filed_from (inbox, не баг): `{filing}`")
    if ui_path and kind != SURFACE_PUBLIC_SITE:
        lines.append(f"- ui_path: `{ui_path}`")
    for root in s.get("code_roots") or []:
        lines.append(f"- code_root: `{root}`")
    notes = str(s.get("notes") or "").strip()
    if notes:
        lines.append(f"- notes: {notes}")
    if _RATES_RE.search(notes) or kind == SURFACE_TELEGRAM_BOT:
        lines.append(
            "- курсы в боте: `bot/tg_bot_btc/services/rates_api.py`, "
            "`bot/tg_bot_btc/handlers/exchange_flow.py`"
        )
    return "\n".join(lines)


def rag_query_for_surface(request_text: str, surface: dict[str, Any] | None) -> str:
    try:
        from ops_ai_grill import human_request_text

        text = human_request_text(request_text)
    except Exception:
        text = str(request_text or "").strip()
    s = surface or {}
    extra = " ".join(str(x) for x in (s.get("code_roots") or []))
    if s.get("surface") == SURFACE_TELEGRAM_BOT:
        extra += " bot/tg_bot_btc rates_api exchange_flow USER_RATES_UNAVAILABLE rapira frozen"
    return f"{text} {extra}".strip()


def filter_file_hints(hints: list[str], surface: dict[str, Any] | None) -> list[str]:
    raw = [str(h).strip() for h in (hints or []) if str(h).strip()]
    if (surface or {}).get("surface") != SURFACE_TELEGRAM_BOT:
        return raw[:12]
    out: list[str] = []
    for h in raw:
        low = h.lower()
        if any(tok in low for tok in _DROP_HINTS_FOR_BOT):
            continue
        if low.rstrip("/") == "/exchange":
            continue
        out.append(h)
    for root in BOT_CODE_ROOTS:
        if root not in out:
            out.append(root)
    return out[:12]


def _panel_code_roots(path: str) -> list[str]:
    p = normalize_path(path)
    if p.startswith("/x8"):
        return ["focussite/frontend/src/panel/admin"]
    if p.startswith("/ops"):
        return ["focussite/frontend/src/panel/operator"]
    return ["focussite/frontend/src/panel"]


def _surface(
    kind: str,
    *,
    code_roots: list[str],
    filing_path: str,
    ui_path: str,
    include_live_rates: bool,
    notes: str,
) -> dict[str, Any]:
    return {
        "surface": kind,
        "code_roots": list(code_roots),
        "filing_path": filing_path,
        "ui_path": ui_path,
        "include_live_rates": bool(include_live_rates),
        "notes": notes,
    }

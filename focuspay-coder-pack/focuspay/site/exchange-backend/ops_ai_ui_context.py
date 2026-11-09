"""Контекст экрана панели (оператор / админ) для Ops AI (read-only)."""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("ops_ai_ui_context")

_PAGE_LABELS = {
    # Operator
    "/ops": "Дашборд оператора",
    "/ops/": "Дашборд оператора",
    "/ops/orders": "Список заявок",
    "/ops/create": "Создание заявки",
    "/ops/chat": "Чаты с клиентами",
    "/ops/payroll": "Зарплата",
    "/ops/promo": "Промо и скидки",
    "/ops/dev-requests": "Задачи AI / разработчикам",
    "/ops/shifts": "Смены",
    "/ops/reviews": "Отзывы",
    "/ops/broadcast": "Рассылка",
    "/ops/profile": "Профиль оператора",
    "/ops/antispam": "Антиспам в чатах",
    "/ops/ai": "AI-помощник оператора",
    # Admin
    "/x8": "Аналитика админки",
    "/x8/": "Аналитика админки",
    "/x8/orders": "Админ · заявки",
    "/x8/users": "Админ · пользователи",
    "/x8/chat": "Админ · чаты",
    "/x8/ai-tasks": "Админ · очередь AI-задач",
    "/x8/sticker-ai": "Админ · Sticker AI (брендовые стикеры)",
    "/x8/stats": "Админ · аналитика (финансы)",
    "/x8/balances": "Админ · балансы",
    "/x8/pricing": "Админ · цены и комиссии",
    "/x8/payroll": "Админ · зарплаты",
    "/x8/operator-payroll": "Админ · выплаты операторам",
    "/x8/expenses": "Админ · расходы",
    "/x8/external": "Админ · внешние обмены",
    "/x8/usdt": "Админ · выпуск USDT",
    "/x8/operators": "Админ · операторы",
    "/x8/shifts": "Админ · смены",
    "/x8/promo": "Админ · промокоды",
    "/x8/focus-lucky": "Админ · FocusLucky",
    "/x8/partners": "Админ · партнёры",
    "/x8/reviews": "Админ · отзывы",
    "/x8/broadcast": "Админ · рассылка",
    "/x8/security": "Админ · безопасность",
    "/x8/settings": "Админ · настройки",
}

_ORDER_RE = re.compile(r"^[A-Z0-9_-]{4,64}$", re.I)

# Path allowlist for UI context (deny-by-default outside /ops|/x8 panel routes).
_PATH_ALLOW_EXACT = frozenset(_PAGE_LABELS.keys())
_PATH_ALLOW_PREFIXES = (
    "/ops/",
    "/x8/",
)

# Очередь подачи задачи — не баг-экран. Не якорить cursor_prompt на эти path.
FILING_DESK_PATHS = frozenset(
    {
        "/ops/dev-requests",
        "/x8/ai-tasks",
        "/ops/ai",
    }
)
_SEARCH_ALLOW_KEYS = frozenset(
    {
        "id",
        "status",
        "action",
        "order",
        "order_id",
        "tab",
        "page",
    }
)
_HINT_MAX = 500


class UiContextValidationError(ValueError):
    pass


def is_filing_desk(path: str) -> bool:
    """True если path — inbox создания/ревью AI-задач, а не экран бага."""
    p = normalize_path(path)
    if not p:
        return False
    if p in FILING_DESK_PATHS:
        return True
    if p.startswith("/x8/ai-tasks/") or p.startswith("/ops/dev-requests/"):
        return True
    return False


def is_path_allowed(path: str) -> bool:
    p = normalize_path(path)
    if not p:
        return False
    if p in _PATH_ALLOW_EXACT:
        return True
    if p.startswith("/ops/client/") and re.match(r"^/ops/client/\d+/?$", p):
        return True
    if any(p.startswith(pref) for pref in _PATH_ALLOW_PREFIXES):
        # Reject path traversal / odd schemes
        if ".." in p or "://" in p or "\\" in p:
            return False
        return True
    return False


def sanitize_search(search: str | None) -> str:
    """Keep only allowlisted query keys; drop PII-heavy values beyond short ids."""
    from urllib.parse import parse_qs, urlencode

    raw = str(search or "").strip().lstrip("?")
    if not raw:
        return ""
    qs = parse_qs(raw, keep_blank_values=False)
    clean: dict[str, str] = {}
    for k, vals in qs.items():
        key = str(k).strip().lower()
        if key not in _SEARCH_ALLOW_KEYS:
            continue
        val = str((vals or [""])[0] or "").strip()[:64]
        if not val:
            continue
        if key in ("order", "order_id") and not _ORDER_RE.match(val):
            continue
        if key == "id" and not re.match(r"^\d{1,12}$", val):
            continue
        if key == "action" and val.lower() not in ("approve", "reject", "done", "view"):
            continue
        clean[key] = val
    return urlencode(clean)


def validate_ui_context(
    ui: dict[str, Any] | None,
    *,
    require_path: str | None = None,
    require_hint_contains: str | None = None,
) -> dict[str, Any]:
    """Validate + normalize UiContextBody via allowlist. Raises UiContextValidationError."""
    if not ui:
        if require_path:
            raise UiContextValidationError("ui_context_required")
        return {}
    path = normalize_path(str(ui.get("path") or "").strip())
    if path and not is_path_allowed(path):
        raise UiContextValidationError(f"path_denied:{path}")
    if require_path and path != normalize_path(require_path):
        raise UiContextValidationError(f"path_mismatch:{path}")
    hint = str(ui.get("hint") or "").strip()[:_HINT_MAX]
    if require_hint_contains and require_hint_contains.lower() not in hint.lower():
        raise UiContextValidationError("hint_mismatch")
    title = str(ui.get("title") or "").strip()[:200]
    search = sanitize_search(ui.get("search"))
    order_id = str(ui.get("order_id") or "").strip().upper()
    if order_id and not _ORDER_RE.match(order_id):
        order_id = ""
    client_id = ui.get("client_id")
    try:
        client_id_i = int(client_id) if client_id is not None and str(client_id).strip() else None
    except (TypeError, ValueError):
        client_id_i = None
    out: dict[str, Any] = {}
    if path:
        out["path"] = path
    if search:
        out["search"] = search
    if title:
        out["title"] = title
    if hint:
        out["hint"] = hint
    if order_id:
        out["order_id"] = order_id
    if client_id_i is not None:
        out["client_id"] = client_id_i
    return out


def normalize_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p


def page_label(path: str) -> str:
    p = normalize_path(path) or "/ops"
    if p in _PAGE_LABELS:
        return _PAGE_LABELS[p]
    if p.startswith("/ops/client/"):
        return "Профиль клиента"
    if p.startswith("/ops/orders"):
        return "Заявки"
    if p.startswith("/x8/sticker-ai"):
        return "Админ · Sticker AI (брендовые стикеры)"
    if p.startswith("/x8/"):
        return f"Админ-панель · {p}"
    if p.startswith("/ops/"):
        return f"Панель оператора · {p}"
    return p


def ui_anchor_lines(ui: dict[str, Any] | None) -> list[str]:
    """Короткий жёсткий якорь экрана для triage/synthesis (без PII)."""
    if not ui:
        return []
    path = normalize_path(str(ui.get("path") or "").strip())
    hint = str(ui.get("hint") or "").strip()
    if not path and not hint:
        return []
    if path and is_filing_desk(path):
        lines = [
            "# UI CONTEXT (inbox — откуда подали задачу, НЕ баг-экран)",
            "Правило: /ops/dev-requests и /x8/ai-tasks — очередь заявок. Не делай их целью cursor_prompt.",
            "Цель бери из текста оператора (Telegram-бот / реальный экран /ops|/x8 / сайт).",
            "LIVE RATES — справочник сайта; не подменяй задачу на публичный /exchange.",
        ]
        lines.append(f"- filed_from: `{path}`")
        lines.append(f"- inbox: {page_label(path)}")
        if hint:
            lines.append(f"- hint: {hint[:500]}")
        return lines
    lines = [
        "# UI ANCHOR (источник правды про ЭКРАН задачи)",
        "Правило: если оператор сказал «тут / эта страница / редизайн» — цель = этот path/hint.",
        "Не подменяй экран на публичный /exchange только из-за блока LIVE RATES (курсы — справочник).",
        "Исключение: «ошибка в боте / телеграм» — цель `bot/tg_bot_btc`, не этот path.",
    ]
    if path:
        lines.append(f"- path: `{path}`")
        lines.append(f"- экран: {page_label(path)}")
    if hint:
        lines.append(f"- hint: {hint[:500]}")
    return lines


async def build_ui_context_block(ui: dict[str, Any] | None) -> str:
    if not ui:
        return ""
    from config import settings
    from privacy_redaction import pseudonym, redact_text

    try:
        ui = validate_ui_context(ui)
    except UiContextValidationError as e:
        logger.warning("ui context rejected: %s", e)
        return ""
    if not ui:
        return ""

    path = normalize_path(str(ui.get("path") or "").strip()) or "?"
    # search уже прошёл allowlist keys
    search = sanitize_search(ui.get("search"))
    title = redact_text(str(ui.get("title") or "").strip(), keep_short_ids=True)
    hint = redact_text(str(ui.get("hint") or "").strip(), keep_short_ids=True)
    order_id = str(ui.get("order_id") or "").strip().upper()
    client_id = ui.get("client_id")
    href = path  # не тащим raw search с потенциальным PII

    lines = ui_anchor_lines({"path": path if path != "?" else "", "hint": hint}) or [
        "# UI CONTEXT (экран панели прямо сейчас)",
        f"- path: `{href}`",
        f"- экран: {page_label(path)}",
    ]
    # Keep a stable section title even when anchor is used (not inbox).
    if lines and lines[0].startswith("# UI ANCHOR"):
        lines[0] = "# UI CONTEXT / ANCHOR (экран панели прямо сейчас)"
    if title:
        lines.append(f"- document.title: {title[:120]}")
    if order_id:
        lines.append(f"- order_id из UI: `{order_id}`")
    if client_id is not None and str(client_id).strip():
        # Deny-by-default: в LLM уходит псевдоним, не сырой Telegram/user id
        if bool(getattr(settings, "ops_ai_allow_ui_client_pii", False)):
            lines.append(f"- client_ref: `{pseudonym(client_id, prefix='client')}`")
        else:
            lines.append("- client_ref: [PRESENT]")
    if hint and not any(x.startswith("- hint:") or x.startswith("- подсказка фронта:") for x in lines):
        lines.append(f"- подсказка фронта: {hint[:500]}")

    # Подтянуть заявку, если есть id
    oid = order_id
    if not oid and search:
        from urllib.parse import parse_qs

        qs = parse_qs(search.lstrip("?"))
        raw = (qs.get("order") or qs.get("order_id") or [""])[0]
        oid = str(raw or "").strip().upper()
    if oid and _ORDER_RE.match(oid):
        snap = await _order_snapshot(oid)
        if snap:
            lines.append("## Открытая / указанная заявка")
            lines.append(snap)
        else:
            lines.append(f"(заявка `{oid}` в БД не найдена)")

    # Клиент из path /ops/client/123
    uid = client_id
    if uid is None:
        m = re.match(r"^/ops/client/(\d+)/?$", path)
        if m:
            uid = int(m.group(1))
    if uid is not None:
        try:
            uid_i = int(uid)
        except (TypeError, ValueError):
            uid_i = None
        if uid_i:
            csnap = await _client_snapshot(uid_i)
            if csnap:
                lines.append("## Клиент на экране")
                lines.append(csnap)

    if path != "?" and is_filing_desk(path):
        lines.append(
            "Это inbox подачи задачи, не баг-экран. Цель — из текста оператора "
            "(Telegram-бот / реальный /ops|/x8 / сайт). Не подменяй на /exchange из-за LIVE RATES."
        )
    else:
        lines.append(
            "Отвечай и планируй задачу с учётом этого экрана. Не выдумывай другой экран. "
            "Если в тексте «ошибка в боте / телеграм» — цель `bot/tg_bot_btc`."
        )
    return "\n".join(lines)


async def _client_snapshot(user_id: int) -> str | None:
    """Deny-by-default: без username/telegram/PII; только агрегаты статусов."""
    try:
        from config import settings
        from db import get_pool
        from privacy_redaction import pseudonym

        pool = await get_pool()
        async with pool.acquire() as conn:
            recent = await conn.fetch(
                """
                SELECT order_id, direction, crypto, status
                FROM orders
                WHERE user_id = $1
                ORDER BY created_at DESC NULLS LAST
                LIMIT 5
                """,
                user_id,
            )
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE user_id = $1",
                user_id,
            )
        ref = pseudonym(user_id, prefix="client")
        lines: list[str] = [f"- client_ref={ref}", f"- orders_count={int(cnt or 0)}"]
        if bool(getattr(settings, "ops_ai_allow_ui_client_pii", False)):
            lines.append("- note: raw PII flag enabled (ops_ai_allow_ui_client_pii)")
        if recent:
            lines.append("- последние заявки (без сумм/PII):")
            for o in recent:
                lines.append(
                    f"  · {o['order_id']} {o['direction']} {o['crypto']} {o['status']}"
                )
        return "\n".join(lines)
    except Exception as e:
        logger.warning("client snapshot: %s", e)
        return "- client_ref=[UNAVAILABLE]"


async def _order_snapshot(order_id: str) -> str | None:
    try:
        from db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT order_id, direction, crypto, status, created_at
                FROM orders WHERE order_id = $1
                """,
                order_id,
            )
        if not row:
            return None
        return (
            f"- order_id={row['order_id']} direction={row['direction']} "
            f"crypto={row['crypto']} status={row['status']}"
        )
    except Exception as e:
        logger.warning("order snapshot: %s", e)
        return None

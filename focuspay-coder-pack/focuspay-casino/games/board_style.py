"""Shared live-card skeleton for Telegram casino boards."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

PHASE_LABELS = {
    "collect": "Сбор ставок",
    "waiting_first": "Ждём первую ставку",
    "countdown": "Отсчёт старта",
    "ready": "Старт вот-вот",
    "delayed": "Старт задерживается, ждём сервер",
    "dealing": "Раздача",
    "dealing_1": "Раздача: первая карта…",
    "dealing_2": "Раздача: вторая карта…",
    "dealing_3": "Раздача: третья карта…",
    "hitting": "Ход игроков",
    "rolling": "Бросок",
    "bets_closed": "Ставки закрыты",
    "spinning": "Колесо крутится 🎡",
    "slowing": "Замедляется…",
    "reel": "Крутится",
    "finalists": "Финалисты",
    "scoring": "Считаем результат…",
    "settled": "Итог",
    "refunded": "Ставка возвращена (один игрок)",
}


def parse_iso(raw: object) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def seconds_until(raw: object, *, now: datetime | None = None) -> int | None:
    stamp = parse_iso(raw)
    if stamp is None:
        return None
    clock = now if now is not None else datetime.now(timezone.utc)
    return max(0, int((stamp - clock).total_seconds()))


def now_line(text: str | None) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body.startswith("Сейчас:"):
        return body
    return f"Сейчас: {body}"


def next_line(text: str | None) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body.startswith("Дальше:"):
        return body
    return f"Дальше: {body}"


def timer_line(
    snapshot: dict[str, Any] | None,
    *,
    spinning_statuses: Iterable[str] = ("locked", "spinning"),
    spinning_text: str = "Колесо крутится, ставки закрыты.",
    settled_status: str = "settled",
    settled_text: str | None = None,
    refunded_text: str | None = None,
    collect_key: str = "collect_seconds",
    collect_default: int = 25,
    waiting_template: str = "Ждём первую ставку. Окно ~{collect} с.",
    running_template: str = "До спина {left} с.",
    closes_key: str = "closes_at",
    now: datetime | None = None,
) -> str:
    if not snapshot:
        return ""
    status = str(snapshot.get("status") or "")
    if status == "refunded" and refunded_text:
        return refunded_text
    if status == settled_status and settled_text:
        return settled_text
    if status in set(spinning_statuses):
        return spinning_text
    left = seconds_until(snapshot.get(closes_key), now=now)
    collect = snapshot.get(collect_key) or collect_default
    if left is None:
        return waiting_template.format(collect=collect)
    return running_template.format(left=left)


def render_board(
    *,
    header: str,
    money: str | None = None,
    subtitle: str | None = None,
    roster: list[str] | None = None,
    now: str | None = None,
    nxt: str | None = None,
    timer: str | None = None,
    extra: list[str] | None = None,
    footer: str | None = None,
    limit: int = 4000,
) -> str:
    chunks: list[str] = []
    if header:
        chunks.append(header)
    if money:
        chunks.append(money)
    if subtitle:
        chunks.append(subtitle)
    if roster:
        if chunks:
            chunks.append("")
        chunks.extend(row for row in roster if row)
    body = [bit for bit in (now_line(now), next_line(nxt), timer or "") if bit]
    if body:
        if chunks:
            chunks.append("")
        chunks.extend(body)
    if extra:
        filtered = [row for row in extra if row]
        if filtered:
            if chunks:
                chunks.append("")
            chunks.extend(filtered)
    if footer:
        chunks.append("")
        chunks.append(footer)
    text = "\n".join(chunks)
    if len(text) > limit:
        return text[: limit - 10] + "\n…"
    return text

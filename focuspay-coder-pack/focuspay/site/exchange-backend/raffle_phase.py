"""FocusLucky campaign phase labels for admin UI."""
from __future__ import annotations

from datetime import datetime, timezone

PHASE_BADGE = {
    "draft": "gray",
    "active": "green",
    "closed": "amber",
    "drawing": "blue",
    "drawn": "blue",
}


def _to_utc(dt) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def campaign_phase(campaign: dict) -> dict:
    status = str(campaign.get("status") or "draft")
    now = datetime.now(timezone.utc)
    starts = _to_utc(campaign.get("starts_at"))
    ends = _to_utc(campaign.get("ends_at"))
    draw = _to_utc(campaign.get("draw_at"))

    if status == "drawn":
        label = "Розыгрыш проведён"
    elif status == "drawing":
        label = "Идёт живой розыгрыш"
    elif status == "closed":
        label = "Набор закрыт, ждём розыгрыш"
    elif status == "draft":
        label = "Черновик"
    elif status == "active":
        label = "Идёт набор билетов"
    else:
        label = status

    accrual_open = status == "active"
    if ends and now > ends and status == "active":
        label = "Набор завершён (ожидает закрытия)"
        accrual_open = False

    days_until_draw = 0
    if draw:
        days_until_draw = max(0, (draw.date() - now.date()).days)

    progress_pct = 0.0
    if starts and draw and draw > starts:
        total_sec = (draw - starts).total_seconds()
        elapsed = (now - starts).total_seconds()
        if total_sec > 0:
            progress_pct = round(min(100.0, max(0.0, elapsed / total_sec * 100)), 1)

    return {
        "status": status,
        "phase_label": label,
        "phase_badge": PHASE_BADGE.get(status, "gray"),
        "accrual_open": accrual_open,
        "days_until_draw": days_until_draw,
        "campaign_progress_pct": progress_pct,
    }

"""Partner commission tiers: +step% every N referred clients, capped at max."""
from __future__ import annotations

from typing import Any, TypedDict


class TierSettings(TypedDict):
    base_percent: float
    step_percent: float
    every_n: int
    max_percent: float


DEFAULT_TIER: TierSettings = {
    "base_percent": 5.0,
    "step_percent": 5.0,
    "every_n": 5,
    "max_percent": 20.0,
}


def partner_effective_percent(
    refs: int,
    *,
    base_percent: float,
    step_percent: float,
    every_n: int,
    max_percent: float,
) -> float:
    base = float(base_percent)
    cap = float(max_percent)
    if float(step_percent) <= 0:
        return min(base, cap)
    every_n = max(1, int(every_n))
    tiers = max(0, int(refs)) // every_n
    raw = base + tiers * float(step_percent)
    return min(raw, cap)


def refs_until_next_tier(refs: int, every_n: int) -> int:
    every_n = max(1, int(every_n))
    rem = max(0, int(refs)) % every_n
    return every_n if rem == 0 else every_n - rem


def next_tier_percent(
    refs: int,
    settings: TierSettings,
) -> float | None:
    if float(settings["step_percent"]) <= 0:
        return None
    current = partner_effective_percent(refs, **settings)
    if current >= settings["max_percent"]:
        return None
    return partner_effective_percent(
        refs + refs_until_next_tier(refs, settings["every_n"]),
        **settings,
    )


def tier_info(refs: int, settings: TierSettings) -> dict[str, Any]:
    effective = partner_effective_percent(refs, **settings)
    fixed = float(settings["step_percent"]) <= 0
    until = 0 if fixed else refs_until_next_tier(refs, settings["every_n"])
    nxt = next_tier_percent(refs, settings)
    at_max = fixed or effective >= settings["max_percent"]
    return {
        "attracted_users": refs,
        "effective_percent": round(effective, 2),
        "refs_until_next_tier": 0 if at_max else until,
        "next_tier_percent": round(nxt, 2) if nxt is not None else None,
        "at_max_tier": at_max,
        "tier_fixed": fixed,
        **settings,
    }


def resolve_tier_settings(
    global_settings: TierSettings,
    campaign_row: dict[str, Any] | None = None,
) -> TierSettings:
    row = campaign_row or {}
    base = float(
        row["partner_tier_base_percent"]
        if row.get("partner_tier_base_percent") is not None
        else row.get("partner_commission_percent")
        if row.get("partner_commission_percent") is not None
        else global_settings["base_percent"]
    )
    max_pct = float(
        row["partner_tier_max_percent"]
        if row.get("partner_tier_max_percent") is not None
        else global_settings["max_percent"]
    )
    max_pct = max(max_pct, base)
    return {
        "base_percent": base,
        "step_percent": float(
            row["partner_tier_step_percent"]
            if row.get("partner_tier_step_percent") is not None
            else global_settings["step_percent"]
        ),
        "every_n": int(
            row["partner_tier_every_n"]
            if row.get("partner_tier_every_n") is not None
            else global_settings["every_n"]
        ),
        "max_percent": max_pct,
    }


def partner_tier_overrides_for_rate(
    percent: float,
    global_settings: TierSettings,
) -> dict[str, float | None]:
    pct = round(float(percent), 2)
    if pct > float(global_settings["max_percent"]):
        return {
            "partner_tier_base_percent": pct,
            "partner_tier_max_percent": pct,
            "partner_tier_step_percent": 0.0,
        }
    return {
        "partner_tier_base_percent": pct,
        "partner_tier_max_percent": None,
        "partner_tier_step_percent": None,
    }


def global_tier_from_runtime(raw: dict[str, Any]) -> TierSettings:
    return {
        "base_percent": float(
            raw.get("base_percent")
            if raw.get("base_percent") is not None
            else raw.get("partner_tier_base_percent", DEFAULT_TIER["base_percent"])
        ),
        "step_percent": float(
            raw.get("step_percent")
            if raw.get("step_percent") is not None
            else raw.get("partner_tier_step_percent", DEFAULT_TIER["step_percent"])
        ),
        "every_n": int(
            raw.get("every_n")
            if raw.get("every_n") is not None
            else raw.get("partner_tier_every_n", DEFAULT_TIER["every_n"])
        ),
        "max_percent": float(
            raw.get("max_percent")
            if raw.get("max_percent") is not None
            else raw.get("partner_tier_max_percent", DEFAULT_TIER["max_percent"])
        ),
    }

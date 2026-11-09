"""Admin-facing readiness checks for V2 PvP house bots."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from casino_finance import money

PVP_GAME_TYPES = frozenset({"pvp_dice"})
DEFAULT_GAME_TYPE = "pvp_dice"
DEFAULT_STAKE_RUB = Decimal("100.00")
MAX_V2_BOTS = 5


def _json_games(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _account_available(row: Mapping[str, object]) -> Decimal:
    return money(row["balance_rub"]) - money(row.get("reserved_rub") or 0)


def _profile_matches_stake(profile: Mapping[str, object], *, game_type: str, stake: Decimal) -> bool:
    if str(profile.get("mode") or "") != "pvp_robot":
        return False
    if not profile.get("is_active"):
        return False
    if not profile.get("account_active"):
        return False
    games = _json_games(profile.get("allowed_games"))
    if game_type not in games:
        return False
    return money(profile["min_bet_rub"]) <= stake <= money(profile["max_bet_rub"])


def _check(
    check_id: str,
    *,
    ok: bool,
    title: str,
    detail: str,
    step: str,
    href: str = "",
    required: bool = False,
) -> dict[str, object]:
    return {
        "id": check_id,
        "ok": ok,
        "title": title,
        "detail": detail,
        "step": step,
        "href": href,
        "required": required,
    }


def _json_setting(value: object) -> object:
    if isinstance(value, str):
        import json

        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _setting_amount(settings: Mapping[str, object], key: str) -> Decimal:
    raw = _json_setting(settings.get(key))
    if not isinstance(raw, dict):
        return Decimal("0")
    field = "amount" if "amount" in raw else "percent"
    return money(raw.get(field) or 0)


def _setting_has_field(settings: Mapping[str, object], key: str, field: str) -> bool:
    raw = _json_setting(settings.get(key))
    return isinstance(raw, dict) and field in raw


def _enabled_game_keys(settings: Mapping[str, object]) -> list[str]:
    raw = _json_setting(settings.get("enabled_games"))
    if not isinstance(raw, dict):
        return []
    return [str(key) for key, enabled in raw.items() if enabled is True]


STEP_HREF = {
    "bank": "/x8/casino/house#house-step-bank",
    "profiles": "/x8/casino/house#house-step-profiles",
    "limits": "/x8/casino/house#house-step-limits",
    "telegram": "/x8/casino/settings#section-chat",
    "commission": "/x8/casino/settings#section-commission",
    "games": "/x8/casino/settings#section-games",
}

REQUIRED_TOTAL = 5


def build_house_readiness(
    accounts: list[Mapping[str, object]],
    profiles: list[Mapping[str, object]],
    *,
    game_type: str = DEFAULT_GAME_TYPE,
    stake_rub: Decimal | float | str = DEFAULT_STAKE_RUB,
    settings: Mapping[str, object] | None = None,
    chat_bound: bool = False,
    chat_title: str | None = None,
) -> dict[str, object]:
    stake = money(stake_rub)
    stored = settings or {}
    checks: list[dict[str, object]] = []

    active_accounts = [row for row in accounts if row.get("is_active")]
    checks.append(
        _check(
            "bank_active",
            ok=bool(active_accounts),
            title="Банк казино включён",
            detail="Нет активного house-счёта" if not active_accounts else f"Активен: {active_accounts[0]['display_name']}",
            step="bank",
        )
    )

    primary_account = active_accounts[0] if active_accounts else None
    available = _account_available(primary_account) if primary_account else Decimal("0.00")
    bank_ok = primary_account is not None and available >= stake
    checks.append(
        _check(
            "bank_balance",
            ok=bank_ok,
            title="Достаточно средств в банке",
            detail=(
                f"Доступно {available} ₽, нужно ≥ {stake} ₽ на одного бота"
                if primary_account
                else "Сначала активируйте и пополните банк"
            ),
            step="bank",
        )
    )

    pvp_profiles = [row for row in profiles if str(row.get("mode") or "") == "pvp_robot"]
    active_pvp = [row for row in pvp_profiles if row.get("is_active")]
    checks.append(
        _check(
            "pvp_profiles_active",
            ok=bool(active_pvp),
            title="Есть активные PvP-роботы",
            detail=(
                f"Активных pvp_robot: {len(active_pvp)}"
                if active_pvp
                else "Включите хотя бы один профиль в режиме pvp_robot"
            ),
            step="profiles",
        )
    )

    wrong_mode = [
        row for row in profiles
        if row.get("is_active") and str(row.get("mode") or "") != "pvp_robot"
    ]
    checks.append(
        _check(
            "profile_mode",
            ok=not wrong_mode,
            title="Профили в режиме pvp_robot",
            detail=(
                "Все активные профили для V2 — pvp_robot"
                if not wrong_mode
                else ", ".join(
                    f"{row['profile_key']} ({row['mode']})" for row in wrong_mode[:3]
                )
            ),
            step="profiles",
        )
    )

    dice_profiles = [
        row for row in active_pvp
        if DEFAULT_GAME_TYPE in _json_games(row.get("allowed_games"))
    ]
    checks.append(
        _check(
            "pvp_dice_allowed",
            ok=bool(dice_profiles),
            title="Разрешена игра pvp_dice",
            detail=(
                f"Профилей с pvp_dice: {len(dice_profiles)}"
                if dice_profiles
                else "Добавьте pvp_dice в allowed_games активного PvP-робота"
            ),
            step="profiles",
        )
    )

    eligible = [row for row in profiles if _profile_matches_stake(row, game_type=game_type, stake=stake)]
    account_ids = {int(row["account_id"]) for row in eligible}
    same_account_ok = len(account_ids) <= 1
    checks.append(
        _check(
            "same_house_account",
            ok=same_account_ok,
            title="Все боты на одном банке",
            detail=(
                "Подходящие профили используют один house-счёт"
                if same_account_ok
                else f"Найдено {len(account_ids)} разных счёта — V2 требует один банк"
            ),
            step="profiles",
        )
    )

    stake_ok_profiles = eligible if same_account_ok else []
    if stake_ok_profiles:
        by_account: dict[int, list[Mapping[str, object]]] = {}
        for row in stake_ok_profiles:
            by_account.setdefault(int(row["account_id"]), []).append(row)
        best_account_id = max(by_account, key=lambda account_id: len(by_account[account_id]))
        capacity_profiles = by_account[best_account_id]
    else:
        capacity_profiles = []

    max_bots_capacity = min(len(capacity_profiles), MAX_V2_BOTS)
    stake_range_ok = bool(capacity_profiles)
    checks.append(
        _check(
            "stake_range",
            ok=stake_range_ok,
            title="Ставка входит в лимиты ботов",
            detail=(
                f"При ставке {stake} ₽ доступно профилей: {len(capacity_profiles)}"
                if stake_range_ok
                else f"Ни один pvp_robot не принимает ставку {stake} ₽"
            ),
            step="limits",
        )
    )

    reserve_ok = primary_account is not None and available >= stake * max(1, max_bots_capacity)
    checks.append(
        _check(
            "bank_reserve",
            ok=reserve_ok or max_bots_capacity == 0,
            title="Банк покрывает нескольких ботов",
            detail=(
                f"Доступно {available} ₽ для до {max_bots_capacity} бот(ов) × {stake} ₽"
                if reserve_ok
                else f"Для {max_bots_capacity} бот(ов) нужно ≥ {stake * max(1, max_bots_capacity)} ₽"
            ),
            step="limits",
        )
    )

    ready = all(item["ok"] for item in checks) and max_bots_capacity > 0
    for item in checks:
        item["href"] = STEP_HREF.get(str(item["step"]), "")
        item["required"] = False

    floor = _setting_amount(stored, "bankroll_floor_rub")
    bank_above = available > floor
    min_bet = _setting_amount(stored, "min_bet_rub")
    max_bet = _setting_amount(stored, "max_bet_rub")
    commission_set = _setting_has_field(stored, "commission_rate_wagering_complete", "percent")
    limits_ok = min_bet > 0 and max_bet >= min_bet and commission_set
    enabled = _enabled_game_keys(stored)
    active_robots = [row for row in profiles if row.get("is_active")]
    telegram_ok = bool(chat_bound)
    telegram_detail = (
        f"Привязан: {chat_title}" if telegram_ok and chat_title else (
            "Есть активная привязка" if telegram_ok else "Нет active-привязки в casino_game_chat_bindings"
        )
    )

    required = [
        _check(
            "bank_above_floor",
            ok=bank_above,
            title="Банк выше порога",
            detail=(
                f"Доступно {available} ₽, порог {floor} ₽"
                if primary_account
                else "Нет активного house-счёта"
            ),
            step="bank",
            href=STEP_HREF["bank"],
            required=True,
        ),
        _check(
            "commission_and_limits",
            ok=limits_ok,
            title="Комиссия и лимиты заданы",
            detail=(
                f"Комиссия после отыгрыша задана, ставка {min_bet}–{max_bet} ₽"
                if limits_ok
                else "Нужны min_bet > 0, max_bet ≥ min_bet и комиссия после отыгрыша"
            ),
            step="commission",
            href=STEP_HREF["commission"],
            required=True,
        ),
        _check(
            "game_enabled",
            ok=bool(enabled),
            title="Включена хотя бы одна игра",
            detail=(
                f"Включено: {', '.join(enabled[:4])}" + ("…" if len(enabled) > 4 else "")
                if enabled
                else "В enabled_games нет ни одной true"
            ),
            step="games",
            href=STEP_HREF["games"],
            required=True,
        ),
        _check(
            "robot_active",
            ok=bool(active_robots),
            title="Есть активный профиль робота",
            detail=(
                f"Активных профилей: {len(active_robots)}"
                if active_robots
                else "Нет is_active профиля в casino_robot_profiles"
            ),
            step="profiles",
            href=STEP_HREF["profiles"],
            required=True,
        ),
        _check(
            "telegram_bound",
            ok=telegram_ok,
            title="Telegram-чат привязан",
            detail=telegram_detail,
            step="telegram",
            href=STEP_HREF["telegram"],
            required=True,
        ),
    ]
    if len(required) != REQUIRED_TOTAL:
        raise RuntimeError("readiness must expose exactly five required checks")
    required_ok = sum(1 for item in required if item["ok"])
    required_ready = required_ok == REQUIRED_TOTAL

    return {
        "ready": ready,
        "game_type": game_type,
        "stake_rub": float(stake),
        "recommended_stake_rub": float(stake),
        "max_bots_capacity": max_bots_capacity,
        "available_rub": float(available),
        "active_pvp_profiles": len(active_pvp),
        "checks": checks,
        "required": required,
        "secondary": checks,
        "required_ready": required_ready,
        "required_ok": required_ok,
        "required_total": REQUIRED_TOTAL,
        "bankroll_floor_rub": float(floor),
    }


async def load_house_readiness(conn, *, game_type: str, stake_rub: Decimal) -> dict[str, object]:
    accounts = await conn.fetch(
        """
        SELECT id, account_key, display_name, balance_rub, reserved_rub, is_active
        FROM casino_house_accounts
        ORDER BY id
        """
    )
    profiles = await conn.fetch(
        """
        SELECT rp.id, rp.profile_key, rp.display_name, rp.mode, rp.account_id,
               ha.is_active AS account_active, rp.is_active, rp.allowed_games,
               rp.min_bet_rub, rp.max_bet_rub, rp.max_concurrent_games, rp.max_exposure_rub
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        ORDER BY rp.id
        """
    )
    settings_rows = await conn.fetch(
        """
        SELECT key, value FROM casino_settings
        WHERE key = ANY($1::text[])
        """,
        [
            "bankroll_floor_rub",
            "min_bet_rub",
            "max_bet_rub",
            "commission_rate_wagering_complete",
            "enabled_games",
        ],
    )
    settings = {str(row["key"]): row["value"] for row in settings_rows}
    chat = await conn.fetchrow(
        """
        SELECT chat_title
        FROM casino_game_chat_bindings
        WHERE status = 'active'
        ORDER BY updated_at DESC
        LIMIT 1
        """
    )
    return build_house_readiness(
        [dict(row) for row in accounts],
        [dict(row) for row in profiles],
        game_type=game_type,
        stake_rub=stake_rub,
        settings=settings,
        chat_bound=chat is not None,
        chat_title=str(chat["chat_title"]) if chat and chat["chat_title"] else None,
    )


def validate_profile_mode_games(mode: str, allowed_games: list[str]) -> None:
    pvp_games = [game for game in allowed_games if game in PVP_GAME_TYPES]
    if mode == "pvp_robot" and not pvp_games:
        raise ValueError("pvp_robot profile must allow at least one PvP game type")
    if mode == "house_robot" and "cub" not in allowed_games:
        raise ValueError("house_robot profile must allow cub")

"""

Admin Casino Panel API

Provides comprehensive casino management endpoints for owner dashboard.

"""

import json

import logging

import uuid

from datetime import date, datetime, timedelta

from decimal import Decimal, ROUND_HALF_UP

from math import isfinite

from typing import Annotated, Optional
from uuid import UUID



from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator



from auth import get_current_admin, get_current_finance_owner

from config import settings as app_settings

from db import get_pool

from referral_links import generate_ref_token, web_ref_link

from casino_house_readiness import (
    DEFAULT_GAME_TYPE,
    load_house_readiness,
    validate_profile_mode_games,
)
from casino_tier_config import (
    cashback_tiers_to_public,
    commission_tiers_to_public,
    parse_cashback_volume_tiers,
    parse_commission_volume_tiers,
    tier_config_from_settings,
)
from admin_salary import today_moscow
from casino_finance import money
from casino_stats import chart_from_stats, dashboard_from_stats, fetch_casino_stats
from casino_clans import disband_clan as clans_disband
from casino_risk import WINDOWS, WINDOW_SQL, fetch_risk_snapshot
from casino_settings_registry import (
    GAME_KEYS as KNOWN_GAME_KEYS,
    REGISTRY,
    default_numeric,
    is_known_key,
    to_storage,
    validate_value,
    UnknownSettingKey,
    SettingValueError,
)





logger = logging.getLogger(__name__)

router = APIRouter()



DEFAULT_ENABLED_GAMES = {game: True for game in KNOWN_GAME_KEYS}
ROBOT_GAME_KEYS = (set(KNOWN_GAME_KEYS) | {"cub"}) - {"holdem", "jackpot", "clan_war", "russian_draughts"}


def _default_setting(key: str) -> float:
    return float(default_numeric(key))





def _json_obj(value: object) -> object:

    """asyncpg отдаёт JSONB-колонку строкой без кодека — распарсить при чтении."""

    if isinstance(value, str):

        try:

            return json.loads(value)

        except (ValueError, TypeError):

            return None

    return value





def _safe_bool_map(value: object, *, default: bool) -> dict[str, bool]:
    value = _json_obj(value)
    games = {game: default for game in KNOWN_GAME_KEYS}
    if isinstance(value, dict):
        for key in KNOWN_GAME_KEYS:
            if isinstance(value.get(key), bool):
                games[key] = value[key]
    return games


def _safe_enabled_games(value: object) -> dict[str, bool]:

    value = _json_obj(value)

    games = DEFAULT_ENABLED_GAMES.copy()

    if isinstance(value, dict):

        for key in KNOWN_GAME_KEYS:

            if isinstance(value.get(key), bool):

                games[key] = value[key]

            elif key == "russian_draughts":

                games[key] = False

    else:

        games["russian_draughts"] = False

    return games





def _setting_number(settings: dict, key: str, *, field: str) -> float:

    spec = REGISTRY[key]
    default = float(spec.default) if spec.kind in {"percent", "amount"} else _default_setting(key)
    value = _json_obj(settings.get(key))

    if not isinstance(value, dict):

        return default

    raw = value.get(field)

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):

        return default

    number = float(raw)

    if not isfinite(number):

        return default

    if spec.min_value is not None and number < float(spec.min_value):

        return default

    if spec.max_value is not None and number > float(spec.max_value):

        return default

    return number


def _setting_int(settings: dict, key: str) -> int:
    spec = REGISTRY[key]
    default = int(spec.default)
    value = _json_obj(settings.get(key))
    raw = value.get("value") if isinstance(value, dict) else value
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    if float(raw) != int(raw):
        return default
    number = int(raw)
    if spec.min_value is not None and number < spec.min_value:
        return default
    if spec.max_value is not None and number > spec.max_value:
        return default
    return number


def _setting_bool(settings: dict, key: str) -> bool:
    spec = REGISTRY[key]
    default = bool(spec.default)
    value = _json_obj(settings.get(key))
    raw = value.get("enabled") if isinstance(value, dict) else value
    if not isinstance(raw, bool):
        return default
    return raw


def _copied_default(spec) -> object:
    default = spec.default
    return dict(default) if isinstance(default, dict) else default


def _setting_row_dict(row) -> dict:
    if hasattr(row, "model_dump"):
        return row.model_dump()
    return dict(row)


def _setting_fingerprint(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _setting_object(settings: dict, key: str) -> object:
    spec = REGISTRY[key]
    raw = _json_obj(settings.get(key))
    if raw is None:
        return _copied_default(spec)
    try:
        return validate_value(key, raw)
    except (UnknownSettingKey, SettingValueError):
        return _copied_default(spec)





def _owner_share_percent(commission_rate: float, creator_cut: float, referral_l1: float, referral_l2: float) -> float:
    owner_share = round(commission_rate - creator_cut - referral_l1 - referral_l2, 4)
    return owner_share if owner_share >= 0 else 0.0





def _settings_response(settings: dict) -> "CasinoSettingsResponse":

    min_bet = _setting_number(settings, "min_bet_rub", field="amount")

    max_bet = _setting_number(settings, "max_bet_rub", field="amount")

    if min_bet > max_bet:

        min_bet = _default_setting("min_bet_rub")

        max_bet = _default_setting("max_bet_rub")



    commission_active = _setting_number(settings, "commission_rate_wagering_active", field="percent")

    commission_complete = _setting_number(settings, "commission_rate_wagering_complete", field="percent")

    creator_active = _setting_number(settings, "creator_cut_percent_wagering_active", field="percent")

    referral_l1_active = _setting_number(settings, "referral_l1_percent_wagering_active", field="percent")

    referral_l2_active = _setting_number(settings, "referral_l2_percent_wagering_active", field="percent")

    creator_complete = _setting_number(settings, "creator_cut_percent_wagering_complete", field="percent")

    referral_l1_complete = _setting_number(settings, "referral_l1_percent_wagering_complete", field="percent")

    referral_l2_complete = _setting_number(settings, "referral_l2_percent_wagering_complete", field="percent")

    owner_share_active = _owner_share_percent(commission_active, creator_active, referral_l1_active, referral_l2_active)

    owner_share_complete = _owner_share_percent(commission_complete, creator_complete, referral_l1_complete, referral_l2_complete)



    preview_active = _commission_preview(commission_active, creator_active, referral_l1_active, referral_l2_active, owner_share_active)

    preview_complete = _commission_preview(commission_complete, creator_complete, referral_l1_complete, referral_l2_complete, owner_share_complete)

    # Базовые поля в ответе = активный профиль отыгрыша (единая правда для UI и бота).
    commission_rate = commission_active
    creator_cut = creator_active
    referral_l1 = referral_l1_active
    referral_l2 = referral_l2_active
    owner_share = owner_share_active
    preview = preview_active



    tier_config = tier_config_from_settings(settings)



    return CasinoSettingsResponse(

        commission_rate=commission_rate,

        commission_rate_wagering_active=_setting_number(settings, "commission_rate_wagering_active", field="percent"),

        commission_rate_wagering_complete=_setting_number(settings, "commission_rate_wagering_complete", field="percent"),

        wagering_percent=_setting_number(settings, "wagering_percent", field="percent"),

        creator_cut_percent=creator_cut,

        referral_l1_percent=referral_l1,

        referral_l2_percent=referral_l2,

        creator_cut_percent_wagering_active=creator_active,

        referral_l1_percent_wagering_active=referral_l1_active,

        referral_l2_percent_wagering_active=referral_l2_active,

        creator_cut_percent_wagering_complete=creator_complete,

        referral_l1_percent_wagering_complete=referral_l1_complete,

        referral_l2_percent_wagering_complete=referral_l2_complete,

        owner_share_percent=owner_share,

        owner_share_percent_wagering_active=owner_share_active,

        owner_share_percent_wagering_complete=owner_share_complete,

        min_bet_rub=min_bet,

        max_bet_rub=max_bet,

        min_withdrawal_rub=_setting_number(settings, "min_withdrawal_rub", field="amount"),
        max_profit_pct_per_round=_setting_number(settings, "max_profit_pct_per_round", field="percent"),
        max_profit_pct_per_round_all=_setting_number(settings, "max_profit_pct_per_round_all", field="percent"),
        bankroll_floor_rub=_setting_number(settings, "bankroll_floor_rub", field="amount"),
        liability_amount_rub=_setting_number(settings, "liability_amount_rub", field="amount"),
        per_game_limits=_setting_object(settings, "per_game_limits"),
        bet_step_rub=_setting_number(settings, "bet_step_rub", field="amount"),
        max_concurrent_games_per_player=_setting_int(settings, "max_concurrent_games_per_player"),
        max_rounds_per_player_per_day=_setting_object(settings, "max_rounds_per_player_per_day"),
        pending_invite_ttl_minutes=_setting_int(settings, "pending_invite_ttl_minutes"),
        move_timeout_minutes=_setting_int(settings, "move_timeout_minutes"),
        holdem_small_blind_rub=_setting_number(settings, "holdem_small_blind_rub", field="amount"),
        holdem_big_blind_rub=_setting_number(settings, "holdem_big_blind_rub", field="amount"),
        holdem_rake_percent=_setting_number(settings, "holdem_rake_percent", field="percent"),
        holdem_rake_cap_rub=_setting_number(settings, "holdem_rake_cap_rub", field="amount"),
        holdem_action_timeout_seconds=_setting_int(settings, "holdem_action_timeout_seconds"),
        draughts_move_timeout_seconds=_setting_int(settings, "draughts_move_timeout_seconds"),
        holdem_min_buyin_bb=_setting_int(settings, "holdem_min_buyin_bb"),
        holdem_max_buyin_bb=_setting_int(settings, "holdem_max_buyin_bb"),
        jackpot_collect_seconds=_setting_int(settings, "jackpot_collect_seconds"),
        jackpot_max_players=_setting_int(settings, "jackpot_max_players"),
        jackpot_rake_percent=_setting_number(settings, "jackpot_rake_percent", field="percent"),
        roulette_table_collect_seconds=_setting_int(settings, "roulette_table_collect_seconds"),
        roulette_table_max_players=_setting_int(settings, "roulette_table_max_players"),
        clans_enabled=_setting_bool(settings, "clans_enabled"),
        clan_max_members=_setting_int(settings, "clan_max_members"),
        fixed_room_rake_percent=_setting_number(settings, "fixed_room_rake_percent", field="percent"),
        fixed_room_max_seats=_setting_int(settings, "fixed_room_max_seats"),
        fixed_room_collect_seconds=_setting_int(settings, "fixed_room_collect_seconds"),
        clan_war_rake_percent=_setting_number(settings, "clan_war_rake_percent", field="percent"),
        clan_war_max_fighters=_setting_int(settings, "clan_war_max_fighters"),
        clan_war_collect_seconds=_setting_int(settings, "clan_war_collect_seconds"),
        commission_cap_rub=_setting_number(settings, "commission_cap_rub", field="amount"),
        commission_min_rub=_setting_number(settings, "commission_min_rub", field="amount"),
        deposit_limit_enabled=_setting_bool(settings, "deposit_limit_enabled"),
        loss_limit_enabled=_setting_bool(settings, "loss_limit_enabled"),
        wager_limit_enabled=_setting_bool(settings, "wager_limit_enabled"),
        session_limit_enabled=_setting_bool(settings, "session_limit_enabled"),
        reality_check_default_minutes=_setting_int(settings, "reality_check_default_minutes"),
        self_exclusion_min_hours=_setting_int(settings, "self_exclusion_min_hours"),
        timeout_max_hours=_setting_int(settings, "timeout_max_hours"),
        limit_loosening_delay_hours=_setting_int(settings, "limit_loosening_delay_hours"),
        withdrawal_auto_approve_max_rub=_setting_number(settings, "withdrawal_auto_approve_max_rub", field="amount"),
        withdrawal_manual_review_min_rub=_setting_number(settings, "withdrawal_manual_review_min_rub", field="amount"),
        withdrawal_daily_limit_rub=_setting_number(settings, "withdrawal_daily_limit_rub", field="amount"),
        withdrawal_hourly_limit_rub=_setting_number(settings, "withdrawal_hourly_limit_rub", field="amount"),
        provably_fair_enabled=_safe_bool_map(settings.get("provably_fair_enabled"), default=False),
        seed_rotation_allowed=_setting_bool(settings, "seed_rotation_allowed"),

        enabled_games=_safe_enabled_games(settings.get("enabled_games")),

        commission_preview=preview,

        commission_preview_wagering_active=preview_active,

        commission_preview_wagering_complete=preview_complete,

        cashback_volume_tiers=[
            CashbackVolumeTierRow(min_wager_rub=row["min_wager_rub"], percent=row["percent"])
            for row in cashback_tiers_to_public(tier_config.cashback_volume_tiers)
        ],

        commission_volume_tiers=[
            CommissionVolumeTierRow(
                min_wager_rub=row["min_wager_rub"],
                active_rate=row["active_rate"],
                complete_rate=row["complete_rate"],
            )
            for row in commission_tiers_to_public(tier_config.commission_volume_tiers)
        ],

        level_reach_bonuses=[
            LevelReachBonusRow(min_wager_rub=row["min_wager_rub"], bonus_rub=row["bonus_rub"])
            for row in (_setting_object(settings, "level_reach_bonuses") or [])
        ],

    )





_PREVIEW_STAKE_RUB = 100.0





def _commission_preview(

    commission_rate: float,

    creator_cut: float,

    referral_l1: float,

    referral_l2: float,

    owner_share: float,

) -> "CommissionPreview":

    """Разложить комиссию на тестовой ставке как доли проигранной ставки.



    Совпадает с моделью casino_finance.allocate_commission: creator/L1/L2 —

    абсолютные доли ставки, остаток комиссии (включая округление) идёт владельцу.

    """

    stake = _PREVIEW_STAKE_RUB

    commission = round(stake * commission_rate / 100.0, 2)

    creator_rub = round(stake * creator_cut / 100.0, 2)

    l1_rub = round(stake * referral_l1 / 100.0, 2)

    l2_rub = round(stake * referral_l2 / 100.0, 2)

    owner_rub = round(commission - creator_rub - l1_rub - l2_rub, 2)

    if owner_rub < 0:

        owner_rub = 0.0

    return CommissionPreview(

        stake_rub=stake,

        commission_rub=commission,

        creator_rub=creator_rub,

        referral_l1_rub=l1_rub,

        referral_l2_rub=l2_rub,

        owner_rub=owner_rub,

    )





def _admin_id(admin: dict) -> int:

    value = admin.get("id")

    if value is None:

        raise HTTPException(status_code=500, detail="Invalid admin principal")

    return int(value)





def _admin_username(admin: dict) -> str:

    value = admin.get("username")

    if not value:

        raise HTTPException(status_code=500, detail="Invalid admin principal")

    return str(value)





# ============================================================================

# Response Models

# ============================================================================



class CasinoDashboard(BaseModel):

    """Overall casino metrics for admin dashboard."""

    total_games: int

    total_turnover_rub: float

    total_commission_rub: float

    owner_profit_rub: float

    commission_profit_rub: float

    house_game_profit_rub: float

    active_players_count: int

    games_today: int

    turnover_today_rub: float

    commission_today_rub: float

    games_by_type: dict[str, int]  # {"pvp": 123, "baccara": 45, ...}

    top_players: list[dict]  # [{telegram_id, username, games_count, total_bet}, ...]

    top_clans: list[dict] = []  # [{tag, name, member_count, wager_rub}, ...]


class CasinoStats(BaseModel):
    """Period casino statistics: handle, GGR, NGR, hold, RTP."""

    model_config = ConfigDict(extra="allow")

    period: dict
    volume: dict
    ggr_breakdown: dict
    costs: dict
    ngr_rub: float
    owner: dict
    reconciliation: dict
    by_type: list[dict]
    daily: list[dict]
    players: dict
    cashier: dict
    bankroll: dict
    top_clans: list[dict] = []
    distributions: dict = {}






class CasinoGameListItem(BaseModel):

    """Casino game item for admin games list."""

    game_id: str

    game_type: str

    created_at: datetime

    finished_at: Optional[datetime]

    status: str

    players: list[int]  # telegram_ids

    bet_amount_rub: float

    winner_id: Optional[int]

    commission_rub: float

    creator_cut_rub: float

    owner_cut_rub: float





class CasinoGameDetail(CasinoGameListItem):

    """Detailed casino game info including full game_data."""

    game_data: dict  # Full JSONB payload





class CommissionPreview(BaseModel):

    """Рублёвое превью распределения комиссии на тестовой ставке."""

    stake_rub: float

    commission_rub: float

    creator_rub: float

    referral_l1_rub: float

    referral_l2_rub: float

    owner_rub: float





class CashbackVolumeTierRow(BaseModel):
    min_wager_rub: Annotated[float, Field(ge=0.0)]
    percent: Annotated[float, Field(ge=0.0, le=100.0)]


class CommissionVolumeTierRow(BaseModel):
    min_wager_rub: Annotated[float, Field(ge=0.0)]
    active_rate: Annotated[float, Field(ge=0.0, le=100.0)]
    complete_rate: Annotated[float, Field(ge=0.0, le=100.0)]


class LevelReachBonusRow(BaseModel):
    min_wager_rub: Annotated[float, Field(gt=0.0)]
    bonus_rub: Annotated[float, Field(ge=0.0)]


class CasinoSettingsResponse(BaseModel):

    """Current casino configuration."""

    commission_rate: float

    commission_rate_wagering_active: float

    commission_rate_wagering_complete: float

    wagering_percent: float

    creator_cut_percent: float

    referral_l1_percent: float

    referral_l2_percent: float

    creator_cut_percent_wagering_active: float

    referral_l1_percent_wagering_active: float

    referral_l2_percent_wagering_active: float

    creator_cut_percent_wagering_complete: float

    referral_l1_percent_wagering_complete: float

    referral_l2_percent_wagering_complete: float

    owner_share_percent: float  # commission_rate − creator − l1 − l2 (остаток владельцу)

    owner_share_percent_wagering_active: float

    owner_share_percent_wagering_complete: float

    min_bet_rub: float

    max_bet_rub: float

    min_withdrawal_rub: float

    max_profit_pct_per_round: float
    max_profit_pct_per_round_all: float
    bankroll_floor_rub: float
    liability_amount_rub: float
    per_game_limits: dict[str, dict[str, float]]
    bet_step_rub: float
    max_concurrent_games_per_player: int
    max_rounds_per_player_per_day: dict[str, int]
    pending_invite_ttl_minutes: int
    move_timeout_minutes: int
    holdem_small_blind_rub: float
    holdem_big_blind_rub: float
    holdem_rake_percent: float
    holdem_rake_cap_rub: float
    holdem_action_timeout_seconds: int
    draughts_move_timeout_seconds: int
    holdem_min_buyin_bb: int
    holdem_max_buyin_bb: int
    jackpot_collect_seconds: int
    jackpot_max_players: int
    jackpot_rake_percent: float
    roulette_table_collect_seconds: int
    roulette_table_max_players: int
    clans_enabled: bool
    clan_max_members: int
    fixed_room_rake_percent: float
    fixed_room_max_seats: int
    fixed_room_collect_seconds: int
    clan_war_rake_percent: float
    clan_war_max_fighters: int
    clan_war_collect_seconds: int
    commission_cap_rub: float
    commission_min_rub: float
    deposit_limit_enabled: bool
    loss_limit_enabled: bool
    wager_limit_enabled: bool
    session_limit_enabled: bool
    reality_check_default_minutes: int
    self_exclusion_min_hours: int
    timeout_max_hours: int
    limit_loosening_delay_hours: int
    withdrawal_auto_approve_max_rub: float
    withdrawal_manual_review_min_rub: float
    withdrawal_daily_limit_rub: float
    withdrawal_hourly_limit_rub: float
    provably_fair_enabled: dict[str, bool]
    seed_rotation_allowed: bool

    enabled_games: dict[str, bool]  # {"pvp": true, "baccara": false, ...}

    commission_preview: CommissionPreview

    commission_preview_wagering_active: CommissionPreview

    commission_preview_wagering_complete: CommissionPreview

    cashback_volume_tiers: list[CashbackVolumeTierRow]

    commission_volume_tiers: list[CommissionVolumeTierRow]

    level_reach_bonuses: list[LevelReachBonusRow]



class CasinoSettingsAuditRow(BaseModel):
    id: int
    batch_id: UUID
    key: str
    old_value: object | None
    new_value: object
    changed_by: str
    changed_at: datetime
    reason: str


class CasinoSettingsAuditList(BaseModel):
    items: list[CasinoSettingsAuditRow]
    total: int





class CasinoSettingsUpdate(BaseModel):

    """Partial casino settings update using whole-percent values."""



    model_config = ConfigDict(extra="forbid")



    commission_rate: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    commission_rate_wagering_active: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    commission_rate_wagering_complete: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    wagering_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    creator_cut_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l1_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l2_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    creator_cut_percent_wagering_active: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l1_percent_wagering_active: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l2_percent_wagering_active: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    creator_cut_percent_wagering_complete: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l1_percent_wagering_complete: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    referral_l2_percent_wagering_complete: Annotated[float, Field(ge=0.0, le=100.0)] | None = None

    min_bet_rub: Annotated[float, Field(gt=0.0)] | None = None

    max_bet_rub: Annotated[float, Field(gt=0.0)] | None = None

    min_withdrawal_rub: Annotated[float, Field(gt=0.0)] | None = None

    max_profit_pct_per_round: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    max_profit_pct_per_round_all: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    bankroll_floor_rub: Annotated[float, Field(ge=0.0)] | None = None
    liability_amount_rub: Annotated[float, Field(ge=0.0)] | None = None
    per_game_limits: dict[str, dict[str, float | None]] | None = None
    bet_step_rub: Annotated[float, Field(gt=0.0)] | None = None
    max_concurrent_games_per_player: Annotated[int, Field(ge=1)] | None = None
    max_rounds_per_player_per_day: dict[str, int] | None = None
    pending_invite_ttl_minutes: Annotated[int, Field(ge=1, le=60)] | None = None
    move_timeout_minutes: Annotated[int, Field(ge=1)] | None = None
    holdem_small_blind_rub: Annotated[float, Field(gt=0.0)] | None = None
    holdem_big_blind_rub: Annotated[float, Field(gt=0.0)] | None = None
    holdem_rake_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    holdem_rake_cap_rub: Annotated[float, Field(ge=0.0)] | None = None
    holdem_action_timeout_seconds: Annotated[int, Field(ge=5, le=300)] | None = None
    draughts_move_timeout_seconds: Annotated[int, Field(ge=5, le=300)] | None = None
    holdem_min_buyin_bb: Annotated[int, Field(ge=2)] | None = None
    holdem_max_buyin_bb: Annotated[int, Field(ge=2)] | None = None
    jackpot_collect_seconds: Annotated[int, Field(ge=30, le=3600)] | None = None
    jackpot_max_players: Annotated[int, Field(ge=2, le=100)] | None = None
    jackpot_rake_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    roulette_table_collect_seconds: Annotated[int, Field(ge=5, le=120)] | None = None
    roulette_table_max_players: Annotated[int, Field(ge=2, le=48)] | None = None
    clans_enabled: bool | None = None
    clan_max_members: Annotated[int, Field(ge=2, le=50)] | None = None
    fixed_room_rake_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    fixed_room_max_seats: Annotated[int, Field(ge=2, le=20)] | None = None
    fixed_room_collect_seconds: Annotated[int, Field(ge=30, le=3600)] | None = None
    clan_war_rake_percent: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    clan_war_max_fighters: Annotated[int, Field(ge=1, le=20)] | None = None
    clan_war_collect_seconds: Annotated[int, Field(ge=60, le=86400)] | None = None
    commission_cap_rub: Annotated[float, Field(ge=0.0)] | None = None
    commission_min_rub: Annotated[float, Field(ge=0.0)] | None = None
    deposit_limit_enabled: bool | None = None
    loss_limit_enabled: bool | None = None
    wager_limit_enabled: bool | None = None
    session_limit_enabled: bool | None = None
    reality_check_default_minutes: Annotated[int, Field(ge=0)] | None = None
    self_exclusion_min_hours: Annotated[int, Field(ge=1)] | None = None
    timeout_max_hours: Annotated[int, Field(ge=1)] | None = None
    limit_loosening_delay_hours: Annotated[int, Field(ge=0)] | None = None
    withdrawal_auto_approve_max_rub: Annotated[float, Field(ge=0.0)] | None = None
    withdrawal_manual_review_min_rub: Annotated[float, Field(ge=0.0)] | None = None
    withdrawal_daily_limit_rub: Annotated[float, Field(ge=0.0)] | None = None
    withdrawal_hourly_limit_rub: Annotated[float, Field(ge=0.0)] | None = None
    provably_fair_enabled: dict[str, bool] | None = None
    seed_rotation_allowed: bool | None = None

    enabled_games: dict[str, bool] | None = None

    cashback_volume_tiers: list[CashbackVolumeTierRow] | None = None

    commission_volume_tiers: list[CommissionVolumeTierRow] | None = None

    level_reach_bonuses: list[LevelReachBonusRow] | None = None

    reason: Annotated[str, Field(min_length=1, max_length=500)] | None = None



    @field_validator(

        "commission_rate",

        "commission_rate_wagering_active",

        "commission_rate_wagering_complete",

        "wagering_percent",

        "creator_cut_percent",

        "referral_l1_percent",

        "referral_l2_percent",

        "creator_cut_percent_wagering_active",

        "referral_l1_percent_wagering_active",

        "referral_l2_percent_wagering_active",

        "creator_cut_percent_wagering_complete",

        "referral_l1_percent_wagering_complete",

        "referral_l2_percent_wagering_complete",

        "min_bet_rub",

        "max_bet_rub",

        "min_withdrawal_rub",
        "max_profit_pct_per_round",
        "max_profit_pct_per_round_all",
        "bankroll_floor_rub",
        "liability_amount_rub",
        "bet_step_rub",
        "max_concurrent_games_per_player",
        "pending_invite_ttl_minutes",
        "move_timeout_minutes",
        "holdem_small_blind_rub",
        "holdem_big_blind_rub",
        "holdem_rake_percent",
        "holdem_rake_cap_rub",
        "holdem_action_timeout_seconds",
        "draughts_move_timeout_seconds",
        "holdem_min_buyin_bb",
        "holdem_max_buyin_bb",
        "jackpot_collect_seconds",
        "jackpot_max_players",
        "jackpot_rake_percent",
        "roulette_table_collect_seconds",
        "roulette_table_max_players",
        "clans_enabled",
        "clan_max_members",
        "fixed_room_rake_percent",
        "fixed_room_max_seats",
        "fixed_room_collect_seconds",
        "clan_war_rake_percent",
        "clan_war_max_fighters",
        "clan_war_collect_seconds",
        "commission_cap_rub",
        "commission_min_rub",
        "deposit_limit_enabled",
        "loss_limit_enabled",
        "wager_limit_enabled",
        "session_limit_enabled",
        "reality_check_default_minutes",
        "self_exclusion_min_hours",
        "timeout_max_hours",
        "limit_loosening_delay_hours",
        "withdrawal_auto_approve_max_rub",
        "withdrawal_manual_review_min_rub",
        "withdrawal_daily_limit_rub",
        "withdrawal_hourly_limit_rub",
        "seed_rotation_allowed",
        "per_game_limits",
        "max_rounds_per_player_per_day",
        "provably_fair_enabled",
        "enabled_games",
        "reason",

        mode="before",

    )

    @classmethod

    def reject_explicit_null(cls, value: object):

        if value is None:

            raise ValueError("Explicit null is not allowed")

        return value



    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None):
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason is required")
        return stripped



    @field_validator("enabled_games")

    @classmethod

    def validate_enabled_games(cls, value: dict[str, bool] | None):

        if value is None:

            return value

        unknown = set(value) - set(KNOWN_GAME_KEYS)

        if unknown:

            raise ValueError(f"Unknown game keys: {', '.join(sorted(unknown))}")

        return value



    @field_validator("provably_fair_enabled", "max_rounds_per_player_per_day", "per_game_limits")
    @classmethod
    def validate_game_keyed_maps(cls, value: object):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise ValueError("Must be an object")
        unknown = set(value) - set(KNOWN_GAME_KEYS)
        if unknown:
            raise ValueError(f"Unknown game keys: {', '.join(sorted(unknown))}")
        return value



    @model_validator(mode="after")

    def validate_complete_values(self):

        shares = (

            self.creator_cut_percent,

            self.referral_l1_percent,

            self.referral_l2_percent,

        )

        if all(value is not None for value in (*shares, self.commission_rate)) and sum(shares) > self.commission_rate:

            raise ValueError("Creator and referral shares cannot exceed the commission rate")

        if (

            self.min_bet_rub is not None

            and self.max_bet_rub is not None

            and self.min_bet_rub > self.max_bet_rub

        ):

            raise ValueError("min_bet_rub cannot exceed max_bet_rub")

        return self





class CreatorAccountAssignRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")



    web_user_id: Annotated[int, Field(gt=0)]





class CreatorAccountResponse(BaseModel):

    id: int

    web_user_id: int

    username: Optional[str]

    display_name: Optional[str]

    ref_token: str

    ref_link: str

    assigned_at: datetime





class CreatorWithdrawalListItem(BaseModel):

    """Creator withdrawal request for admin review."""

    withdrawal_id: int

    created_at: datetime

    amount_rub: float

    method: str  # crypto/card/sbp

    requisites: str

    status: str  # pending/approved/rejected

    processed_at: Optional[datetime]

    processed_by_admin_id: Optional[str]

    tx_hash: Optional[str]

    rejection_reason: Optional[str]





class WithdrawalApproval(BaseModel):

    """Approve creator withdrawal."""



    model_config = ConfigDict(extra="forbid")



    tx_hash: str = Field(..., min_length=1, description="Transaction hash or payment confirmation")





class WithdrawalRejection(BaseModel):

    """Reject creator withdrawal."""



    model_config = ConfigDict(extra="forbid")



    reason: str = Field(..., min_length=1, description="Rejection reason")





class GameChatBindingResponse(BaseModel):

    id: int

    chat_id: int

    chat_type: str

    chat_title: Optional[str]

    telegram_url: Optional[str]

    status: str

    requested_by_telegram_id: int

    created_at: datetime

    updated_at: datetime

    confirmed_at: Optional[datetime]

    disabled_at: Optional[datetime]





class GameChatBindingAction(BaseModel):

    model_config = ConfigDict(extra="forbid")



    binding_id: int = Field(gt=0)





class HouseAccountResponse(BaseModel):

    id: int

    account_key: str

    display_name: str

    balance_rub: float

    reserved_rub: float

    available_rub: float

    is_active: bool

    created_at: datetime

    updated_at: datetime





class HouseLedgerItem(BaseModel):

    id: int

    account_id: int

    game_id: str | None

    entry_key: str

    entry_type: str

    amount_rub: float

    balance_after_rub: float

    reason: str

    created_by: str | None

    created_at: datetime





class HouseMoneyRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")



    amount_rub: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    reason: str = Field(min_length=1, max_length=1000)

    idempotency_key: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")



    @field_validator("amount_rub")

    @classmethod

    def money_precision(cls, value: Decimal) -> Decimal:

        if not value.is_finite() or value.as_tuple().exponent < -2:

            raise ValueError("amount_rub must have at most two decimal places")

        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)



    @field_validator("reason")

    @classmethod

    def non_blank_reason(cls, value: str) -> str:

        value = value.strip()

        if not value:

            raise ValueError("reason must not be blank")

        return value





class HouseAdjustmentRequest(HouseMoneyRequest):

    direction: str = Field(pattern=r"^(credit|debit)$")





class HouseProfileUpdate(BaseModel):

    model_config = ConfigDict(extra="forbid")



    is_active: bool | None = None

    display_name: str | None = Field(default=None, min_length=1, max_length=128)

    mode: str | None = Field(default=None, pattern=r"^(house_robot|pvp_robot)$")

    allowed_games: list[str] | None = None

    min_bet_rub: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)

    max_bet_rub: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)

    max_concurrent_games: int | None = Field(default=None, gt=0, le=1000)

    max_exposure_rub: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)



    @field_validator("allowed_games")

    @classmethod

    def known_profile_games(cls, value: list[str] | None) -> list[str] | None:

        if value is None:

            return value

        allowed = ROBOT_GAME_KEYS

        if not value or len(value) != len(set(value)) or any(game not in allowed for game in value):

            raise ValueError("allowed_games must be a non-empty unique list of known games")

        return value



    @model_validator(mode="after")

    def profile_limits(self):

        if self.min_bet_rub is not None and self.max_bet_rub is not None and self.min_bet_rub > self.max_bet_rub:

            raise ValueError("min_bet_rub cannot exceed max_bet_rub")

        return self





class HouseProfileCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")



    profile_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")

    display_name: str = Field(min_length=1, max_length=128)

    account_id: int | None = None

    mode: str = Field(default="pvp_robot", pattern=r"^(house_robot|pvp_robot)$")

    allowed_games: list[str] = Field(default_factory=lambda: [DEFAULT_GAME_TYPE])

    min_bet_rub: Decimal = Field(default=Decimal("10.00"), gt=0, max_digits=10, decimal_places=2)

    max_bet_rub: Decimal = Field(default=Decimal("100000.00"), gt=0, max_digits=10, decimal_places=2)

    max_concurrent_games: int = Field(default=20, gt=0, le=1000)

    max_exposure_rub: Decimal = Field(default=Decimal("50000.00"), ge=0, max_digits=12, decimal_places=2)

    is_active: bool = True



    @field_validator("allowed_games")

    @classmethod

    def known_profile_games(cls, value: list[str]) -> list[str]:

        allowed = ROBOT_GAME_KEYS

        if not value or len(value) != len(set(value)) or any(game not in allowed for game in value):

            raise ValueError("allowed_games must be a non-empty unique list of known games")

        return value



    @model_validator(mode="after")

    def profile_limits(self):

        if self.min_bet_rub > self.max_bet_rub:

            raise ValueError("min_bet_rub cannot exceed max_bet_rub")

        validate_profile_mode_games(self.mode, self.allowed_games)

        return self





class HouseReadinessCheck(BaseModel):

    id: str

    ok: bool

    title: str

    detail: str

    step: str

    href: str = ""

    required: bool = False





class HouseReadinessResponse(BaseModel):

    ready: bool

    game_type: str

    stake_rub: float

    recommended_stake_rub: float

    max_bots_capacity: int

    available_rub: float

    active_pvp_profiles: int

    checks: list[HouseReadinessCheck]

    required: list[HouseReadinessCheck] = []

    secondary: list[HouseReadinessCheck] = []

    required_ready: bool = False

    required_ok: int = 0

    required_total: int = 5

    bankroll_floor_rub: float = 0





class HouseProfileResponse(BaseModel):

    id: int

    profile_key: str

    display_name: str

    mode: str

    account_id: int

    account_active: bool

    is_active: bool

    allowed_games: list[str]

    min_bet_rub: float

    max_bet_rub: float

    max_concurrent_games: int

    max_exposure_rub: float

    created_at: datetime

    updated_at: datetime





class HousePolicyCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")



    policy_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")

    game_type: str = Field(min_length=1, max_length=32)

    payout_multiplier: Decimal = Field(ge=0, le=1000, max_digits=10, decimal_places=6)

    win_probability: Decimal = Field(gt=0, lt=1, max_digits=10, decimal_places=8)

    terms: dict[str, object] = Field(default_factory=dict)



    @field_validator("game_type")

    @classmethod

    def house_game_type(cls, value: str) -> str:

        if value != "cub":

            raise ValueError("game_type is not supported for house policies")

        return value





class HousePolicyResponse(BaseModel):

    id: int

    policy_key: str

    version: int

    game_type: str

    is_active: bool

    payout_multiplier: float

    win_probability: float

    terms: dict[str, object]

    created_by: str | None

    created_at: datetime





def _house_account_response(row: object) -> HouseAccountResponse:

    data = dict(row)

    data["balance_rub"] = float(data["balance_rub"])

    data["reserved_rub"] = float(data["reserved_rub"])

    data["available_rub"] = float(

        Decimal(str(data["balance_rub"])) - Decimal(str(data["reserved_rub"]))

    )

    return HouseAccountResponse(**data)





def _house_profile_response(row: object) -> HouseProfileResponse:

    data = dict(row)

    data["allowed_games"] = _json_obj(data["allowed_games"]) or []

    for field in ("min_bet_rub", "max_bet_rub", "max_exposure_rub"):

        data[field] = float(data[field])

    return HouseProfileResponse(**data)





def _house_policy_response(row: object) -> HousePolicyResponse:

    data = dict(row)

    data["terms"] = _json_obj(data["terms"]) or {}

    data["payout_multiplier"] = float(data["payout_multiplier"])

    data["win_probability"] = float(data["win_probability"])

    return HousePolicyResponse(**data)





def _house_ledger_response(row: object) -> HouseLedgerItem:

    data = dict(row)

    data["amount_rub"] = float(data["amount_rub"])

    data["balance_after_rub"] = float(data["balance_after_rub"])

    return HouseLedgerItem(**data)





# ============================================================================

# Endpoints

# ============================================================================



@router.get("/casino/house/accounts", response_model=list[HouseAccountResponse])

async def get_house_accounts(admin=Depends(get_current_finance_owner)):

    """List the isolated casino house bankroll accounts."""

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch(

            """

            SELECT id, account_key, display_name, balance_rub, reserved_rub, is_active,

                   created_at, updated_at

            FROM casino_house_accounts ORDER BY id

            """

        )

    return [_house_account_response(row) for row in rows]





@router.get("/casino/house/accounts/{account_id}/ledger", response_model=list[HouseLedgerItem])

async def get_house_ledger(

    account_id: int,

    admin=Depends(get_current_finance_owner),

    limit: int = Query(100, ge=1, le=500),

    offset: int = Query(0, ge=0),

):

    """Return immutable house ledger entries newest first."""

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch(

            """

            SELECT id, account_id, game_id, entry_key, entry_type, amount_rub,

                   balance_after_rub, reason, created_by, created_at

            FROM casino_house_ledger

            WHERE account_id = $1

            ORDER BY id DESC LIMIT $2 OFFSET $3

            """,

            account_id, limit, offset,

        )

    return [_house_ledger_response(row) for row in rows]





async def _post_house_money(

    conn, *, account_id: int, entry_type: str, amount: Decimal, reason: str,

    idempotency_key: str, admin_username: str,

) -> HouseAccountResponse:

    entry_key = f"admin-house:{entry_type}:{idempotency_key}"

    account = await conn.fetchrow(

        """

        SELECT id, account_key, display_name, balance_rub, reserved_rub, is_active,

               created_at, updated_at

        FROM casino_house_accounts WHERE id = $1 FOR UPDATE

        """, account_id,

    )

    if not account:

        raise HTTPException(status_code=404, detail="House account not found")

    existing = await conn.fetchrow(

        """

        SELECT account_id, entry_type, amount_rub, reason, balance_after_rub

        FROM casino_house_ledger WHERE entry_key = $1

        """, entry_key,

    )

    if existing:

        if (int(existing["account_id"]) != account_id or existing["entry_type"] != entry_type

                or Decimal(str(existing["amount_rub"])) != amount or existing["reason"] != reason):

            raise HTTPException(status_code=409, detail="Idempotency key conflicts with an existing operation")

        restored = dict(account)

        restored["balance_rub"] = existing["balance_after_rub"]

        return _house_account_response(restored)

    new_balance = Decimal(str(account["balance_rub"])) + amount

    if new_balance < Decimal(str(account["reserved_rub"])):

        raise HTTPException(status_code=409, detail="Adjustment cannot reduce available bankroll below reservations")

    updated = await conn.fetchrow(

        """

        UPDATE casino_house_accounts

        SET balance_rub = $2, updated_at = now()

        WHERE id = $1

        RETURNING id, account_key, display_name, balance_rub, reserved_rub, is_active,

                  created_at, updated_at

        """, account_id, new_balance,

    )

    await conn.execute(

        """

        INSERT INTO casino_house_ledger

            (account_id, entry_key, entry_type, amount_rub, balance_after_rub, reason, created_by)

        VALUES ($1, $2, $3, $4, $5, $6, $7)

        """, account_id, entry_key, entry_type, amount, new_balance, reason, admin_username,

    )

    return _house_account_response(updated)





@router.post("/casino/house/accounts/{account_id}/fund", response_model=HouseAccountResponse)

async def fund_house_account(

    account_id: int, body: HouseMoneyRequest, admin=Depends(get_current_finance_owner)

):

    """Fund a house account once for a client idempotency key."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            result = await _post_house_money(

                conn, account_id=account_id, entry_type="funding", amount=body.amount_rub,

                reason=body.reason, idempotency_key=body.idempotency_key,

                admin_username=_admin_username(admin),

            )

    logger.info("Finance owner %s funded house account %s", _admin_id(admin), account_id)

    return result





@router.post("/casino/house/accounts/{account_id}/adjust", response_model=HouseAccountResponse)

async def adjust_house_account(

    account_id: int, body: HouseAdjustmentRequest, admin=Depends(get_current_finance_owner)

):

    """Apply an auditable signed adjustment without consuming reserved funds."""

    amount = body.amount_rub if body.direction == "credit" else -body.amount_rub

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            result = await _post_house_money(

                conn, account_id=account_id, entry_type="adjustment", amount=amount,

                reason=body.reason, idempotency_key=body.idempotency_key,

                admin_username=_admin_username(admin),

            )

    logger.info("Finance owner %s adjusted house account %s", _admin_id(admin), account_id)

    return result





@router.get("/casino/house/profiles", response_model=list[HouseProfileResponse])

async def get_house_profiles(admin=Depends(get_current_finance_owner)):

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch(

            """

            SELECT rp.id, rp.profile_key, rp.display_name, rp.mode, rp.account_id,

                   ha.is_active AS account_active, rp.is_active, rp.allowed_games,

                   rp.min_bet_rub, rp.max_bet_rub, rp.max_concurrent_games, rp.max_exposure_rub,

                   rp.created_at, rp.updated_at

            FROM casino_robot_profiles rp JOIN casino_house_accounts ha ON ha.id = rp.account_id

            ORDER BY rp.id

            """

        )

    return [_house_profile_response(row) for row in rows]





@router.get("/casino/house/readiness", response_model=HouseReadinessResponse)

async def get_house_readiness(

    admin=Depends(get_current_finance_owner),

    game_type: str = Query(default=DEFAULT_GAME_TYPE),

    stake_rub: Decimal | None = Query(default=None, gt=0, max_digits=12, decimal_places=2),

):

    _admin_id(admin)

    if game_type not in KNOWN_GAME_KEYS:

        raise HTTPException(status_code=422, detail="Unknown game type")

    pool = await get_pool()

    async with pool.acquire() as conn:

        if stake_rub is None:

            settings_rows = await conn.fetch("SELECT key, value FROM casino_settings")

            settings = {row["key"]: row["value"] for row in settings_rows}

            stake = money(_setting_number(settings, "min_bet_rub", field="amount"))

        else:

            stake = money(stake_rub)

        payload = await load_house_readiness(conn, game_type=game_type, stake_rub=stake)

    return HouseReadinessResponse(**payload)





@router.post("/casino/house/profiles", response_model=HouseProfileResponse)

async def create_house_profile(body: HouseProfileCreate, admin=Depends(get_current_finance_owner)):

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            account_id = body.account_id

            if account_id is None:

                account = await conn.fetchrow(

                    "SELECT id, is_active FROM casino_house_accounts WHERE account_key = 'main'"

                )

                if not account:

                    raise HTTPException(status_code=404, detail="Main house account not found")

                account_id = int(account["id"])

                if body.is_active and not account["is_active"]:

                    raise HTTPException(status_code=409, detail="Cannot activate a profile on an inactive account")

            else:

                account = await conn.fetchrow(

                    "SELECT id, is_active FROM casino_house_accounts WHERE id = $1", account_id

                )

                if not account:

                    raise HTTPException(status_code=404, detail="House account not found")

                if body.is_active and not account["is_active"]:

                    raise HTTPException(status_code=409, detail="Cannot activate a profile on an inactive account")

            existing = await conn.fetchrow(

                "SELECT id FROM casino_robot_profiles WHERE profile_key = $1", body.profile_key

            )

            if existing:

                row = await conn.fetchrow(

                    """

                    SELECT rp.id, rp.profile_key, rp.display_name, rp.mode, rp.account_id,

                           ha.is_active AS account_active, rp.is_active, rp.allowed_games,

                           rp.min_bet_rub, rp.max_bet_rub, rp.max_concurrent_games, rp.max_exposure_rub,

                           rp.created_at, rp.updated_at

                    FROM casino_robot_profiles rp

                    JOIN casino_house_accounts ha ON ha.id = rp.account_id

                    WHERE rp.id = $1

                    """,

                    int(existing["id"]),

                )

                data = dict(row)

                data["account_active"] = row["account_active"]

                return _house_profile_response(data)

            row = await conn.fetchrow(

                """

                INSERT INTO casino_robot_profiles (

                    profile_key, display_name, mode, account_id, is_active, allowed_games,

                    min_bet_rub, max_bet_rub, max_concurrent_games, max_exposure_rub

                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)

                RETURNING id, profile_key, display_name, mode, account_id, is_active, allowed_games,

                          min_bet_rub, max_bet_rub, max_concurrent_games, max_exposure_rub,

                          created_at, updated_at

                """,

                body.profile_key,

                body.display_name,

                body.mode,

                account_id,

                body.is_active,

                json.dumps(body.allowed_games),

                body.min_bet_rub,

                body.max_bet_rub,

                body.max_concurrent_games,

                body.max_exposure_rub,

            )

            data = dict(row)

            data["account_active"] = account["is_active"]

    logger.info("Finance owner %s created house profile %s", _admin_id(admin), body.profile_key)

    return _house_profile_response(data)





@router.patch("/casino/house/profiles/{profile_id}", response_model=HouseProfileResponse)

async def update_house_profile(

    profile_id: int, body: HouseProfileUpdate, admin=Depends(get_current_finance_owner)

):

    patch = body.model_dump(exclude_unset=True)

    if not patch:

        raise HTTPException(status_code=422, detail="At least one field is required")

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            current = await conn.fetchrow(

                """

                SELECT rp.*, ha.is_active AS account_active

                FROM casino_robot_profiles rp JOIN casino_house_accounts ha ON ha.id = rp.account_id

                WHERE rp.id = $1 FOR UPDATE OF rp, ha

                """, profile_id,

            )

            if not current:

                raise HTTPException(status_code=404, detail="House profile not found")

            if patch.get("is_active") and not current["account_active"]:

                raise HTTPException(status_code=409, detail="Cannot activate a profile on an inactive account")

            min_bet = patch.get("min_bet_rub", current["min_bet_rub"])

            max_bet = patch.get("max_bet_rub", current["max_bet_rub"])

            if min_bet > max_bet:

                raise HTTPException(status_code=422, detail="min_bet_rub cannot exceed max_bet_rub")

            merged_mode = patch.get("mode", current["mode"])

            merged_games = patch.get("allowed_games", _json_obj(current["allowed_games"]) or [])

            if not isinstance(merged_games, list):

                merged_games = []

            try:

                validate_profile_mode_games(str(merged_mode), [str(game) for game in merged_games])

            except ValueError as exc:

                raise HTTPException(status_code=422, detail=str(exc)) from exc

            columns, args = [], []

            for index, (field, value) in enumerate(patch.items(), start=2):

                columns.append(f"{field} = ${index}" + ("::jsonb" if field == "allowed_games" else ""))

                args.append(json.dumps(value) if field == "allowed_games" else value)

            row = await conn.fetchrow(

                f"""

                UPDATE casino_robot_profiles SET {', '.join(columns)}, updated_at = now()

                WHERE id = $1

                RETURNING id, profile_key, display_name, mode, account_id, is_active, allowed_games,

                          min_bet_rub, max_bet_rub, max_concurrent_games, max_exposure_rub,

                          created_at, updated_at

                """, profile_id, *args,

            )

            data = dict(row)

            data["account_active"] = current["account_active"]

    return _house_profile_response(data)





@router.get("/casino/house/policies", response_model=list[HousePolicyResponse])

async def get_house_policies(admin=Depends(get_current_finance_owner)):

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch("SELECT * FROM casino_house_policies ORDER BY policy_key, version DESC")

    return [_house_policy_response(row) for row in rows]





@router.post("/casino/house/policies", response_model=HousePolicyResponse)

async def create_house_policy(body: HousePolicyCreate, admin=Depends(get_current_finance_owner)):

    """Create an immutable next version; activation remains explicit."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"house-policy:{body.policy_key}")

            row = await conn.fetchrow(

                """

                INSERT INTO casino_house_policies

                    (policy_key, version, game_type, payout_multiplier, win_probability, terms, created_by)

                SELECT $1, COALESCE(MAX(version), 0) + 1, $2, $3, $4, $5::jsonb, $6

                FROM casino_house_policies WHERE policy_key = $1

                RETURNING *

                """, body.policy_key, body.game_type, body.payout_multiplier, body.win_probability,

                json.dumps(body.terms), _admin_username(admin),

            )

    return _house_policy_response(row)





@router.post("/casino/house/policies/{policy_id}/activate", response_model=HousePolicyResponse)

async def activate_house_policy(policy_id: int, admin=Depends(get_current_finance_owner)):

    """Atomically activate one policy version per game type."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            policy = await conn.fetchrow(

                "SELECT * FROM casino_house_policies WHERE id = $1 FOR UPDATE", policy_id

            )

            if not policy:

                raise HTTPException(status_code=404, detail="House policy not found")

            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"house-policy-game:{policy['game_type']}")

            await conn.execute(

                "UPDATE casino_house_policies SET is_active = FALSE WHERE game_type = $1 AND is_active",

                policy["game_type"],

            )

            row = await conn.fetchrow(

                "UPDATE casino_house_policies SET is_active = TRUE WHERE id = $1 RETURNING *", policy_id

            )

    logger.info("Finance owner %s activated house policy %s", _admin_id(admin), policy_id)

    return _house_policy_response(row)





@router.get("/casino/chat-binding", response_model=GameChatBindingResponse | None)

async def get_game_chat_binding(admin=Depends(get_current_finance_owner)):

    """Return the current active binding, or most recently updated pending one."""

    _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        row = await conn.fetchrow(

            """

            SELECT id, chat_id, chat_type, chat_title, telegram_url, status, requested_by_telegram_id,

                   created_at, updated_at, confirmed_at, disabled_at

            FROM casino_game_chat_bindings

            WHERE status IN ('active', 'pending')

            ORDER BY (status = 'active') DESC, updated_at DESC

            LIMIT 1

            """

        )

    return dict(row) if row else None





class TournamentPrizePlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: int = Field(default=1, ge=1, le=20)
    prize_rub: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    share_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=6, decimal_places=2)


class TournamentUpsert(BaseModel):
    """Everything an owner can dial in for one tournament, FocusLucky-style."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Турнир FocusBet", min_length=1, max_length=140)
    subtitle: str = Field(default="", max_length=280)
    code: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="registration", pattern="^(draft|registration|active)$")
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    duration_minutes: int = Field(default=60, ge=5, le=43200)
    entry_mode: str = Field(default="free", pattern="^(free|promo|paid|promo_or_paid)$")
    promo_code: Optional[str] = Field(default=None, max_length=64)
    entry_fee_rub: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    starting_chips: Decimal = Field(default=Decimal("1000"), gt=0, max_digits=14, decimal_places=2)
    min_bet_chips: Decimal = Field(default=Decimal("10"), gt=0, max_digits=14, decimal_places=2)
    max_bet_chips: Decimal = Field(default=Decimal("1000"), gt=0, max_digits=14, decimal_places=2)
    rebuy_enabled: bool = False
    rebuy_fee_rub: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    rebuy_chips: Decimal = Field(default=Decimal("1000"), gt=0, max_digits=14, decimal_places=2)
    max_rebuys_per_user: int = Field(default=0, ge=0, le=100)
    rebuy_max_balance_chips: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    prize_mode: str = Field(default="fixed", pattern="^(fixed|dynamic)$")
    guaranteed_pool_rub: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    entry_pool_share_pct: Decimal = Field(default=Decimal("100"), ge=0, le=100, max_digits=6, decimal_places=2)
    prize_places: list[TournamentPrizePlace] = Field(default_factory=list, max_length=20)
    require_exchange_history: bool = True
    min_exchange_count: int = Field(default=1, ge=0, le=1000)
    min_exchange_volume_rub: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    min_rounds_for_prize: int = Field(default=1, ge=0, le=1000)
    max_participants: int = Field(default=500, ge=2, le=100000)
    min_participants: int = Field(default=2, ge=2, le=100000)
    allowed_games: list[str] = Field(default_factory=list, max_length=20)


class TournamentPatch(TournamentUpsert):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, max_length=140)
    status: Optional[str] = Field(default=None, pattern="^(draft|registration|active|finished|cancelled)$")


class TournamentBlockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(ge=1)
    blocked: bool = True


def _tournament_payload(body: BaseModel, *, exclude_unset: bool = False) -> dict:
    data = body.model_dump(exclude_unset=exclude_unset, exclude_none=exclude_unset)
    places = data.get("prize_places")
    if places is not None:
        data["prize_places"] = [dict(item) for item in places]
    return data


@router.get("/casino/tournaments")
async def list_casino_tournaments(admin=Depends(get_current_finance_owner)):
    from casino_tournaments import admin_list, ensure_closer

    _admin_id(admin)
    ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {"tournaments": await admin_list(conn)}


@router.post("/casino/tournaments", status_code=201)
async def create_casino_tournament(body: TournamentUpsert, admin=Depends(get_current_finance_owner)):
    from casino_tournaments import admin_list, create_tournament

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                row = await create_tournament(conn, _tournament_payload(body))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tournament_id": int(row["id"]), "tournaments": await admin_list(conn)}


@router.patch("/casino/tournaments/{tournament_id}")
async def patch_casino_tournament(
    tournament_id: int, body: TournamentPatch, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import admin_list, update_tournament

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await update_tournament(
                    conn, int(tournament_id), _tournament_payload(body, exclude_unset=True)
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"tournaments": await admin_list(conn)}


@router.post("/casino/tournaments/{tournament_id}/status/{status}")
async def set_casino_tournament_status(
    tournament_id: int, status: str, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import admin_list, ensure_closer, set_status

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await set_status(conn, int(tournament_id), status)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        ensure_closer()
        return {"tournaments": await admin_list(conn)}


@router.get("/casino/tournaments/{tournament_id}/participants")
async def list_casino_tournament_participants(
    tournament_id: int, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import admin_participants, snapshot

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {
            "participants": await admin_participants(conn, int(tournament_id)),
            "bracket": await snapshot(conn, tournament_id=int(tournament_id), viewer_id=None),
        }


@router.post("/casino/tournaments/{tournament_id}/block")
async def block_casino_tournament_participant(
    tournament_id: int, body: TournamentBlockBody, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import admin_participants, block_participant

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await block_participant(conn, int(tournament_id), body.user_id, body.blocked)
        return {"participants": await admin_participants(conn, int(tournament_id))}


class TournamentAccessBody(BaseModel):
    """Персональный доступ: Telegram ID или @username."""

    model_config = ConfigDict(extra="forbid")
    identity: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=300)


async def _resolve_bot_user(conn, identity: str) -> int:
    raw = (identity or "").strip().lstrip("@")
    if not raw:
        raise HTTPException(status_code=400, detail="Укажите Telegram ID или @username")
    if raw.isdigit():
        return int(raw)
    user_id = await conn.fetchval(
        "SELECT user_id FROM bot_users WHERE LOWER(username) = LOWER($1) LIMIT 1",
        raw,
    )
    if not user_id:
        raise HTTPException(status_code=404, detail=f"Пользователь @{raw} не найден")
    return int(user_id)


@router.get("/casino/tournaments/{tournament_id}/access")
async def list_casino_tournament_access(
    tournament_id: int, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import list_access

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return {"access": await list_access(conn, int(tournament_id))}


@router.post("/casino/tournaments/{tournament_id}/access")
async def grant_casino_tournament_access(
    tournament_id: int, body: TournamentAccessBody, admin=Depends(get_current_finance_owner)
):
    """Открыть вход конкретному юзеру без истории обменов."""
    from casino_tournaments import grant_access, list_access

    admin_id = _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = await _resolve_bot_user(conn, body.identity)
            await grant_access(
                conn,
                tournament_id=int(tournament_id),
                user_id=user_id,
                note=body.note,
                granted_by=admin_id,
            )
        return {"user_id": user_id, "access": await list_access(conn, int(tournament_id))}


@router.delete("/casino/tournaments/{tournament_id}/access/{user_id}")
async def revoke_casino_tournament_access(
    tournament_id: int, user_id: int, admin=Depends(get_current_finance_owner)
):
    from casino_tournaments import list_access, revoke_access

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await revoke_access(conn, tournament_id=int(tournament_id), user_id=int(user_id))
        return {"access": await list_access(conn, int(tournament_id))}


class BonusWalletGrantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_id: int = Field(gt=0)
    chips: float = Field(gt=0, le=1_000_000)
    note: str = Field(default="", max_length=300)


@router.get("/casino/bonus-wallet/{telegram_id}")
async def get_casino_bonus_wallet(telegram_id: int, admin=Depends(get_current_finance_owner)):
    """Бонусный кошелёк игрока: баланс фишек и последние движения."""
    from casino_wallet import ensure_bonus_wallet

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        wallet = await ensure_bonus_wallet(conn, int(telegram_id))
        rows = await conn.fetch(
            """
            SELECT kind, amount_chips, order_id, game_id, note, created_at
            FROM casino_bonus_ledger
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT 50
            """,
            int(telegram_id),
        )
        return {
            "telegram_id": int(telegram_id),
            "chips_balance": float(wallet.get("chips_balance") or 0),
            "granted_total": float(wallet.get("granted_total") or 0),
            "total_wagered_chips": float(wallet.get("total_wagered_chips") or 0),
            "rounds_played": int(wallet.get("rounds_played") or 0),
            "wins_count": int(wallet.get("wins_count") or 0),
            "blocked": bool(wallet.get("blocked")),
            "ledger": [
                {
                    "kind": str(row["kind"]),
                    "amount_chips": float(row["amount_chips"]),
                    "order_id": str(row["order_id"]),
                    "game_id": str(row["game_id"] or ""),
                    "note": str(row["note"] or ""),
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }


@router.post("/casino/bonus-wallet/grant")
async def grant_casino_bonus_wallet(
    body: BonusWalletGrantBody, admin=Depends(get_current_finance_owner)
):
    """Выдать бонусные фишки игроку. Идемпотентно по admin+игрок+сумма+время."""
    from decimal import Decimal as _Decimal

    from casino_wallet import bonus_order_ref, grant_bonus_chips

    admin_id = _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            seq = int(
                await conn.fetchval(
                    "SELECT COUNT(*) FROM casino_bonus_ledger WHERE user_id = $1 AND kind = 'grant'",
                    int(body.telegram_id),
                )
                or 0
            )
            order_id = bonus_order_ref("admin", f"{body.telegram_id}:{seq + 1}")
            balance = await grant_bonus_chips(
                conn,
                user_id=int(body.telegram_id),
                amount_chips=_Decimal(str(body.chips)),
                order_id=order_id,
                note=body.note or f"Выдача админом {admin_id}",
            )
        return {
            "success": True,
            "telegram_id": int(body.telegram_id),
            "chips_balance": float(balance),
        }


@router.get("/casino/bot-status")
async def get_casino_bot_status(admin=Depends(get_current_finance_owner)):

    """Живой статус casino-бота для панели: username и deep-link (секреты не отдаём)."""

    _admin_id(admin)

    username = (app_settings.casino_bot_username or "").strip().lstrip("@")

    configured = bool(username)

    return {

        "configured": configured,

        "username": username or None,

        "deep_link": f"https://t.me/{username}" if configured else None,

    }





@router.post("/casino/chat-binding/confirm", response_model=GameChatBindingResponse)

async def confirm_game_chat_binding(body: GameChatBindingAction, admin=Depends(get_current_finance_owner)):

    """Atomically replace the active PVP chat with an approved pending request."""

    admin_id = _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            await conn.execute("SELECT pg_advisory_xact_lock(741921)")

            target = await conn.fetchrow(

                """

                SELECT id FROM casino_game_chat_bindings

                WHERE id = $1 AND status = 'pending'

                FOR UPDATE

                """,

                body.binding_id,

            )

            if not target:

                raise HTTPException(status_code=409, detail="Pending game chat binding not found")

            await conn.execute(

                """

                UPDATE casino_game_chat_bindings

                SET status = 'disabled', disabled_by_admin_id = $1,

                    disabled_at = now(), updated_at = now()

                WHERE status = 'active' AND id <> $2

                """,

                admin_id,

                body.binding_id,

            )

            row = await conn.fetchrow(

                """

                UPDATE casino_game_chat_bindings

                SET status = 'active', confirmed_by_admin_id = $1,

                    confirmed_at = now(), disabled_by_admin_id = NULL,

                    disabled_at = NULL, updated_at = now()

                WHERE id = $2

                RETURNING id, chat_id, chat_type, chat_title, telegram_url, status, requested_by_telegram_id,

                          created_at, updated_at, confirmed_at, disabled_at

                """,

                admin_id,

                body.binding_id,

            )

    return dict(row)





@router.post("/casino/chat-binding/disable", response_model=GameChatBindingResponse)

async def disable_game_chat_binding(body: GameChatBindingAction, admin=Depends(get_current_finance_owner)):

    """Disable a requested or active PVP chat binding."""

    admin_id = _admin_id(admin)

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            await conn.execute("SELECT pg_advisory_xact_lock(741921)")

            row = await conn.fetchrow(

                """

                UPDATE casino_game_chat_bindings

                SET status = 'disabled', disabled_by_admin_id = $1,

                    disabled_at = now(), updated_at = now()

                WHERE id = $2 AND status IN ('pending', 'active')

                RETURNING id, chat_id, chat_type, chat_title, telegram_url, status, requested_by_telegram_id,

                          created_at, updated_at, confirmed_at, disabled_at

                """,

                admin_id,

                body.binding_id,

            )

    if not row:

        raise HTTPException(status_code=404, detail="Game chat binding not found or already disabled")

    return dict(row)





@router.get("/casino/dashboard", response_model=CasinoDashboard)
async def get_casino_dashboard(admin=Depends(get_current_admin)):
    """Overall casino metrics. Turnover is player handle only (bot stakes excluded)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        lifetime = await fetch_casino_stats(conn)
        today = today_moscow()
        today_stats = await fetch_casino_stats(conn, today, today)
        return CasinoDashboard(**dashboard_from_stats(lifetime, today_stats))


@router.get("/casino/stats", response_model=CasinoStats)
async def get_casino_stats(
    admin=Depends(get_current_admin),
    date_from: date | None = Query(None, description="YYYY-MM-DD inclusive"),
    date_to: date | None = Query(None, description="YYYY-MM-DD inclusive"),
):
    """Period casino stats: handle, GGR, NGR, hold, RTP, breakdown, daily, players."""
    if (date_from is None) ^ (date_to is None):
        raise HTTPException(status_code=422, detail="date_from and date_to must be sent together")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await fetch_casino_stats(conn, date_from, date_to)


@router.post("/casino/clans/{clan_id}/disband")
async def admin_disband_clan(clan_id: int, admin=Depends(get_current_admin)):
    """Force-disband a clan. Members keep already attributed weekly wager."""
    actor_id = _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await clans_disband(conn, actor_id=actor_id, as_admin=True, clan_id=clan_id)


@router.get("/casino/risk")
async def get_casino_risk(
    admin=Depends(get_current_admin),
    window: str = Query("7d"),
    rtp_deviation_pp: float = Query(15, gt=0, le=100),
):
    """Bankroll, RTP corridor, open exposure, anomalies, and top winners/losers."""
    _admin_id(admin)
    if window not in WINDOWS:
        raise HTTPException(status_code=422, detail="window must be 24h, 7d, or 30d")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            return await fetch_risk_snapshot(conn, window=window, deviation_pp=rtp_deviation_pp)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/casino/players/{player_id}/profile")
async def get_casino_player_profile(
    player_id: int,
    admin=Depends(get_current_admin),
):
    from casino_client_profile import SCOPE_ADMIN, build_casino_client_profile

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await build_casino_client_profile(conn, player_id, scope=SCOPE_ADMIN)


@router.get("/casino/players/{player_id}/history")
async def get_casino_player_history(
    player_id: int,
    admin=Depends(get_current_admin),
    before: str | None = Query(None),
    game_type: str | None = Query(None),
):
    from casino_client_profile import load_casino_client_history

    _admin_id(admin)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await load_casino_client_history(
            conn,
            player_id,
            before=before,
            game_type=game_type,
        )


@router.get("/casino/games", response_model=list[CasinoGameListItem])

async def get_casino_games(

    admin=Depends(get_current_admin),

    game_type: Optional[str] = Query(None, description="Filter by game type"),

    status: Optional[str] = Query(None, description="Filter by status"),

    player_id: Optional[int] = Query(None, description="Filter by player telegram_id"),

    limit: int = Query(50, ge=1, le=500),

    offset: int = Query(0, ge=0),

):

    """

    Get paginated list of casino games with filters.



    Filters:

    - game_type: pvp, baccara, blackjack, raffle

    - status: active, finished, cancelled

    - player_id: telegram_id of player involved

    """

    pool = await get_pool()

    async with pool.acquire() as conn:

        conditions = ["TRUE"]

        params = []

        param_idx = 1



        if game_type:

            conditions.append(f"game_type = ${param_idx}")

            params.append(game_type)

            param_idx += 1



        if status:

            conditions.append(f"status = ${param_idx}")

            params.append(status)

            param_idx += 1



        if player_id:

            conditions.append(f"(creator_id = ${param_idx} OR opponent_id = ${param_idx})")

            params.append(player_id)

            param_idx += 1



        where_clause = " AND ".join(conditions)



        rows = await conn.fetch(f"""

            SELECT

                id, game_id, game_type, created_at, finished_at, status,

                creator_id, opponent_id, bet_rub, winner_id, commission_rub

            FROM casino_games

            WHERE {where_clause}

            ORDER BY created_at DESC

            LIMIT ${param_idx} OFFSET ${param_idx + 1}

        """, *params, limit, offset)



        games = []

        for row in rows:

            # Build players array

            players = [row["creator_id"]]

            if row["opponent_id"]:

                players.append(row["opponent_id"])



            # Get commission breakdown

            commission_rows = await conn.fetch("""

                SELECT recipient_type, SUM(amount_rub) as total

                FROM casino_commission_ledger

                WHERE game_id = $1

                GROUP BY recipient_type

            """, row["id"])



            commission_map = {r["recipient_type"]: float(r["total"]) for r in commission_rows}



            games.append(CasinoGameListItem(

                game_id=row["game_id"],

                game_type=row["game_type"],

                created_at=row["created_at"],

                finished_at=row["finished_at"],

                status=row["status"],

                players=players,

                bet_amount_rub=float(row["bet_rub"]),

                winner_id=row["winner_id"],

                commission_rub=float(row["commission_rub"]),

                creator_cut_rub=commission_map.get("creator", 0.0),

                owner_cut_rub=commission_map.get("owner", 0.0),

            ))



        return games





@router.get("/casino/games/{game_id}", response_model=CasinoGameDetail)

async def get_casino_game_detail(game_id: str, admin=Depends(get_current_admin)):

    """Get detailed info for a single casino game including full game_data."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        row = await conn.fetchrow("""

            SELECT

                id, game_id, game_type, created_at, finished_at, status,

                creator_id, opponent_id, bet_rub, winner_id, commission_rub, game_data

            FROM casino_games

            WHERE game_id = $1

        """, game_id)



        if not row:

            raise HTTPException(404, "Game not found")



        # Build players array

        players = [row["creator_id"]]

        if row["opponent_id"]:

            players.append(row["opponent_id"])



        # Commission breakdown

        commission_rows = await conn.fetch("""

            SELECT recipient_type, SUM(amount_rub) as total

            FROM casino_commission_ledger

            WHERE game_id = $1

            GROUP BY recipient_type

        """, row["id"])



        commission_map = {r["recipient_type"]: float(r["total"]) for r in commission_rows}



        return CasinoGameDetail(

            game_id=row["game_id"],

            game_type=row["game_type"],

            created_at=row["created_at"],

            finished_at=row["finished_at"],

            status=row["status"],

            players=players,

            bet_amount_rub=float(row["bet_rub"]),

            winner_id=row["winner_id"],

            commission_rub=float(row["commission_rub"]),

            creator_cut_rub=commission_map.get("creator", 0.0),

            owner_cut_rub=commission_map.get("owner", 0.0),

            game_data=row["game_data"] or {},

        )





@router.get("/casino/settings", response_model=CasinoSettingsResponse)

async def get_casino_settings(admin=Depends(get_current_admin)):

    """Get current casino configuration."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        rows = await conn.fetch("SELECT key, value FROM casino_settings")

        return _settings_response({row["key"]: row["value"] for row in rows})


@router.get("/casino/settings/audit", response_model=CasinoSettingsAuditList)
async def list_casino_settings_audit(
    admin=Depends(get_current_admin),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    window: str | None = Query(None),
    key: str | None = Query(None),
    changed_by: str | None = Query(None),
    q: str | None = Query(None),
    batch_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _admin_id(admin)
    if not isinstance(window, str):
        window = None
    if not isinstance(q, str):
        q = None
    if not isinstance(batch_id, UUID):
        batch_id = None
    if window is not None and window not in WINDOW_SQL:
        raise HTTPException(status_code=422, detail="window must be 24h, 7d, or 30d")
    clauses = ["TRUE"]
    args: list[object] = []

    def _add(clause: str, value: object) -> None:
        args.append(value)
        clauses.append(clause.replace("?", f"${len(args)}"))

    if window is not None:
        clauses.append(f"changed_at > now() - interval '{WINDOW_SQL[window]}'")
    else:
        if date_from is not None:
            _add("changed_at >= ?::date", date_from)
        if date_to is not None:
            _add("changed_at < (?::date + INTERVAL '1 day')", date_to)
    if key:
        _add("key = ?", key)
    if changed_by:
        _add("changed_by = ?", changed_by)
    if batch_id is not None:
        _add("batch_id = ?", batch_id)
    q_text = (q or "").strip()
    if q_text:
        args.append(q_text.lower())
        needle = f"${len(args)}"
        clauses.append(
            "("
            f"strpos(lower(key), {needle}) > 0 OR "
            f"strpos(lower(reason), {needle}) > 0 OR "
            f"strpos(lower(changed_by), {needle}) > 0 OR "
            f"strpos(lower(COALESCE(old_value::text, '')), {needle}) > 0 OR "
            f"strpos(lower(new_value::text), {needle}) > 0"
            ")"
        )

    where_sql = " AND ".join(clauses)
    args.extend([limit, offset])
    limit_placeholder = f"${len(args) - 1}"
    offset_placeholder = f"${len(args)}"

    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM casino_settings_audit WHERE {where_sql}",
            *args[:-2],
        )
        rows = await conn.fetch(
            f"""
            SELECT id, batch_id, key, old_value, new_value, changed_by, changed_at, reason
            FROM casino_settings_audit
            WHERE {where_sql}
            ORDER BY changed_at DESC, id DESC
            LIMIT {limit_placeholder} OFFSET {offset_placeholder}
            """,
            *args,
        )

    return CasinoSettingsAuditList(
        total=int(total or 0),
        items=[
            CasinoSettingsAuditRow(
                id=row["id"],
                batch_id=row["batch_id"],
                key=row["key"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                changed_by=row["changed_by"],
                changed_at=row["changed_at"],
                reason=row["reason"],
            )
            for row in rows
        ],
    )


@router.patch("/casino/settings", response_model=CasinoSettingsResponse)

async def update_casino_settings(

    update: CasinoSettingsUpdate,

    admin=Depends(get_current_admin)

):

    """

    Update casino settings.



    Only provided fields are updated; others remain unchanged.

    Validates that percentages sum correctly.

    """

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            rows = await conn.fetch("SELECT key, value FROM casino_settings")

            stored = {row["key"]: row["value"] for row in rows}

            current = _settings_response(stored)

            patch = update.model_dump(exclude_unset=True)

            reason = str(patch.pop("reason", "") or "").strip()

            if not reason:

                raise HTTPException(

                    status_code=422,

                    detail="reason is required",

                )

            unknown_keys = [key for key in patch if not is_known_key(key)]

            if unknown_keys:

                raise HTTPException(

                    status_code=400,

                    detail=f"Unknown casino setting key: {unknown_keys[0]}",

                )



            commission_rate = patch.get("commission_rate", current.commission_rate)

            creator_share = patch.get("creator_cut_percent", current.creator_cut_percent)

            referral_l1_share = patch.get("referral_l1_percent", current.referral_l1_percent)

            referral_l2_share = patch.get("referral_l2_percent", current.referral_l2_percent)

            if creator_share + referral_l1_share + referral_l2_share > commission_rate:

                raise HTTPException(

                    status_code=422,

                    detail="Creator and referral shares cannot exceed the commission rate",

                )



            active_rate = patch.get("commission_rate_wagering_active", current.commission_rate_wagering_active)

            active_shares = (

                patch.get("creator_cut_percent_wagering_active", current.creator_cut_percent_wagering_active),

                patch.get("referral_l1_percent_wagering_active", current.referral_l1_percent_wagering_active),

                patch.get("referral_l2_percent_wagering_active", current.referral_l2_percent_wagering_active),

            )

            if sum(active_shares) > active_rate:

                raise HTTPException(

                    status_code=422,

                    detail="Active wagering shares cannot exceed its commission rate",

                )



            complete_rate = patch.get("commission_rate_wagering_complete", current.commission_rate_wagering_complete)

            complete_shares = (

                patch.get("creator_cut_percent_wagering_complete", current.creator_cut_percent_wagering_complete),

                patch.get("referral_l1_percent_wagering_complete", current.referral_l1_percent_wagering_complete),

                patch.get("referral_l2_percent_wagering_complete", current.referral_l2_percent_wagering_complete),

            )

            if sum(complete_shares) > complete_rate:

                raise HTTPException(

                    status_code=422,

                    detail="Complete wagering shares cannot exceed its commission rate",

                )



            min_bet = patch.get("min_bet_rub", current.min_bet_rub)

            max_bet = patch.get("max_bet_rub", current.max_bet_rub)

            if min_bet > max_bet:

                raise HTTPException(

                    status_code=422,

                    detail="min_bet_rub cannot exceed max_bet_rub",

                )



            holdem_sb = patch.get("holdem_small_blind_rub", current.holdem_small_blind_rub)

            holdem_bb = patch.get("holdem_big_blind_rub", current.holdem_big_blind_rub)

            if holdem_sb > holdem_bb:

                raise HTTPException(

                    status_code=422,

                    detail="holdem_small_blind_rub cannot exceed holdem_big_blind_rub",

                )

            holdem_min_bb = patch.get("holdem_min_buyin_bb", current.holdem_min_buyin_bb)

            holdem_max_bb = patch.get("holdem_max_buyin_bb", current.holdem_max_buyin_bb)

            if holdem_min_bb > holdem_max_bb:

                raise HTTPException(

                    status_code=422,

                    detail="holdem_min_buyin_bb cannot exceed holdem_max_buyin_bb",

                )



            if "enabled_games" in patch and patch["enabled_games"] is not None:

                patch["enabled_games"] = {

                    **current.enabled_games,

                    **patch["enabled_games"],

                }



            if "provably_fair_enabled" in patch and patch["provably_fair_enabled"] is not None:

                patch["provably_fair_enabled"] = {

                    **current.provably_fair_enabled,

                    **patch["provably_fair_enabled"],

                }



            # Базовый профиль = активный профиль отыгрыша (единый источник для бота и fallback).
            patch["commission_rate"] = active_rate
            patch["creator_cut_percent"] = active_shares[0]
            patch["referral_l1_percent"] = active_shares[1]
            patch["referral_l2_percent"] = active_shares[2]

            try:
                if patch.get("commission_volume_tiers") is not None:
                    commission_rows = [_setting_row_dict(row) for row in patch["commission_volume_tiers"]]
                    parse_commission_volume_tiers(commission_rows)
                    patch["commission_volume_tiers"] = commission_rows
                elif "commission_rate_wagering_active" in patch or "commission_rate_wagering_complete" in patch:
                    base_rows = [_setting_row_dict(row) for row in current.commission_volume_tiers]
                    if base_rows:
                        base_rows[0]["active_rate"] = active_rate
                        base_rows[0]["complete_rate"] = complete_rate
                        patch["commission_volume_tiers"] = base_rows

                if patch.get("cashback_volume_tiers") is not None:
                    cashback_rows = [_setting_row_dict(row) for row in patch["cashback_volume_tiers"]]
                    parse_cashback_volume_tiers(cashback_rows)
                    patch["cashback_volume_tiers"] = cashback_rows
                if patch.get("level_reach_bonuses") is not None:
                    from casino_level_bonus import parse_level_reach_bonuses, bonuses_to_public

                    bonus_rows = [_setting_row_dict(row) for row in patch["level_reach_bonuses"]]
                    patch["level_reach_bonuses"] = bonuses_to_public(parse_level_reach_bonuses(bonus_rows))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            if patch.get("commission_volume_tiers") is not None and "commission_rate_wagering_active" not in patch:
                first_tier = _setting_row_dict(patch["commission_volume_tiers"][0])
                patch["commission_rate_wagering_active"] = first_tier["active_rate"]
                patch["commission_rate_wagering_complete"] = first_tier["complete_rate"]



            updated_by = _admin_username(admin)
            batch_id = uuid.uuid4()

            for key, value in patch.items():

                if not is_known_key(key):

                    raise HTTPException(status_code=400, detail=f"Unknown casino setting key: {key}")

                if hasattr(value, "model_dump"):
                    value = value.model_dump()
                elif isinstance(value, list):
                    value = [row.model_dump() if hasattr(row, "model_dump") else row for row in value]
                elif isinstance(value, dict):
                    value = {
                        inner_key: (
                            inner.model_dump() if hasattr(inner, "model_dump") else inner
                        )
                        for inner_key, inner in value.items()
                    }
                try:
                    json_value = to_storage(key, value)
                    validate_value(key, json_value)
                except (UnknownSettingKey, SettingValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc



                await conn.execute("""

                    INSERT INTO casino_settings (key, value, updated_at, updated_by)

                    VALUES ($1, $2::jsonb, NOW(), $3)

                    ON CONFLICT (key) DO UPDATE

                    SET value = $2::jsonb, updated_at = NOW(), updated_by = $3

                """, key, json.dumps(json_value), updated_by)

                previous = stored.get(key)
                if _setting_fingerprint(previous) != _setting_fingerprint(json_value):
                    await conn.execute(
                        """
                        INSERT INTO casino_settings_audit
                            (batch_id, key, old_value, new_value, changed_by, reason)
                        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
                        """,
                        batch_id,
                        key,
                        None if previous is None else json.dumps(previous),
                        json.dumps(json_value),
                        updated_by,
                        reason,
                    )
                    stored[key] = json_value



            rows = await conn.fetch("SELECT key, value FROM casino_settings")

            result = _settings_response({row["key"]: row["value"] for row in rows})



    logger.info(

        "Admin %s updated %d casino setting(s)",

        _admin_id(admin),

        len(patch),

    )

    return result





def _creator_account_response(row: dict) -> CreatorAccountResponse:

    data = dict(row)

    return CreatorAccountResponse(**data, ref_link=web_ref_link(str(data["ref_token"])))





@router.get("/casino/creator/current", response_model=Optional[CreatorAccountResponse])

async def get_current_creator_account(admin=Depends(get_current_admin)):

    """Получить единственный активный creator account."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        row = await conn.fetchrow(

            """

            SELECT cca.id, cca.web_user_id, wu.username,

                   wu.display_name, cca.ref_token, cca.assigned_at

            FROM casino_creator_accounts cca

            JOIN web_users wu ON wu.id = cca.web_user_id

            WHERE cca.is_active = TRUE

            ORDER BY cca.assigned_at DESC, cca.id DESC

            LIMIT 1

            """

        )

    return _creator_account_response(row) if row else None





@router.post("/casino/creator/assign", response_model=CreatorAccountResponse)

async def assign_creator_account(

    body: CreatorAccountAssignRequest,

    admin=Depends(get_current_admin),

):

    """Назначить web-user создателем, безопасно отозвав предыдущее назначение."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            user = await conn.fetchrow(

                "SELECT id FROM web_users WHERE id = $1", body.web_user_id

            )

            if not user:

                raise HTTPException(status_code=404, detail="Web user not found")

            admin_id = _admin_id(admin)

            await conn.execute(

                """

                UPDATE casino_creator_accounts

                SET is_active = FALSE, revoked_at = now(), revoked_by = $1

                WHERE is_active = TRUE AND web_user_id <> $2

                """,

                admin_id, body.web_user_id,

            )

            row = await conn.fetchrow(

                """

                INSERT INTO casino_creator_accounts (web_user_id, ref_token, assigned_by)

                VALUES ($1, $2, $3)

                ON CONFLICT (web_user_id) WHERE is_active DO UPDATE

                SET revoked_at = NULL, revoked_by = NULL

                RETURNING id, web_user_id, ref_token, assigned_at

                """,

                body.web_user_id, generate_ref_token(), admin_id,

            )

            account = await conn.fetchrow(

                """

                SELECT cca.id, cca.web_user_id, wu.username,

                       wu.display_name, cca.ref_token, cca.assigned_at

                FROM casino_creator_accounts cca

                JOIN web_users wu ON wu.id = cca.web_user_id

                WHERE cca.id = $1

                """,

                row["id"],

            )

    logger.info("Admin %s assigned casino creator account %s", _admin_id(admin), body.web_user_id)

    return _creator_account_response(account)





@router.post("/casino/creator/revoke")

async def revoke_creator_account(admin=Depends(get_current_admin)):

    """Отозвать текущий creator account без удаления финансовой истории."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        row = await conn.fetchrow(

            """

            UPDATE casino_creator_accounts

            SET is_active = FALSE, revoked_at = now(), revoked_by = $1

            WHERE id = (

                SELECT id FROM casino_creator_accounts

                WHERE is_active = TRUE ORDER BY assigned_at DESC, id DESC LIMIT 1

            )

            RETURNING id

            """,

            _admin_id(admin),

        )

    if not row:

        raise HTTPException(status_code=404, detail="No active casino creator account")

    logger.info("Admin %s revoked casino creator account %s", _admin_id(admin), row["id"])

    return {"success": True}





@router.get("/casino/creator/withdrawals", response_model=list[CreatorWithdrawalListItem])

async def get_creator_withdrawals(

    admin=Depends(get_current_admin),

    status: Optional[str] = Query(None, description="Filter by status: pending/approved/rejected"),

):

    """

    Get creator withdrawal requests for admin review.



    Defaults to showing pending requests.

    """

    pool = await get_pool()

    async with pool.acquire() as conn:

        if status:

            rows = await conn.fetch("""

                SELECT

                    id AS withdrawal_id,

                    created_at,

                    amount_rub,

                    method,

                    requisites,

                    status,

                    processed_at,

                    processed_by_username AS processed_by_admin_id,

                    tx_hash,

                    reject_reason AS rejection_reason

                FROM casino_creator_withdrawals

                WHERE status = $1

                ORDER BY created_at DESC

            """, status)

        else:

            # Default: show pending first, then recent processed

            rows = await conn.fetch("""

                SELECT

                    id AS withdrawal_id,

                    created_at,

                    amount_rub,

                    method,

                    requisites,

                    status,

                    processed_at,

                    processed_by_username AS processed_by_admin_id,

                    tx_hash,

                    reject_reason AS rejection_reason

                FROM casino_creator_withdrawals

                ORDER BY

                    CASE WHEN status = 'pending' THEN 0 ELSE 1 END,

                    created_at DESC

                LIMIT 100

            """)



        return [

            CreatorWithdrawalListItem(

                withdrawal_id=row["withdrawal_id"],

                created_at=row["created_at"],

                amount_rub=float(row["amount_rub"]),

                method=row["method"],

                requisites=row["requisites"],

                status=row["status"],

                processed_at=row["processed_at"],

                processed_by_admin_id=row["processed_by_admin_id"],

                tx_hash=row["tx_hash"],

                rejection_reason=row["rejection_reason"],

            )

            for row in rows

        ]





async def _lock_creator_withdrawal_balance(conn, withdrawal: object):

    """Lock the only balance row that may settle a pending creator withdrawal."""

    account_id = withdrawal["creator_account_id"]

    telegram_id = withdrawal["telegram_id"]

    balance = await conn.fetchrow(

        """

        SELECT creator_account_id, telegram_id

        FROM casino_creator_balance

        WHERE creator_account_id = $1

           OR ($1 IS NULL AND telegram_id = $2)

        FOR UPDATE

        """,

        account_id,

        telegram_id,

    )

    if not balance:

        raise HTTPException(status_code=409, detail="Creator balance integrity error")

    return balance





async def _execute_exactly_one(conn, query: str, *args):

    result = await conn.execute(query, *args)

    if result != "UPDATE 1":

        raise HTTPException(status_code=409, detail="Creator balance integrity error")





async def _update_creator_balance(

    conn,

    balance: object,

    withdrawal: object,

    *,

    field: str,

):

    if balance["creator_account_id"] is not None:

        await _execute_exactly_one(

            conn,

            f"""

            UPDATE casino_creator_balance

            SET {field} = {field} + $1,

                updated_at = NOW()

            WHERE creator_account_id = $2

            """,

            withdrawal["amount_rub"],

            balance["creator_account_id"],

        )

        return



    if withdrawal["creator_account_id"] is not None or balance["telegram_id"] is None:

        raise HTTPException(status_code=409, detail="Creator balance integrity error")

    await _execute_exactly_one(

        conn,

        f"""

        UPDATE casino_creator_balance

        SET {field} = {field} + $1,

            updated_at = NOW()

        WHERE telegram_id = $2

        """,

        withdrawal["amount_rub"],

        balance["telegram_id"],

    )





@router.post("/casino/creator/withdrawals/{withdrawal_id}/approve")

async def approve_creator_withdrawal(

    withdrawal_id: int,

    approval: WithdrawalApproval,

    admin=Depends(get_current_admin)

):

    """Approve a pending withdrawal after updating its locked creator balance."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow("""

                SELECT id, creator_account_id, telegram_id, amount_rub, status

                FROM casino_creator_withdrawals

                WHERE id = $1

                FOR UPDATE

            """, withdrawal_id)



            if not row:

                raise HTTPException(404, "Withdrawal not found")

            if row["status"] != "pending":

                raise HTTPException(409, f"Withdrawal already {row['status']}")



            balance = await _lock_creator_withdrawal_balance(conn, row)

            await _update_creator_balance(

                conn,

                balance,

                row,

                field="total_withdrawn_rub",

            )

            await _execute_exactly_one(

                conn,

                """

                UPDATE casino_creator_withdrawals

                SET status = 'approved',

                    processed_at = NOW(),

                    processed_by_username = $1,

                    tx_hash = $2

                WHERE id = $3 AND status = 'pending'

                """,

                _admin_username(admin),

                approval.tx_hash,

                withdrawal_id,

            )



    logger.info(

        "Admin %s approved creator withdrawal %s",

        _admin_id(admin),

        withdrawal_id,

    )

    return {"success": True, "message": "Withdrawal approved"}





@router.post("/casino/creator/withdrawals/{withdrawal_id}/reject")

async def reject_creator_withdrawal(

    withdrawal_id: int,

    rejection: WithdrawalRejection,

    admin=Depends(get_current_admin)

):

    """Reject a pending withdrawal and refund its locked creator balance."""

    pool = await get_pool()

    async with pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow("""

                SELECT id, creator_account_id, telegram_id, amount_rub, status

                FROM casino_creator_withdrawals

                WHERE id = $1

                FOR UPDATE

            """, withdrawal_id)



            if not row:

                raise HTTPException(404, "Withdrawal not found")

            if row["status"] != "pending":

                raise HTTPException(409, f"Withdrawal already {row['status']}")



            balance = await _lock_creator_withdrawal_balance(conn, row)

            await _update_creator_balance(conn, balance, row, field="balance_rub")

            await _execute_exactly_one(

                conn,

                """

                UPDATE casino_creator_withdrawals

                SET status = 'rejected',

                    processed_at = NOW(),

                    processed_by_username = $1,

                    reject_reason = $2

                WHERE id = $3 AND status = 'pending'

                """,

                _admin_username(admin),

                rejection.reason,

                withdrawal_id,

            )



    logger.info(

        "Admin %s rejected creator withdrawal %s",

        _admin_id(admin),

        withdrawal_id,

    )

    return {"success": True, "message": "Withdrawal rejected, amount refunded"}





@router.get("/casino/chart")
async def get_casino_chart_data(
    admin=Depends(get_current_admin),
    days: int = Query(30, ge=1, le=365, description="Number of days to fetch"),
):
    """Daily handle / GGR / owner profit for the last `days` Moscow calendar days."""
    pool = await get_pool()
    d_to = today_moscow()
    d_from = d_to - timedelta(days=days - 1)
    async with pool.acquire() as conn:
        stats = await fetch_casino_stats(conn, d_from, d_to)
        return chart_from_stats(stats)

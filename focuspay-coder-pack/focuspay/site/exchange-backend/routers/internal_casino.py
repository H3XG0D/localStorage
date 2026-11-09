"""Internal Casino API: атомарные холды и финансовое завершение игр."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse
from decimal import Decimal
from typing import Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from casino_cards import (
    CARD_COMMIT_TTL,
    CARD_GAME_TYPES,
    CARD_SHUFFLE_ALGORITHM,
    DEFAULT_CLIENT_SEED,
    MAX_CARD_HAND_SIZE,
    dealt_cards as card_dealt_cards,
    game_commit,
    is_valid_shoe_side,
    pair_commit,
)
from casino_cub_faces import cub_pips_from_rng, cub_presentation_pips
from casino_fairness import (
    get_or_create_fairness_session,
    increment_session_nonce,
    public_fairness_session,
    rotate_fairness_session,
    set_client_seed,
    validate_client_seed,
)
from casino_finance import (
    CommissionAllocation,
    ClientUserId,
    MoneyInput,
    PositiveTelegramId,
    SettlementRequest,
    allocate_commission,
    allocate_legacy_commission,
    calculate_equal_stake_settlement,
    calculate_house_settlement,
    commission_share_profile,
    commission_shares_for_rate,
    game_stake_bounds,
    load_casino_settings,
    casino_ledger_order_ref,
    casino_operation_ref,
    confirm_unified_hold,
    lock_casino_game,
    lock_casino_users,
    money,
    maybe_credit_tournament_payout,
    MAX_BOTS_PER_TABLE,
    release_unified_hold,
    reserve_unified_funds,
    RETIRED_SPORT_GAME_TYPES,
    unified_hold_amount,
)
from casino_wallet import (
    active_scope,
    assert_may_sit_at,
    assert_real_money_only,
    assert_player_may_sit,
    row_scope_of,
    scope_from_row,
    scope_insert_sql,
)
from casino_payout_rail import rail_from_sub_token
from casino_wagering import (
    commission_profile_for_player,
    commission_rate_for_player,
    record_deposit_lock,
    serialize_wagering_progress,
    wagering_progress,
)
from casino_clans import (
    clan_brief_for_user,
    clan_snapshot,
    create_clan,
    disband_clan,
    join_clan,
    kick_member,
    leave_clan,
    list_top as clans_list_top,
    my_clan,
    rotate_invite,
    transfer_owner,
)
from config import settings
from db import get_pool
from user_unified_balance import unified_available

try:
    from casino_cashback_tiers import cashback_amount, cashback_percent_for_wager
    from casino_tier_config import load_tier_config, next_cashback_tier, resolve_cashback_percent, resolve_commission_volume_tier
except (ImportError, ModuleNotFoundError):  # Backward-compatible with pre-tier deployments.
    async def load_tier_config(conn):  # type: ignore[misc]
        raise RuntimeError("casino tier config is unavailable")

    def next_cashback_tier(tiers, wager_rub):  # type: ignore[misc]
        return None

    def resolve_cashback_percent(tiers, wager_rub):  # type: ignore[misc]
        return Decimal("2")

    def cashback_percent_for_wager(total_wager_rub: Decimal | int | float | str) -> Decimal:
        return Decimal("2")

    def cashback_amount(
        total_wager_rub: Decimal | int | float | str,
        eligible_loss_rub: Decimal | int | float | str,
    ) -> Decimal:
        return money(Decimal(str(eligible_loss_rub)) * Decimal("0.02"))


_CASINO_TIMEZONE = ZoneInfo("Europe/Moscow")

router = APIRouter()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BalanceResponse(StrictModel):
    telegram_id: int
    available_rub: Decimal


_CASHBACK_GAME_TYPES = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "cub",
)
_PVP_GAME_TYPES = ("pvp_dice",)


class HoldBalanceRequest(StrictModel):
    telegram_id: PositiveTelegramId
    game_id: str = Field(min_length=1, max_length=64)
    amount_rub: MoneyInput
    role: Literal["player", "creator", "opponent"] = "player"


class ConfirmReleaseRequest(StrictModel):
    hold_id: str = Field(min_length=1, max_length=128)


class PayoutRequest(StrictModel):
    telegram_id: PositiveTelegramId
    game_id: str = Field(min_length=1, max_length=64)
    amount_rub: MoneyInput
    note: str | None = Field(None, max_length=500)


class DepositCreditRequest(StrictModel):
    deal_id: int = Field(gt=0)


class EmptyCommissionRequest(StrictModel):
    """Legacy endpoint accepts no caller-calculated financial values."""


class CasinoSettingsResponse(StrictModel):
    commission_rate: float
    creator_cut_percent: float
    referral_l1_percent: float
    referral_l2_percent: float
    wagering_percent: float
    commission_rate_wagering_active: float
    commission_rate_wagering_complete: float
    creator_cut_percent_wagering_active: float
    referral_l1_percent_wagering_active: float
    referral_l2_percent_wagering_active: float
    creator_cut_percent_wagering_complete: float
    referral_l1_percent_wagering_complete: float
    referral_l2_percent_wagering_complete: float
    min_bet_rub: float
    max_bet_rub: float
    min_withdrawal_rub: float
    enabled_games: dict[str, bool]


class GameChatBindingPendingRequest(StrictModel):
    chat_id: int = Field(lt=0)
    chat_type: Literal["group", "supergroup"]
    chat_title: str | None = Field(default=None, max_length=255)
    telegram_url: str | None = Field(default=None, max_length=255)
    requested_by_telegram_id: PositiveTelegramId

    @field_validator("chat_title")
    @classmethod
    def strip_chat_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("telegram_url")
    @classmethod
    def validate_telegram_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value:
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "t.me"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("telegram_url must be a Telegram HTTPS link")
        path = parsed.path.strip("/")
        valid_public = re.fullmatch(r"[A-Za-z0-9_]{5,32}", path)
        valid_invite = re.fullmatch(r"\+[A-Za-z0-9_-]{16,}", path)
        valid_legacy_invite = re.fullmatch(r"joinchat/[A-Za-z0-9_-]{16,}", path)
        if not (valid_public or valid_invite or valid_legacy_invite):
            raise ValueError("telegram_url must be a public chat or invite link")
        return f"https://t.me/{path}"


class CasinoGameCreateRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    game_type: Literal[
        "pvp_dice", "baccara", "blackjack"
    ]
    creator_id: PositiveTelegramId
    stake_rub: MoneyInput

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CasinoDmPvpCreateRequest(CasinoGameCreateRequest):
    """Create a PVP game from a private chat using the active approved binding."""

    game_type: Literal["pvp_dice"]
    rounds: int = Field(
        default=1,
        validation_alias=AliasChoices("rounds", "rolls"),
        serialization_alias="rounds",
        ge=1,
        le=20,
    )
    publish_to_group: bool = Field(
        default=False,
        description="Whether to publish invitation card to group chat. False for DM-only games.",
    )


class PrepareCubRequest(StrictModel):
    telegram_id: ClientUserId


class CubPlayRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    telegram_id: ClientUserId
    stake_rub: MoneyInput
    house_bot_count: int = Field(default=0, ge=0, le=6)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CubOpenRequest(StrictModel):
    telegram_id: PositiveTelegramId
    stake_rub: MoneyInput


class CubResolveRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    telegram_id: PositiveTelegramId
    player_value: int = Field(ge=1, le=6)
    house_value: int = Field(ge=1, le=6)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class RouletteTableChipBody(StrictModel):
    bet: str = Field(min_length=1, max_length=120)
    amount_rub: MoneyInput


class RouletteTableBetRequest(StrictModel):
    telegram_id: PositiveTelegramId
    notify_chat_id: int
    amount_rub: MoneyInput | None = None
    bet: str | None = Field(default=None, min_length=1, max_length=120)
    chips: list[RouletteTableChipBody] | None = None

    @field_validator("notify_chat_id")
    @classmethod
    def chat_must_be_nonzero(cls, value: int) -> int:
        if int(value) == 0:
            raise ValueError("notify_chat_id must not be 0")
        return int(value)

    @model_validator(mode="after")
    def chips_or_single(self) -> "RouletteTableBetRequest":
        if self.chips:
            if len(self.chips) > 80:
                raise ValueError("too many chips")
            return self
        if self.bet and self.amount_rub is not None:
            return self
        raise ValueError("bet and amount_rub or chips required")


class JackpotBetRequest(StrictModel):
    telegram_id: PositiveTelegramId
    notify_chat_id: int
    amount_rub: MoneyInput

    @field_validator("notify_chat_id")
    @classmethod
    def chat_must_be_nonzero(cls, value: int) -> int:
        if int(value) == 0:
            raise ValueError("notify_chat_id must not be 0")
        return int(value)


class FixedRoomCreateRequest(StrictModel):
    telegram_id: PositiveTelegramId
    stake_rub: MoneyInput
    seat_count: int = Field(ge=2, le=20)


class FixedRoomActorRequest(StrictModel):
    telegram_id: PositiveTelegramId


class CardsPrepareRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    game_type: Literal["baccara", "blackjack"]
    telegram_id: PositiveTelegramId

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CardsDealRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    telegram_id: PositiveTelegramId
    hand_size: int = Field(ge=1, le=MAX_CARD_HAND_SIZE)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CardsRevealRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    telegram_id: PositiveTelegramId

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class V2CardsPrepareRequest(StrictModel):
    telegram_id: PositiveTelegramId
    game_type: Literal["baccara", "blackjack"]


class V2CardsDealRequest(StrictModel):
    telegram_id: PositiveTelegramId
    hand_size: int = Field(ge=1, le=MAX_CARD_HAND_SIZE)
    seat_no: int | None = Field(default=None, ge=1, le=6)
    shoe_side: str | None = None

    @field_validator("shoe_side")
    @classmethod
    def known_shoe_side(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not is_valid_shoe_side(value):
            raise ValueError("invalid shoe side")
        return value


class V2CardsRevealRequest(StrictModel):
    telegram_id: PositiveTelegramId


class FairnessSessionRequest(StrictModel):
    telegram_id: PositiveTelegramId


class FairnessClientSeedRequest(StrictModel):
    telegram_id: PositiveTelegramId
    client_seed: str = Field(min_length=1, max_length=64)

    @field_validator("client_seed")
    @classmethod
    def clean_client_seed(cls, value: str) -> str:
        return validate_client_seed(value)


class CasinoGameJoinRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    opponent_id: PositiveTelegramId

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CasinoGameJoinRobotRequest(StrictModel):
    """Join a waiting PVP game with an eligible house-backed robot."""

    game_id: str = Field(min_length=1, max_length=64)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CasinoGameStateRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    expected_state_version: int = Field(ge=0)
    game_state: dict[str, JsonValue]

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CasinoGameOutcomeRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    winner_id: PositiveTelegramId | None = None
    expected_state_version: int = Field(ge=0)
    outcome: dict[str, JsonValue]

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_outcome_kind(self):
        kind = self.outcome.get("kind")
        if kind not in {"winner", "house_win", "draw", "cancel", "timeout"}:
            raise ValueError("outcome.kind must be winner, house_win, draw, cancel, or timeout")
        if kind == "winner" and self.winner_id is None:
            raise ValueError("winner_id is required for a winner outcome")
        if kind != "winner" and self.winner_id is not None:
            raise ValueError("winner_id is allowed only for a winner outcome")
        return self


class CasinoGameReleaseRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value else None


class CasinoGameDiceRollRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    telegram_id: PositiveTelegramId
    value: int | None = Field(default=None, ge=1, le=6)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class CasinoGameIdRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)

    @field_validator("game_id")
    @classmethod
    def strip_game_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("game_id must not be blank")
        return value


class ClaimRequest(StrictModel):
    worker_id: str = Field(min_length=1, max_length=128)
    limit: int = Field(default=50, ge=1, le=100)
    lease_seconds: int = Field(default=60, ge=10, le=3600)

    @field_validator("worker_id")
    @classmethod
    def strip_worker_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("worker_id must not be blank")
        return value


class RecoveryCompleteRequest(StrictModel):
    game_id: str = Field(min_length=1, max_length=64)
    claim_token: str = Field(min_length=1, max_length=128)

    @field_validator("game_id", "claim_token")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class OutboxCompleteRequest(StrictModel):
    outbox_id: int = Field(gt=0)
    claim_token: str = Field(min_length=1, max_length=128)

    @field_validator("claim_token")
    @classmethod
    def strip_claim_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("claim_token must not be blank")
        return value


class OutboxFailRequest(OutboxCompleteRequest):
    error: str = Field(min_length=1, max_length=1000)
    error_kind: Literal["dm_unavailable", "rate_limited", "temporary"] = "temporary"
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86400)

    @field_validator("error")
    @classmethod
    def strip_error(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("error must not be blank")
        return value


V2_NON_RESUMABLE_EVENT_TYPES = frozenset({"public_settled", "public_cancelled"})
V2_PERSONAL_EVENT_TYPES = frozenset({"settled", "cancelled"})


class NotificationResumeRequest(StrictModel):
    telegram_id: int = Field(gt=0)
    limit: int = Field(default=10, ge=1, le=10)


class InvitationOutboxCompleteRequest(OutboxCompleteRequest):
    telegram_message_id: int = Field(gt=0)


def _verify_internal_token(token: str | None) -> None:
    expected = (settings.internal_api_secret or settings.webhook_secret or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Internal API not configured")
    supplied = (token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")


def _text_money(value: object) -> str:
    return format(money(value or 0), ".2f")


def _snapshot_amount(snapshot: Mapping[str, object], key: str) -> Decimal:
    raw = snapshot.get(key, 0)
    if raw in (None, ""):
        return money(0)
    return money(raw)


def _assert_stake_within_limits(
    settings,
    game_type: str,
    stake: Decimal,
    *,
    payout_multiplier: Decimal | str | int | float = Decimal("2"),
    bankroll_rub: Decimal | str | int | float = Decimal("0"),
) -> None:
    lo, hi = game_stake_bounds(
        settings,
        game_type,
        payout_multiplier=payout_multiplier,
        bankroll_rub=bankroll_rub,
    )
    if stake < lo or stake > hi:
        raise HTTPException(
            status_code=409,
            detail=f"Ставка вне лимита ({format(lo, '.2f')}–{format(hi, '.2f')} ₽)",
        )


def _pricing_snapshot_payload(
    *,
    commission_profile: object,
    commission_rate,
    creator_cut_percent,
    referral_l1_percent,
    referral_l2_percent,
    commission_cap_rub,
    commission_min_rub,
) -> dict[str, object]:
    return {
        "allocation_model": "stake_percent_v2",
        "commission_profile": commission_profile,
        "commission_rate": _text_money(commission_rate),
        "creator_cut_percent": _text_money(creator_cut_percent),
        "referral_l1_percent": _text_money(referral_l1_percent),
        "referral_l2_percent": _text_money(referral_l2_percent),
        "commission_cap_rub": _text_money(commission_cap_rub),
        "commission_min_rub": _text_money(commission_min_rub),
    }


_CASINO_DEPOSIT_TRANSACTION_RE = re.compile(
    r"^casino-dep-(?P<telegram_id>[1-9]\d*)"
    r"(?:-c(?P<credit_kopecks>[1-9]\d*))?"
    r"-(?P<nonce>[A-Za-z0-9_-]{1,96})$"
)


def _configured_casino_exchanger_id() -> int:
    exchanger_id = int(settings.casino_exchanger_id or 0)
    if exchanger_id <= 0:
        raise HTTPException(status_code=503, detail="Casino exchanger is not configured")
    return exchanger_id


def _telegram_id_from_deposit_transaction_id(value: object) -> int:
    transaction_id = str(value or "").strip()
    match = _CASINO_DEPOSIT_TRANSACTION_RE.fullmatch(transaction_id)
    if not match:
        raise HTTPException(status_code=409, detail="Deal has an invalid casino transaction id")
    return int(match.group("telegram_id"))


def _credit_amount_from_deposit(value: object, amount_paid: Decimal) -> Decimal:
    """Сумму зачисления берём из client_transaction_id (цель до комиссии).

    Старые заявки без части ``-c<копейки>`` не удерживали комиссию — им
    зачисляется вся оплаченная сумма (обратная совместимость).
    """
    match = _CASINO_DEPOSIT_TRANSACTION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise HTTPException(status_code=409, detail="Deal has an invalid casino transaction id")
    kopecks = match.group("credit_kopecks")
    if not kopecks:
        return amount_paid
    credit = money(Decimal(kopecks) / Decimal(100))
    if credit <= 0 or credit > amount_paid:
        raise HTTPException(status_code=409, detail="Casino deposit credit exceeds paid amount")
    return credit


def _row_dict(row: Mapping[str, object] | object) -> dict[str, object]:
    return dict(row) if row else {}


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _v2_countdown_state(game_state: object) -> tuple[dict[str, object], str]:
    from casino_live_sessions import merge_starts_at

    state = merge_starts_at(_json_object(game_state))
    return state, json.dumps(state, separators=(",", ":"))


def _ensure_v2_web_closer() -> None:
    from casino_v2_web import ensure_closer as v2_web_ensure_closer

    v2_web_ensure_closer()


def _persisted_settlement_response(row: Mapping[str, object], *, idempotent: bool) -> dict:
    game = _row_dict(row)
    game_data = _json_object(game.get("game_data"))
    response = _json_object(game_data.get("settlement_response"))
    if response:
        return {**response, "success": True, "idempotent": idempotent}

    stake = game.get("settlement_base_rub") or game.get("bet_rub") or 0
    commission = game.get("commission_rub") or 0
    payout = game.get("payout_rub")
    if payout is None:
        payout = money(stake) * 2 - money(commission)
    response = {
        "success": True,
        "idempotent": idempotent,
        "game_id": str(game.get("game_id") or ""),
        "game_type": str(game.get("game_type") or ""),
        "creator_id": game.get("creator_id"),
        "opponent_id": game.get("opponent_id"),
        "winner_id": game.get("winner_id"),
        "stake_rub": _text_money(stake),
        "commission_rub": _text_money(commission),
        "payout_rub": _text_money(payout),
        "status": str(game.get("status") or "finished"),
    }
    if "state_version" in game:
        response["game"] = _game_response(game)
        response["state_version"] = response["game"]["state_version"]
    return response


def _assert_existing_game_matches(row: Mapping[str, object], body: SettlementRequest) -> None:
    game = _row_dict(row)
    expected = {
        "game_type": body.game_type,
        "creator_id": body.creator_id,
        "opponent_id": body.opponent_id,
        "winner_id": body.winner_id,
        "creator_hold_id": body.creator_hold_id,
        "opponent_hold_id": body.opponent_hold_id,
    }
    for field, value in expected.items():
        persisted = game.get(field)
        if persisted is not None and persisted != value:
            raise HTTPException(status_code=409, detail=f"Game {field} does not match")
    persisted_bet = game.get("settlement_base_rub") or game.get("bet_rub")
    if persisted_bet is not None and money(persisted_bet) != money(body.stake_rub):
        raise HTTPException(status_code=409, detail="Game stake does not match")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _validate_settlement_holds(rows: list, body: SettlementRequest) -> dict[str, dict]:
    by_id = {str(row["hold_id"]): _row_dict(row) for row in rows}
    if set(by_id) != {body.creator_hold_id, body.opponent_hold_id}:
        raise HTTPException(status_code=409, detail="Both player holds are required")

    expected = (
        (body.creator_hold_id, body.creator_id),
        (body.opponent_hold_id, body.opponent_id),
    )
    now = datetime.now(timezone.utc)
    for hold_id, user_id in expected:
        hold = by_id[hold_id]
        if int(hold["telegram_id"]) != user_id:
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} belongs to another user")
        if str(hold["game_id"]) != body.game_id:
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} belongs to another game")
        if money(hold["amount_rub"]) != money(body.stake_rub):
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} amount does not match")
        if hold["status"] != "active":
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} is not active")
        if _utc(hold["expires_at"]) <= now:
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} has expired")
        if not hold.get("ledger_order_ref"):
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} has no unified balance reserve")
    return by_id


async def _insert_commission(
    conn,
    *,
    game_pk: int,
    recipient_type: str,
    recipient_id: int | None,
    amount_rub: Decimal,
    creator_account_id: int | None = None,
) -> bool:
    inserted = await conn.fetchrow(
        """
        INSERT INTO casino_commission_ledger (
            game_id, recipient_type, recipient_id, creator_account_id, amount_rub, status
        )
        VALUES ($1, $2, $3, $4, $5, 'accrued')
        ON CONFLICT (game_id, recipient_type) DO NOTHING
        RETURNING id
        """,
        game_pk,
        recipient_type,
        recipient_id,
        creator_account_id,
        money(amount_rub),
    )
    if inserted:
        return True

    existing = await conn.fetchrow(
        """
        SELECT recipient_id, creator_account_id, amount_rub
        FROM casino_commission_ledger
        WHERE game_id = $1 AND recipient_type = $2
        """,
        game_pk,
        recipient_type,
    )
    if (
        not existing
        or existing["recipient_id"] != recipient_id
        or existing["creator_account_id"] != creator_account_id
        or money(existing["amount_rub"]) != money(amount_rub)
    ):
        raise HTTPException(status_code=409, detail=f"Existing {recipient_type} commission conflicts")
    return False


async def _credit_winner(
    conn,
    *,
    game_id: str,
    winner_id: int,
    payout_rub: Decimal,
) -> None:
    order_id = casino_operation_ref("payout", game_id, str(winner_id))
    if await maybe_credit_tournament_payout(
        conn, user_id=winner_id, order_id=order_id, amount_rub=payout_rub, game_id=game_id
    ):
        return
    inserted = await conn.fetchrow(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        winner_id,
        money(payout_rub),
        order_id,
        f"Casino win: {game_id}",
    )
    existing = inserted or await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
        order_id,
    )
    if not existing or int(existing["user_id"]) != winner_id or money(existing["amount_rub"]) != money(payout_rub):
        raise HTTPException(status_code=409, detail="Existing casino payout conflicts")


async def _insert_deposit_credit_audit(
    conn,
    *,
    deal_id: int,
    exchanger_id: int,
    telegram_id: int,
    amount_rub: Decimal,
    ledger_order_id: str,
    status: str,
    rail: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO casino_deposit_credits (
            deal_id, exchanger_id, telegram_id, amount_rub, ledger_order_id, status,
            credited_at, rail
        )
        VALUES ($1, $2, $3, $4, $5, $6, now(), $7)
        """,
        deal_id,
        exchanger_id,
        telegram_id,
        money(amount_rub),
        ledger_order_id,
        status,
        rail,
    )


def _deposit_credit_response(
    *,
    deal_id: int,
    telegram_id: int,
    amount_rub: Decimal,
    status: str,
    idempotent: bool,
) -> dict:
    return {
        "success": True,
        "idempotent": idempotent,
        "deal_id": deal_id,
        "telegram_id": telegram_id,
        "amount_rub": _text_money(amount_rub),
        "status": status,
    }


async def credit_deposit_with_conn(conn, body: DepositCreditRequest) -> dict:
    """Зачислить подтверждённое casino-пополнение из авторитетной external_deals."""
    casino_exchanger_id = _configured_casino_exchanger_id()
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended('casino-deposit:' || $1::text, 0))",
        str(body.deal_id),
    )
    deal = await conn.fetchrow(
        """
        SELECT id, exchanger_id, status, client_transaction_id, amount_rub, sub_token
        FROM external_deals
        WHERE id = $1
        FOR UPDATE
        """,
        body.deal_id,
    )
    if not deal:
        raise HTTPException(status_code=404, detail="External deal not found")
    if int(deal["exchanger_id"]) != casino_exchanger_id:
        raise HTTPException(status_code=403, detail="External deal belongs to another exchanger")
    if str(deal["status"]) != "confirmed":
        raise HTTPException(status_code=409, detail="External deal is not confirmed")

    telegram_id = _telegram_id_from_deposit_transaction_id(deal["client_transaction_id"])
    amount_paid = money(deal["amount_rub"])
    # На баланс зачисляем целевую сумму (до 21% наценки), а не всю оплату.
    amount_rub = _credit_amount_from_deposit(deal["client_transaction_id"], amount_paid)
    rail = rail_from_sub_token(deal.get("sub_token"))
    await lock_casino_users(conn, (telegram_id,))

    existing_credit = await conn.fetchrow(
        """
        SELECT deal_id, exchanger_id, telegram_id, amount_rub, ledger_order_id, status
        FROM casino_deposit_credits
        WHERE deal_id = $1
        FOR UPDATE
        """,
        body.deal_id,
    )
    if existing_credit:
        if (
            int(existing_credit["exchanger_id"]) != casino_exchanger_id
            or int(existing_credit["telegram_id"]) != telegram_id
            or money(existing_credit["amount_rub"]) != amount_rub
        ):
            raise HTTPException(status_code=409, detail="Existing casino deposit credit conflicts")
        return _deposit_credit_response(
            deal_id=body.deal_id,
            telegram_id=telegram_id,
            amount_rub=amount_rub,
            status=str(existing_credit["status"]),
            idempotent=True,
        )

    legacy_order_id = casino_operation_ref(
        "payout", f"deposit-{body.deal_id}", str(telegram_id)
    )
    legacy_credit = await conn.fetchrow(
        """
        SELECT user_id, amount_rub
        FROM user_cashback_ledger
        WHERE order_id = $1 AND type = 'accrual'
        FOR UPDATE
        """,
        legacy_order_id,
    )
    if legacy_credit:
        if (
            int(legacy_credit["user_id"]) != telegram_id
            or money(legacy_credit["amount_rub"]) != amount_rub
        ):
            raise HTTPException(status_code=409, detail="Legacy casino deposit credit conflicts")
        await _insert_deposit_credit_audit(
            conn,
            deal_id=body.deal_id,
            exchanger_id=casino_exchanger_id,
            telegram_id=telegram_id,
            amount_rub=amount_rub,
            ledger_order_id=legacy_order_id,
            status="legacy_reconciled",
            rail=rail,
        )
        return _deposit_credit_response(
            deal_id=body.deal_id,
            telegram_id=telegram_id,
            amount_rub=amount_rub,
            status="legacy_reconciled",
            idempotent=False,
        )

    ledger_order_id = casino_operation_ref(
        "deposit", str(body.deal_id), str(telegram_id)
    )
    inserted = await conn.fetchrow(
        """
        INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING user_id, amount_rub
        """,
        telegram_id,
        amount_rub,
        ledger_order_id,
        f"Casino deposit: external deal #{body.deal_id}",
    )
    persisted_ledger = inserted or await conn.fetchrow(
        "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1 FOR UPDATE",
        ledger_order_id,
    )
    if (
        not persisted_ledger
        or int(persisted_ledger["user_id"]) != telegram_id
        or money(persisted_ledger["amount_rub"]) != amount_rub
    ):
        raise HTTPException(status_code=409, detail="Existing casino deposit ledger conflicts")

    await _insert_deposit_credit_audit(
        conn,
        deal_id=body.deal_id,
        exchanger_id=casino_exchanger_id,
        telegram_id=telegram_id,
        amount_rub=amount_rub,
        ledger_order_id=ledger_order_id,
        status="credited",
        rail=rail,
    )
    # Депозит зачислен по номиналу — запираем его к выводу до отыгрыша.
    await record_deposit_lock(
        conn,
        deal_id=body.deal_id,
        telegram_id=telegram_id,
        deposit_rub=amount_rub,
    )
    return _deposit_credit_response(
        deal_id=body.deal_id,
        telegram_id=telegram_id,
        amount_rub=amount_rub,
        status="credited",
        idempotent=False,
    )


async def _resolve_loser_referrals(conn, loser_id: int) -> tuple[int | None, int | None]:
    row = await conn.fetchrow(
        """
        SELECT a1.referrer_user_id AS referral_l1_id,
               a2.referrer_user_id AS referral_l2_id
        FROM user_referral_attributions a1
        LEFT JOIN user_referral_attributions a2
          ON a2.user_id = a1.referrer_user_id
        WHERE a1.user_id = $1
        """,
        loser_id,
    )
    if not row:
        return None, None
    return (
        int(row["referral_l1_id"]) if row["referral_l1_id"] is not None else None,
        int(row["referral_l2_id"]) if row["referral_l2_id"] is not None else None,
    )


async def _credit_referral(
    conn,
    *,
    game_id: str,
    level: Literal["l1", "l2"],
    recipient_id: int,
    amount_rub: Decimal,
) -> None:
    order_id = casino_operation_ref(f"ref-{level}", game_id, str(recipient_id))
    await conn.execute(
        """
        INSERT INTO user_referral_ledger (
            referrer_user_id, type, amount_rub, order_id, note
        )
        VALUES ($1, 'accrual', $2, $3, $4)
        ON CONFLICT (order_id) DO NOTHING
        """,
        recipient_id,
        money(amount_rub),
        order_id,
        f"Casino referral {level.upper()}: game {game_id}",
    )


async def _resolve_active_creator_account(conn) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT id AS account_id
        FROM casino_creator_accounts
        WHERE is_active = TRUE
        ORDER BY assigned_at DESC, id DESC
        LIMIT 1
        """
    )
    return dict(row) if row else None


async def _record_commissions(
    conn,
    *,
    game_pk: int,
    game_id: str,
    casino_creator_account: dict | None,
    referral_l1_id: int | None,
    referral_l2_id: int | None,
    allocations: CommissionAllocation,
) -> None:
    # Раунд на фишках не создаёт рублёвую экономику: ни комиссий, ни рефералки.
    if not (await row_scope_of(conn, "casino_games", "game_id", game_id)).is_rub:
        return
    if casino_creator_account is not None and allocations.creator > 0:
        creator_account_id = int(casino_creator_account["account_id"])
        inserted = await _insert_commission(
            conn,
            game_pk=game_pk,
            recipient_type="creator",
            recipient_id=None,
            creator_account_id=creator_account_id,
            amount_rub=allocations.creator,
        )
        if inserted:
            await conn.execute(
                """
                INSERT INTO casino_creator_balance (
                    creator_account_id, balance_rub, total_earned_rub,
                    games_count, last_game_at, updated_at
                ) VALUES ($1, $2, $2, 1, now(), now())
                ON CONFLICT (creator_account_id) WHERE creator_account_id IS NOT NULL DO UPDATE
                SET balance_rub = casino_creator_balance.balance_rub + EXCLUDED.balance_rub,
                    total_earned_rub = casino_creator_balance.total_earned_rub + EXCLUDED.total_earned_rub,
                    games_count = casino_creator_balance.games_count + 1,
                    last_game_at = now(), updated_at = now()
                """,
                creator_account_id, allocations.creator,
            )

    for recipient_type, recipient_id, amount_rub, level in (
        ("referrer_l1", referral_l1_id, allocations.referral_l1, "l1"),
        ("referrer_l2", referral_l2_id, allocations.referral_l2, "l2"),
    ):
        if recipient_id is None or amount_rub <= 0:
            continue
        inserted = await _insert_commission(
            conn,
            game_pk=game_pk,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            amount_rub=amount_rub,
        )
        if inserted:
            await _credit_referral(
                conn,
                game_id=game_id,
                level=level,
                recipient_id=recipient_id,
                amount_rub=amount_rub,
            )

    await _insert_commission(
        conn,
        game_pk=game_pk,
        recipient_type="owner",
        recipient_id=None,
        amount_rub=allocations.owner,
    )


async def settle_game_with_conn(conn, body: SettlementRequest) -> dict:
    """Завершить игру на уже открытом соединении и внутри транзакции вызывающей стороны."""
    await lock_casino_game(conn, body.game_id)
    existing = await conn.fetchrow(
        """
        SELECT id, game_id, game_type, creator_id, opponent_id, bet_rub,
               settlement_base_rub, commission_rub, payout_rub, winner_id,
               creator_hold_id, opponent_hold_id, status, state_version, game_state,
               outcome, created_at, started_at, outcome_committed_at, game_data, finished_at
        FROM casino_games
        WHERE game_id = $1
        """,
        body.game_id,
    )
    if existing:
        _assert_existing_game_matches(existing, body)
        if existing["status"] == "finished":
            return _persisted_settlement_response(existing, idempotent=True)
        if existing["status"] != "outcome_committed":
            raise HTTPException(status_code=409, detail="Use /games/commit-outcome then /games/settle-committed-outcome")
    else:
        raise HTTPException(status_code=409, detail="Use /games/create-or-resume then commit the outcome before settlement")

    await lock_casino_users(conn, (body.creator_id, body.opponent_id))
    hold_rows = await conn.fetch(
        """
        SELECT hold_id, telegram_id, game_id, amount_rub, status,
               expires_at, ledger_order_ref
        FROM casino_balance_holds
        WHERE hold_id = ANY($1::varchar[])
        ORDER BY hold_id
        FOR UPDATE
        """,
        [body.creator_hold_id, body.opponent_hold_id],
    )
    holds = _validate_settlement_holds(hold_rows, body)

    casino_settings = await load_casino_settings(conn)
    stake = money(body.stake_rub)
    pricing_snapshot = {}
    if existing and str(existing["status"]) == "outcome_committed":
        game_data = _json_object(existing.get("game_data"))
        pricing_snapshot = _json_object(game_data.get("pricing_snapshot"))
        if not pricing_snapshot:
            raise HTTPException(status_code=409, detail="Committed game has no immutable pricing snapshot")
    else:
        if not casino_settings.enabled_games.get(body.game_type, False):
            raise HTTPException(status_code=409, detail="Game type is disabled")
        _assert_stake_within_limits(casino_settings, body.game_type, stake)

    commission_rate = pricing_snapshot.get("commission_rate", casino_settings.commission_rate)
    creator_cut_percent = pricing_snapshot.get("creator_cut_percent", casino_settings.creator_cut_percent)
    referral_l1_percent = pricing_snapshot.get("referral_l1_percent", casino_settings.referral_l1_percent)
    referral_l2_percent = pricing_snapshot.get("referral_l2_percent", casino_settings.referral_l2_percent)

    for hold_id, user_id in (
        (body.creator_hold_id, body.creator_id),
        (body.opponent_hold_id, body.opponent_id),
    ):
        order_ref = str(holds[hold_id]["ledger_order_ref"])
        if await unified_hold_amount(conn, user_id, order_ref) != stake:
            raise HTTPException(status_code=409, detail=f"Hold {hold_id} is not fully backed")

    settlement = calculate_equal_stake_settlement(
        stake,
        commission_rate,
        commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub")
        if pricing_snapshot
        else casino_settings.commission_cap_rub,
        commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub")
        if pricing_snapshot
        else casino_settings.commission_min_rub,
    )
    loser_id = body.opponent_id if body.winner_id == body.creator_id else body.creator_id
    referral_l1_id, referral_l2_id = await _resolve_loser_referrals(conn, loser_id)
    casino_creator_account = await _resolve_active_creator_account(conn)
    allocation_model = str(pricing_snapshot.get("allocation_model", "commission_percent"))
    allocation_kwargs = {
        "creator_percent": creator_cut_percent,
        "referral_l1_percent": referral_l1_percent,
        "referral_l2_percent": referral_l2_percent,
        "has_creator": casino_creator_account is not None,
        "has_referral_l1": referral_l1_id is not None,
        "has_referral_l2": referral_l2_id is not None,
    }
    if allocation_model == "stake_percent_v2":
        allocations = allocate_commission(
            stake,
            commission_rate=commission_rate,
            commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub")
            if pricing_snapshot
            else casino_settings.commission_cap_rub,
            commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub")
            if pricing_snapshot
            else casino_settings.commission_min_rub,
            **allocation_kwargs,
        )
    elif allocation_model == "commission_percent":
        allocations = allocate_legacy_commission(settlement.commission, **allocation_kwargs)
    else:
        raise HTTPException(status_code=409, detail="Unknown immutable casino allocation model")

    game_row = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, opponent_id, bet_rub,
            settlement_base_rub, commission_rub, payout_rub, winner_id,
            creator_hold_id, opponent_hold_id, settlement_key,
            status, started_at, game_data
        )
        VALUES (
            $1, $2, $3, $4, $5, $5, $6, $7, $8,
            $9, $10, $11, 'active', COALESCE($12, now()), $13::jsonb
        )
        ON CONFLICT (game_id) DO UPDATE
        SET game_type = EXCLUDED.game_type,
            creator_id = EXCLUDED.creator_id,
            opponent_id = EXCLUDED.opponent_id,
            bet_rub = EXCLUDED.bet_rub,
            settlement_base_rub = EXCLUDED.settlement_base_rub,
            commission_rub = EXCLUDED.commission_rub,
            payout_rub = EXCLUDED.payout_rub,
            winner_id = EXCLUDED.winner_id,
            creator_hold_id = EXCLUDED.creator_hold_id,
            opponent_hold_id = EXCLUDED.opponent_hold_id,
            settlement_key = EXCLUDED.settlement_key,
            status = 'active',
            started_at = COALESCE(casino_games.started_at, now()),
            game_data = casino_games.game_data || EXCLUDED.game_data
        WHERE casino_games.status <> 'finished'
        RETURNING id
        """,
        body.game_id,
        body.game_type,
        body.creator_id,
        body.opponent_id,
        settlement.losing_stake,
        settlement.commission,
        settlement.payout,
        body.winner_id,
        body.creator_hold_id,
        body.opponent_hold_id,
        f"casino-settle:{body.game_id}",
        existing["started_at"] if existing and "started_at" in existing else None,
        json.dumps({"loser_id": loser_id}, separators=(",", ":")),
    )
    if not game_row:
        raise HTTPException(status_code=409, detail="Game was already settled")
    game_pk = int(game_row["id"])

    for hold_id, user_id in (
        (body.creator_hold_id, body.creator_id),
        (body.opponent_hold_id, body.opponent_id),
    ):
        await confirm_unified_hold(
            conn,
            user_id=user_id,
            order_ref=str(holds[hold_id]["ledger_order_ref"]),
            amount_rub=stake,
            note=f"Casino stake: {body.game_id}",
        )

    await _credit_winner(
        conn,
        game_id=body.game_id,
        winner_id=body.winner_id,
        payout_rub=settlement.payout,
    )
    await _record_commissions(
        conn,
        game_pk=game_pk,
        game_id=body.game_id,
        casino_creator_account=casino_creator_account,
        referral_l1_id=referral_l1_id,
        referral_l2_id=referral_l2_id,
        allocations=allocations,
    )

    await conn.execute(
        """
        UPDATE casino_balance_holds
        SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = ANY($1::varchar[]) AND status = 'active'
        """,
        [body.creator_hold_id, body.opponent_hold_id],
    )

    response = {
        "success": True,
        "idempotent": False,
        "game_id": body.game_id,
        "game_type": body.game_type,
        "creator_id": body.creator_id,
        "opponent_id": body.opponent_id,
        "winner_id": body.winner_id,
        "loser_id": loser_id,
        "stake_rub": _text_money(settlement.losing_stake),
        "pot_rub": _text_money(settlement.pot),
        "commission_rub": _text_money(settlement.commission),
        "payout_rub": _text_money(settlement.payout),
        "allocations": {
            "creator_rub": _text_money(allocations.creator),
            "referral_l1_rub": _text_money(allocations.referral_l1),
            "referral_l2_rub": _text_money(allocations.referral_l2),
            "owner_rub": _text_money(allocations.owner),
        },
        "status": "finished",
    }
    finished_game = await conn.fetchrow(
        """
        UPDATE casino_games
        SET status = 'finished', finished_at = now(), updated_at = now(),
            game_data = game_data || jsonb_build_object(
                'settlement_response', $2::jsonb,
                'referral_l1_id', $3::bigint,
                'referral_l2_id', $4::bigint
            )
        WHERE id = $1
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        game_pk,
        json.dumps(response, separators=(",", ":")),
        referral_l1_id,
        referral_l2_id,
    )
    if not finished_game:
        raise HTTPException(status_code=409, detail="Game settlement conflicts")
    response["game"] = _game_response(finished_game)
    response["state_version"] = response["game"]["state_version"]
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(
        conn,
        int(body.creator_id),
        int(body.opponent_id) if body.opponent_id is not None else 0,
    )
    return response


def _game_response(row: Mapping[str, object]) -> dict[str, object]:
    game = _row_dict(row)
    def timestamp(name: str) -> str | None:
        value = game.get(name)
        return _utc(value).isoformat() if isinstance(value, datetime) else None

    game_data = _json_object(game.get("game_data"))
    pvp_data = _json_object(game_data.get("pvp"))
    return {
        "game_id": str(game["game_id"]),
        "game_type": str(game["game_type"]),
        "creator_id": int(game["creator_id"]),
        "opponent_id": int(game["opponent_id"]) if game.get("opponent_id") is not None else None,
        "counterparty_kind": str(game.get("counterparty_kind") or "player"),
        "robot_profile": _json_object(_json_object(game.get("game_data")).get("robot_profile")),
        "stake_rub": _text_money(game["bet_rub"]),
        "creator_hold_id": game.get("creator_hold_id"),
        "opponent_hold_id": game.get("opponent_hold_id"),
        "status": str(game["status"]),
        "state_version": int(game.get("state_version") or 0),
        "game_state": _json_object(game.get("game_state")),
        "outcome": _json_object(game.get("outcome")) or None,
        "created_at": timestamp("created_at"),
        "started_at": timestamp("started_at"),
        "outcome_committed_at": timestamp("outcome_committed_at"),
        "finished_at": timestamp("finished_at"),
        "game_chat_binding_id": int(game["game_chat_binding_id"]) if game.get("game_chat_binding_id") is not None else None,
        "game_chat_id": int(game["game_chat_id"]) if game.get("game_chat_id") is not None else None,
        "game_chat_binding_revision": int(game["game_chat_binding_revision"]) if game.get("game_chat_binding_revision") is not None else None,
        "rounds": int(pvp_data["rounds"]) if pvp_data.get("rounds") is not None else None,
        "rng_commit": str(game["rng_commit"]) if game.get("rng_commit") else None,
    }


async def active_pvp_games_with_conn(conn) -> dict[str, object]:
    """Return recoverable PVP games without leasing, settling, or mutating them."""
    rows = await conn.fetch(
        """
        SELECT game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
               opponent_hold_id, counterparty_kind, game_data, status, state_version,
               game_state, outcome, created_at, started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision, rng_commit
        FROM casino_games
        WHERE status IN ('waiting', 'active')
          AND game_type IN (
                'pvp_dice', 'pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball',
                'baccara', 'blackjack'
          )
        ORDER BY created_at ASC, game_id ASC
        """
    )
    return {"games": [_game_response(row) for row in rows]}


async def _game_for_update(conn, game_id: str):
    row = await conn.fetchrow(
        """
        SELECT id, game_id, game_type, creator_id, opponent_id, bet_rub, winner_id, creator_hold_id,
               opponent_hold_id, counterparty_kind, house_account_id, robot_profile_id,
               settlement_base_rub, payout_rub, commission_rub, game_data, status, state_version,
               game_state, outcome, created_at, started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        FROM casino_games WHERE game_id = $1 FOR UPDATE
        """,
        game_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Casino game not found")
    return row


async def _wagering_status_payload(conn, recipient_ids: set[int]) -> dict[int, dict[str, str]]:
    """Snapshot each recipient's current wagering progress for durable settlement delivery."""
    statuses: dict[int, dict[str, str]] = {}
    for recipient_id in recipient_ids:
        progress = await wagering_progress(conn, recipient_id)
        statuses[recipient_id] = serialize_wagering_progress(progress)
    return statuses


_GAME_TYPE_LABELS = {
    "pvp_dice": "🎲 Кубики",
    "pvp_darts": "🎯 Дартс",
    "pvp_bowling": "🎳 Боулинг",
    "pvp_football": "⚽ Футбол",
    "pvp_basketball": "🏀 Баскетбол",
    "baccara": "🃏 Baccara",
    "blackjack": "🂡 Blackjack",
    "cub": "🎲 Кубик",
}

_RESULT_HEADLINES = {
    "win": "Вы победили",
    "lose": "Вы проиграли",
    "tie": "Ничья",
    "cancel": "Игра отменена, ставка возвращена",
}


def _as_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_game(payload: Mapping[str, object]) -> Mapping[str, object]:
    game = payload.get("game")
    return game if isinstance(game, Mapping) else {}


def _notification_recipient_ids(payload: Mapping[str, object]) -> set[int]:
    ids: set[int] = set()
    for source in (payload, _nested_game(payload)):
        for field in ("creator_id", "opponent_id", "winner_id"):
            parsed = _as_optional_int(source.get(field))
            if parsed is not None:
                ids.add(parsed)
    return ids


def _payload_game_type(payload: Mapping[str, object]) -> str:
    game = _nested_game(payload)
    return str(payload.get("game_type") or game.get("game_type") or "")


def _payload_game_id(payload: Mapping[str, object]) -> str:
    game = _nested_game(payload)
    return str(payload.get("game_id") or payload.get("table_id") or game.get("game_id") or "")


def _personal_result_kind(*, event_type: str, payload: Mapping[str, object], recipient_id: int) -> str:
    if event_type != "game_settled":
        return "cancel"
    outcome = payload.get("outcome")
    kind = str(outcome.get("kind") or "") if isinstance(outcome, Mapping) else ""
    if kind in {"draw", "tie"}:
        return "tie"
    if kind == "house_win":
        return "lose"
    winner_id = _as_optional_int(payload.get("winner_id"))
    if winner_id is None:
        winner_id = _as_optional_int(_nested_game(payload).get("winner_id"))
    if winner_id is not None:
        return "win" if winner_id == recipient_id else "lose"
    if kind == "winner":
        return "win"
    return "lose"


def _personal_payout_rub(*, result: str, payload: Mapping[str, object]) -> str:
    if result in {"lose", "cancel"}:
        return "0.00"
    return _text_money(payload.get("your_payout_rub") or payload.get("payout_rub") or 0)


def format_personal_result_html(
    *,
    result: str,
    game_type: str,
    game_id: str,
    payout_rub: object,
    available_rub: object | None,
) -> str:
    """Private-chat HTML: you won/lost/tied, payout, balance snapshot."""
    headline = _RESULT_HEADLINES.get(result, "Игра завершена")
    label = _GAME_TYPE_LABELS.get(game_type, game_type or "Игра")
    short_id = str(game_id or "")[:8].upper()
    lines = [f"<b>{headline}</b>"]
    if short_id:
        lines.append(f"{html.escape(label)} · стол #{html.escape(short_id)}")
    else:
        lines.append(html.escape(label))
    if result != "cancel":
        lines.append(f"Выплата: {_text_money(payout_rub)} ₽")
    if available_rub is not None and str(available_rub) != "":
        lines.append(f"Баланс: {_text_money(available_rub)} ₽")
    return "\n".join(lines)


async def _snapshot_available_rub(conn, user_id: int) -> str | None:
    """Post-settle unified balance. Must not roll back the financial transaction."""
    try:
        return _text_money(await unified_available(conn, int(user_id)))
    except Exception:
        return None


async def _enqueue_v2_public_outbox(
    conn,
    table,
    *,
    event_type: Literal["public_settled", "public_cancelled"],
    payload: Mapping[str, object],
) -> None:
    """Persist group-card delivery separately from every personal result."""
    chat_id = table.get("game_chat_id")
    try:
        parsed_chat_id = int(chat_id)
    except (TypeError, ValueError):
        return
    if parsed_chat_id >= 0:
        return
    snapshot = await _v2_table_response_with_conn(conn, table)
    public_payload = {
        **dict(payload),
        "table_id": str(table["table_id"]),
        "game_type": str(table["game_type"]),
        "game_chat_id": parsed_chat_id,
        "table": snapshot,
    }
    await conn.execute(
        """INSERT INTO casino_v2_notification_outbox(event_key,table_id,recipient_id,event_type,payload)
        VALUES($1,$2,$3,$4,$5::jsonb)
        ON CONFLICT(table_id,event_type,recipient_id) DO NOTHING""",
        f"v2:{table['table_id']}:{event_type}",
        int(table["id"]),
        int(table["creator_id"]),
        event_type,
        json.dumps(public_payload, separators=(",", ":")),
    )


async def _enqueue_v2_cancelled_outbox(conn, table, seats) -> None:
    """DM each player whose stake was released: table cancelled, expired, or they left."""
    table_id = str(table["table_id"])
    table_pk = int(table["id"])
    game_type = str(table["game_type"])
    seen: set[int] = set()
    for seat in seats:
        if str(seat.get("participant_kind") or "") != "player":
            continue
        try:
            recipient_id = int(seat["telegram_id"])
        except (TypeError, ValueError, KeyError):
            continue
        if recipient_id <= 0 or recipient_id in seen:
            continue
        seen.add(recipient_id)
        available = await _snapshot_available_rub(conn, recipient_id)
        personal = {
            "table_id": table_id,
            "game_type": game_type,
            "game_chat_id": int(table["game_chat_id"]) if table.get("game_chat_id") is not None else None,
            "result": "cancel",
            "outcome_kind": "cancel",
            "stake_rub": _text_money(table.get("stake_rub")),
            "your_payout_rub": "0.00",
            "available_rub": available,
            "public_delivery_separate": True,
            "text": format_personal_result_html(
                result="cancel",
                game_type=game_type,
                game_id=table_id,
                payout_rub=0,
                available_rub=available,
            ),
        }
        await conn.execute(
            """INSERT INTO casino_v2_notification_outbox(event_key,table_id,recipient_id,event_type,payload)
            VALUES($1,$2,$3,'cancelled',$4::jsonb) ON CONFLICT(table_id,event_type,recipient_id) DO NOTHING""",
            f"v2:{table_id}:cancelled:{recipient_id}",
            table_pk,
            recipient_id,
            json.dumps(personal, separators=(",", ":")),
        )
    await _enqueue_v2_public_outbox(
        conn,
        table,
        event_type="public_cancelled",
        payload={"result": "cancel", "outcome_kind": "cancel"},
    )


def _v2_seat_result(*, outcome_kind: str, seat_no: int, winner_seat_nos: list[int]) -> str:
    if outcome_kind == "tie_split" and seat_no in winner_seat_nos:
        return "tie"
    if seat_no in winner_seat_nos:
        return "win"
    return "lose"


async def _enqueue_notification(
    conn,
    *,
    game_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> None:
    """Queue one recipient-specific delivery after terminal financial work only."""
    recipient_ids = _notification_recipient_ids(payload)
    if not recipient_ids:
        return
    wagering_by_recipient = (
        await _wagering_status_payload(conn, recipient_ids)
        if event_type == "game_settled"
        else {}
    )
    game_type = _payload_game_type(payload)
    game_id_label = _payload_game_id(payload) or game_id
    for recipient_id in recipient_ids:
        result = _personal_result_kind(event_type=event_type, payload=payload, recipient_id=recipient_id)
        payout = _personal_payout_rub(result=result, payload=payload)
        available = await _snapshot_available_rub(conn, recipient_id)
        notification_payload = {
            **payload,
            "chat_id": recipient_id,
            "result": result,
            "your_payout_rub": payout,
            "available_rub": available,
            "text": format_personal_result_html(
                result=result,
                game_type=game_type,
                game_id=game_id_label,
                payout_rub=payout,
                available_rub=available,
            ),
        }
        if recipient_id in wagering_by_recipient:
            notification_payload["wagering"] = wagering_by_recipient[recipient_id]
        encoded_payload = json.dumps(notification_payload, separators=(",", ":"), default=str)
        await conn.execute(
            """
            INSERT INTO casino_notification_outbox (event_key, event_type, game_id, recipient_id, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (game_id, event_type, recipient_id) DO NOTHING
            """,
            f"casino:{game_id}:{event_type}:{recipient_id}",
            event_type,
            game_id,
            recipient_id,
            encoded_payload,
        )


def _house_rng_seed() -> str:
    return secrets.token_hex(32)


def _house_rng_commit(seed: str, game_id: str) -> str:
    return game_commit(seed, game_id)


def _card_rng_public(
    *,
    game_id: str,
    rng_commit: str,
    client_seed: str,
    nonce: int,
    pair_commit_hash: str,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "rng_commit": rng_commit,
        "pair_commit": pair_commit_hash,
        "client_seed": client_seed,
        "nonce": int(nonce),
        "algorithm": CARD_SHUFFLE_ALGORITHM,
    }


def _card_rng_metadata(
    rng_commit: str,
    *,
    client_seed: str,
    nonce: int,
    pair_commit_hash: str,
) -> dict[str, object]:
    return {
        "algorithm": CARD_SHUFFLE_ALGORITHM,
        "commit": rng_commit,
        "pair_commit": pair_commit_hash,
        "client_seed": client_seed,
        "nonce": int(nonce),
        "creator_cards": [],
        "opponent_cards": [],
    }


def _rng_text(row: Mapping[str, object], key: str, default: str = "") -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        value = default
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _rng_nonce(row: Mapping[str, object]) -> int:
    try:
        value = row["nonce"]
    except (KeyError, IndexError):
        value = 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stored_card_hand(card_rng: Mapping[str, object], side: str) -> list[str]:
    stored = card_rng.get(f"{side}_cards")
    if not isinstance(stored, list) or not all(isinstance(card, str) and card for card in stored):
        return []
    return list(stored)


async def _load_or_create_card_commit(
    conn,
    *,
    game_id: str,
    game_type: str,
    telegram_id: int,
) -> dict[str, object]:
    """Commit shoe entropy before cards are dealt. Idempotent per game_id.

    A new commit copies the player's current seed pair and nonce, then increments
    the session nonce. Repeating prepare for the same game_id must not increment.
    """
    existing = await conn.fetchrow(
        """
        SELECT game_id, commit_hash, server_seed, nonce, status, telegram_id, game_type,
               client_seed
        FROM casino_house_rng_commits
        WHERE game_id = $1
        FOR UPDATE
        """,
        game_id,
    )
    if existing:
        if str(existing["game_type"]) != game_type or int(existing["telegram_id"]) != telegram_id:
            raise HTTPException(status_code=409, detail="Card fairness commitment conflicts")
        if str(existing["status"]) not in {"pending", "consumed"}:
            raise HTTPException(status_code=409, detail="Card fairness commitment is not usable")
        seed = str(existing["server_seed"])
        return {
            "game_id": game_id,
            "rng_commit": str(existing["commit_hash"]),
            "server_seed": seed,
            "client_seed": _rng_text(existing, "client_seed", DEFAULT_CLIENT_SEED),
            "nonce": _rng_nonce(existing),
            "pair_commit": pair_commit(seed),
        }
    session = await get_or_create_fairness_session(conn, telegram_id)
    seed = str(session["server_seed"])
    client_seed = _rng_text(session, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(session)
    commit = _house_rng_commit(seed, game_id)
    await conn.execute(
        """
        INSERT INTO casino_house_rng_commits (
            game_id, commit_hash, game_type, telegram_id, server_seed, nonce, client_seed, expires_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, now() + interval '{ttl}')
        """.format(ttl=CARD_COMMIT_TTL),
        game_id, commit, game_type, telegram_id, seed, nonce, client_seed,
    )
    await increment_session_nonce(conn, telegram_id, nonce)
    return {
        "game_id": game_id,
        "rng_commit": commit,
        "server_seed": seed,
        "client_seed": client_seed,
        "nonce": nonce,
        "pair_commit": pair_commit(seed),
    }


async def prepare_cards_with_conn(conn, body: CardsPrepareRequest) -> dict:
    """Commit the card shoe hash before the creator's stake is held."""
    rng = await _load_or_create_card_commit(
        conn,
        game_id=body.game_id,
        game_type=body.game_type,
        telegram_id=body.telegram_id,
    )
    return {
        "success": True,
        **_card_rng_public(
            game_id=body.game_id,
            rng_commit=str(rng["rng_commit"]),
            client_seed=str(rng["client_seed"]),
            nonce=int(rng["nonce"]),
            pair_commit_hash=str(rng["pair_commit"]),
        ),
    }


async def _bind_card_commit_to_game(conn, *, game_id: str, game_type: str, telegram_id: int) -> str:
    rng = await _load_or_create_card_commit(
        conn, game_id=game_id, game_type=game_type, telegram_id=telegram_id,
    )
    await conn.execute(
        """
        UPDATE casino_games
        SET rng_commit = $2,
            game_data = COALESCE(game_data, '{}'::jsonb) || $3::jsonb
        WHERE game_id = $1
        """,
        game_id,
        rng["rng_commit"],
        json.dumps(
            {
                "card_rng": _card_rng_metadata(
                    str(rng["rng_commit"]),
                    client_seed=str(rng["client_seed"]),
                    nonce=int(rng["nonce"]),
                    pair_commit_hash=str(rng["pair_commit"]),
                )
            },
            separators=(",", ":"),
        ),
    )
    return str(rng["rng_commit"])


def _card_side_for_player(game: Mapping[str, object], telegram_id: int) -> str:
    if int(game["creator_id"]) == telegram_id:
        return "creator"
    opponent_id = game.get("opponent_id")
    if opponent_id is not None and int(opponent_id) == telegram_id:
        return "opponent"
    raise HTTPException(status_code=409, detail="Player is not in this card game")


async def deal_cards_with_conn(conn, body: CardsDealRequest) -> dict:
    """Deal from the committed shoe. The bot cannot choose or reshuffle cards."""
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    game_type = str(game["game_type"])
    if game_type not in CARD_GAME_TYPES:
        raise HTTPException(status_code=409, detail="Game is not a card game")
    if str(game["status"]) != "active" or game.get("opponent_id") is None:
        raise HTTPException(status_code=409, detail="Card game has not started")
    side = _card_side_for_player(game, body.telegram_id)

    rng_row = await conn.fetchrow(
        """
        SELECT commit_hash, server_seed, status, client_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = $2 AND status = 'pending' AND expires_at > now()
        FOR UPDATE
        """,
        body.game_id, game_type,
    )
    if not rng_row:
        raise HTTPException(status_code=409, detail="Card fairness commitment is missing or expired")
    seed = str(rng_row["server_seed"])
    rng_commit = str(rng_row["commit_hash"])
    client_seed = _rng_text(rng_row, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(rng_row)
    pair_hash = pair_commit(seed)
    game_data = _json_object(game.get("game_data"))
    card_rng = _json_object(game_data.get("card_rng"))
    stored = _stored_card_hand(card_rng, side)
    if body.hand_size < len(stored):
        raise HTTPException(status_code=409, detail="Cannot shrink a dealt hand")
    try:
        full = card_dealt_cards(
            seed,
            body.game_id,
            side,
            body.hand_size,
            client_seed=client_seed,
            nonce=nonce,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Card deal is invalid") from exc
    if stored != full[:len(stored)]:
        raise HTTPException(status_code=409, detail="Dealt hand does not match the committed shoe")
    idempotent = body.hand_size == len(stored)
    card_rng["algorithm"] = CARD_SHUFFLE_ALGORITHM
    card_rng["commit"] = rng_commit
    card_rng["pair_commit"] = pair_hash
    card_rng["client_seed"] = client_seed
    card_rng["nonce"] = nonce
    card_rng[f"{side}_cards"] = full
    game_data["card_rng"] = card_rng
    await conn.execute(
        """
        UPDATE casino_games
        SET game_data = $2::jsonb, updated_at = now()
        WHERE game_id = $1
        """,
        body.game_id, json.dumps(game_data, separators=(",", ":")),
    )
    return {
        "success": True,
        "idempotent": idempotent,
        "cards": full,
        "hand_size": body.hand_size,
        **_card_rng_public(
            game_id=body.game_id,
            rng_commit=rng_commit,
            client_seed=client_seed,
            nonce=nonce,
            pair_commit_hash=pair_hash,
        ),
    }


async def reveal_cards_with_conn(conn, body: CardsRevealRequest) -> dict:
    """Reveal the committed shoe seed after the round is committed or finished."""
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    game_type = str(game["game_type"])
    if game_type not in CARD_GAME_TYPES:
        raise HTTPException(status_code=409, detail="Game is not a card game")
    _card_side_for_player(game, body.telegram_id)
    if str(game["status"]) not in {"outcome_committed", "finished"}:
        raise HTTPException(status_code=409, detail="Card seed is revealed after the round")
    rng_row = await conn.fetchrow(
        """
        SELECT commit_hash, server_seed, status, client_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = $2
        FOR UPDATE
        """,
        body.game_id, game_type,
    )
    if not rng_row:
        raise HTTPException(status_code=409, detail="Card fairness commitment is missing")
    seed = str(rng_row["server_seed"])
    rng_commit = str(rng_row["commit_hash"])
    client_seed = _rng_text(rng_row, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(rng_row)
    pair_hash = pair_commit(seed)
    if str(rng_row["status"]) == "pending":
        await conn.execute(
            """
            UPDATE casino_house_rng_commits
            SET status = 'consumed', consumed_at = now()
            WHERE game_id = $1 AND status = 'pending'
            """,
            body.game_id,
        )
        await conn.execute(
            """
            UPDATE casino_games
            SET rng_seed_reveal = $2, updated_at = now(),
                game_data = COALESCE(game_data, '{}'::jsonb) || $3::jsonb
            WHERE game_id = $1
            """,
            body.game_id,
            seed,
            json.dumps(
                {
                    "card_rng_reveal": {
                        "commit": rng_commit,
                        "pair_commit": pair_hash,
                        "client_seed": client_seed,
                        "nonce": nonce,
                        "algorithm": CARD_SHUFFLE_ALGORITHM,
                    }
                },
                separators=(",", ":"),
            ),
        )
    return {
        "success": True,
        "rng_seed": seed,
        **_card_rng_public(
            game_id=body.game_id,
            rng_commit=rng_commit,
            client_seed=client_seed,
            nonce=nonce,
            pair_commit_hash=pair_hash,
        ),
    }


def _v2_seat_for_card_deal(table: Mapping[str, object], roster: list[Mapping[str, object]], *, telegram_id: int, seat_no: int | None) -> tuple[int, str]:
    seats = [seat for seat in roster if str(seat.get("status", "seated")) == "seated"]
    if seat_no is not None:
        seat = next((row for row in seats if int(row["seat_no"]) == seat_no), None)
        if seat is None:
            raise HTTPException(status_code=409, detail="V2 card seat is not seated")
        if str(seat.get("participant_kind")) == "player" and int(seat.get("telegram_id") or 0) != telegram_id:
            raise HTTPException(status_code=409, detail="Player is not in this card seat")
        return int(seat["seat_no"]), f"seat{int(seat['seat_no'])}"
    seat = next((row for row in seats if str(row.get("participant_kind")) == "player" and int(row.get("telegram_id") or 0) == telegram_id), None)
    if seat is None:
        raise HTTPException(status_code=409, detail="Player is not seated at this V2 table")
    return int(seat["seat_no"]), f"seat{int(seat['seat_no'])}"


async def prepare_v2_table_cards_with_conn(conn, table_id: str, body: V2CardsPrepareRequest) -> dict:
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    if str(table["game_type"]) not in CARD_GAME_TYPES or str(table["game_type"]) != body.game_type:
        raise HTTPException(status_code=409, detail="V2 table is not this card game")
    rng = await _load_or_create_card_commit(
        conn, game_id=table_id, game_type=body.game_type, telegram_id=body.telegram_id,
    )
    return {
        "success": True,
        **_card_rng_public(
            game_id=table_id,
            rng_commit=str(rng["rng_commit"]),
            client_seed=str(rng["client_seed"]),
            nonce=int(rng["nonce"]),
            pair_commit_hash=str(rng["pair_commit"]),
        ),
    }


async def deal_v2_table_cards_with_conn(conn, table_id: str, body: V2CardsDealRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    game_type = str(table["game_type"])
    if game_type not in CARD_GAME_TYPES:
        raise HTTPException(status_code=409, detail="V2 table is not a card game")
    if str(table["status"]) not in {"running", "tie_break_running"}:
        raise HTTPException(status_code=409, detail="V2 card game has not started")
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 AND status='seated' ORDER BY seat_no", int(table["id"]))
    seat_no, default_side = _v2_seat_for_card_deal(table, seats, telegram_id=body.telegram_id, seat_no=body.seat_no)
    side = body.shoe_side or default_side
    rng_row = await conn.fetchrow(
        """
        SELECT commit_hash, server_seed, status, client_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = $2 AND status IN ('pending', 'consumed') AND expires_at > now()
        FOR UPDATE
        """,
        table_id, game_type,
    )
    if not rng_row:
        raise HTTPException(status_code=409, detail="Card fairness commitment is missing or expired")
    seed = str(rng_row["server_seed"])
    rng_commit = str(rng_row["commit_hash"])
    client_seed = _rng_text(rng_row, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(rng_row)
    pair_hash = pair_commit(seed)
    state = _json_object(table.get("game_state"))
    card_rng = _json_object(state.get("card_rng"))
    stored = _stored_card_hand(card_rng, side)
    if body.hand_size < len(stored):
        raise HTTPException(status_code=409, detail="Cannot shrink a dealt hand")
    try:
        full = card_dealt_cards(seed, table_id, side, body.hand_size, client_seed=client_seed, nonce=nonce)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Card deal is invalid") from exc
    if stored != full[:len(stored)]:
        raise HTTPException(status_code=409, detail="Dealt hand does not match the committed shoe")
    card_rng["algorithm"] = CARD_SHUFFLE_ALGORITHM
    card_rng["commit"] = rng_commit
    card_rng["pair_commit"] = pair_hash
    card_rng["client_seed"] = client_seed
    card_rng["nonce"] = nonce
    card_rng[f"{side}_cards"] = full
    state["card_rng"] = card_rng
    hands = _json_object(state.get("hands"))
    hands[str(seat_no)] = full
    state["hands"] = hands
    await conn.execute(
        """UPDATE casino_v2_tables SET game_state=game_state || $2::jsonb, updated_at=now() WHERE table_id=$1""",
        table_id, json.dumps({"card_rng": card_rng, "hands": hands}, separators=(",", ":")),
    )
    return {
        "success": True,
        "idempotent": body.hand_size == len(stored),
        "cards": full,
        "hand_size": body.hand_size,
        "seat_no": seat_no,
        "side": side,
        **_card_rng_public(
            game_id=table_id,
            rng_commit=rng_commit,
            client_seed=client_seed,
            nonce=nonce,
            pair_commit_hash=pair_hash,
        ),
    }


async def reveal_v2_table_cards_with_conn(conn, table_id: str, body: V2CardsRevealRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    game_type = str(table["game_type"])
    if game_type not in CARD_GAME_TYPES:
        raise HTTPException(status_code=409, detail="V2 table is not a card game")
    if str(table["status"]) not in {"outcome_committed", "finished"}:
        raise HTTPException(status_code=409, detail="Card seed is revealed after the round")
    rng_row = await conn.fetchrow(
        """
        SELECT commit_hash, server_seed, status, client_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = $2
        FOR UPDATE
        """,
        table_id, game_type,
    )
    if not rng_row:
        raise HTTPException(status_code=409, detail="Card fairness commitment is missing")
    seed = str(rng_row["server_seed"])
    rng_commit = str(rng_row["commit_hash"])
    client_seed = _rng_text(rng_row, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(rng_row)
    pair_hash = pair_commit(seed)
    if str(rng_row["status"]) == "pending":
        await conn.execute(
            """UPDATE casino_house_rng_commits SET status='consumed', consumed_at=now() WHERE game_id=$1 AND status='pending'""",
            table_id,
        )
    return {
        "success": True,
        "rng_seed": seed,
        **_card_rng_public(
            game_id=table_id,
            rng_commit=rng_commit,
            client_seed=client_seed,
            nonce=nonce,
            pair_commit_hash=pair_hash,
        ),
    }


async def prepare_cub_with_conn(conn, body: PrepareCubRequest) -> dict:
    """Commit server entropy before the player supplies a stake."""
    game_id = str(uuid4())
    seed = _house_rng_seed()
    commit = _house_rng_commit(seed, game_id)
    await conn.execute(
        """
        INSERT INTO casino_house_rng_commits (
            game_id, commit_hash, game_type, telegram_id, server_seed, nonce
        ) VALUES ($1, $2, 'cub', $3, $4, 0)
        """,
        game_id, commit, body.telegram_id, seed,
    )
    return {"success": True, "game_id": game_id, "rng_commit": commit}


async def play_cub_with_conn(conn, body: CubPlayRequest) -> dict:
    """Atomically play a private house-backed dice round.

    The casino is accounted for by its own reserve, never by a synthetic user.
    """
    await assert_real_money_only(conn, body.telegram_id)
    await lock_casino_game(conn, body.game_id)
    await lock_casino_users(conn, (body.telegram_id,))
    stake = money(body.stake_rub)
    existing = await conn.fetchrow(
        "SELECT * FROM casino_games WHERE game_id = $1 FOR UPDATE", body.game_id
    )
    if existing:
        if (
            str(existing["game_type"]) != "cub"
            or int(existing["creator_id"]) != body.telegram_id
            or money(existing["bet_rub"]) != stake
        ):
            raise HTTPException(status_code=409, detail="Existing cub game conflicts")
        if str(existing["status"]) != "finished":
            raise HTTPException(status_code=409, detail="Cub game requires manual recovery")
        game_data = _json_object(existing.get("game_data"))
        rng_audit = game_data.get("rng_audit")
        return {
            "success": True,
            "idempotent": True,
            "game_id": body.game_id,
            "outcome": _json_object(existing.get("outcome")),
            "payout_rub": _text_money(existing.get("payout_rub") or 0),
            "rng": rng_audit,
            **cub_pips_from_rng(rng_audit),
        }

    settings_snapshot = await load_casino_settings(conn)
    commission_rate = await commission_rate_for_player(conn, body.telegram_id)
    commission_profile, _ = await commission_profile_for_player(conn, body.telegram_id)
    if not settings_snapshot.enabled_games.get("cub", False):
        raise HTTPException(status_code=409, detail="Cub is disabled")

    policy = await conn.fetchrow(
        """
        SELECT id, payout_multiplier, win_probability, terms
        FROM casino_house_policies
        WHERE game_type = 'cub' AND is_active = TRUE
        FOR UPDATE
        """
    )
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.account_id, rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub,
               ha.account_key, ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND rp.allowed_games ? 'cub'
        ORDER BY rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """
    )
    if not policy or not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="Cub house robot is unavailable")
    if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
        raise HTTPException(status_code=409, detail="Stake is outside the robot limits")

    win_probability = Decimal(str(policy["win_probability"]))
    payout_multiplier = Decimal(str(policy["payout_multiplier"]))
    from casino_play import house_bots_cub_odds

    scaled = house_bots_cub_odds(int(body.house_bot_count or 0))
    if scaled:
        payout_multiplier, win_probability = scaled
    if not Decimal("0") < win_probability < Decimal("1"):
        raise HTTPException(status_code=409, detail="Cub policy is invalid")
    _assert_stake_within_limits(
        settings_snapshot,
        "cub",
        stake,
        payout_multiplier=payout_multiplier,
        bankroll_rub=money(profile["balance_rub"]),
    )
    max_settlement = calculate_house_settlement(
        stake,
        payout_multiplier,
        commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    exposure_limit = money(profile["max_exposure_rub"])
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"])
    if (exposure_limit > 0 and max_settlement.payout > exposure_limit) or available < max_settlement.payout:
        raise HTTPException(status_code=409, detail="Cub house bankroll is insufficient")

    rng_row = await conn.fetchrow(
        """
        SELECT game_id, commit_hash, server_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = 'cub' AND telegram_id = $2
          AND status = 'pending' AND expires_at > now()
        FOR UPDATE
        """,
        body.game_id, body.telegram_id,
    )
    if not rng_row:
        raise HTTPException(status_code=409, detail="Cub fairness commitment is missing or expired")
    seed = str(rng_row["server_seed"])
    nonce = int(rng_row["nonce"])
    rng_commit = str(rng_row["commit_hash"])
    threshold = int((win_probability * Decimal(1 << 256)).to_integral_value())
    digest_value = int.from_bytes(
        hmac.new(seed.encode("utf-8"), f"{body.game_id}:{nonce}".encode("utf-8"), hashlib.sha256).digest(),
        "big",
    )
    won = digest_value < threshold
    player_pips, house_pips = cub_presentation_pips(digest_value, won=won)
    settlement = calculate_house_settlement(
        stake,
        payout_multiplier if won else Decimal("0"),
        commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )

    hold_id = f"casino-{body.game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(
            conn, user_id=body.telegram_id, order_ref=order_ref, amount_rub=stake
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Недостаточно средств") from exc
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    game_data = {
        "house_policy_snapshot": {
            "policy_id": int(policy["id"]),
            "payout_multiplier": _text_money(payout_multiplier),
            "win_probability": str(win_probability),
            "house_bot_count": int(body.house_bot_count or 0),
        },
        "pricing_snapshot": _pricing_snapshot_payload(
            commission_profile=commission_profile,
            commission_rate=commission_rate,
            creator_cut_percent=creator_cut_percent,
            referral_l1_percent=referral_l1_percent,
            referral_l2_percent=referral_l2_percent,
            commission_cap_rub=settings_snapshot.commission_cap_rub,
            commission_min_rub=settings_snapshot.commission_min_rub,
        ),
        "rng_audit": {
            "algorithm": "HMAC-SHA256",
            "commit": rng_commit,
            "seed": seed,
            "nonce": nonce,
            "message": f"{body.game_id}:{nonce}",
            "digest_hex": hmac.new(
                seed.encode("utf-8"),
                f"{body.game_id}:{nonce}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
            "threshold": str(threshold),
            "won": won,
            "player_pips": player_pips,
            "house_pips": house_pips,
        },
    }
    game = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_commit, rng_seed_reveal, rng_nonce,
            game_data, started_at
        ) VALUES (
            $1, 'cub', $2, $3, $3, $4, $5, 'active', 'house_robot', $6,
            $7, $8, $9, $10, $11, $12::jsonb, now()
        )
        RETURNING id
        """,
        body.game_id, body.telegram_id, stake, settlement.payout, hold_id,
        int(profile["account_id"]), int(profile["id"]), int(policy["id"]),
        rng_commit, seed, nonce, json.dumps(game_data, separators=(",", ":")),
    )
    if not game:
        raise HTTPException(status_code=409, detail="Cub game creation conflicts")
    consumed = await conn.execute(
        """
        UPDATE casino_house_rng_commits
        SET status = 'consumed', consumed_at = now()
        WHERE game_id = $1 AND telegram_id = $2 AND game_type = 'cub'
          AND status = 'pending'
        """,
        body.game_id,
        body.telegram_id,
    )
    if consumed != "UPDATE 1":
        raise HTTPException(status_code=409, detail="Cub fairness commitment was already consumed")
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, body.telegram_id, body.game_id, stake, order_ref,
    )
    reservation = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $2, updated_at = now()
        WHERE id = $1 AND balance_rub - reserved_rub >= $2
        RETURNING balance_rub, reserved_rub
        """,
        int(profile["account_id"]), max_settlement.payout,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="Cub house bankroll is insufficient")
    await conn.execute(
        """
        INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
        VALUES ($1, $2, $3, $4)
        """,
        f"cub-reserve-{body.game_id}", int(profile["account_id"]), body.game_id,
        max_settlement.payout,
    )
    await confirm_unified_hold(
        conn, user_id=body.telegram_id, order_ref=order_ref, amount_rub=stake,
        note=f"Casino cub stake: {body.game_id}",
    )
    if won:
        await _credit_winner(
            conn, game_id=body.game_id, winner_id=body.telegram_id, payout_rub=settlement.payout
        )
    account = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $2 - $3,
            reserved_rub = reserved_rub - $4,
            updated_at = now()
        WHERE id = $1 AND reserved_rub >= $4
        RETURNING balance_rub, reserved_rub
        """,
        int(profile["account_id"]), stake, settlement.payout, max_settlement.payout,
    )
    if not account:
        raise HTTPException(status_code=409, detail="Cub house reservation conflicts")
    casino_creator_account = await _resolve_active_creator_account(conn)
    referral_l1_id, referral_l2_id = await _resolve_loser_referrals(conn, body.telegram_id)
    pricing_snapshot = game_data["pricing_snapshot"]
    allocations = allocate_commission(
        stake,
        commission_rate=pricing_snapshot["commission_rate"],
        creator_percent=pricing_snapshot["creator_cut_percent"],
        referral_l1_percent=pricing_snapshot["referral_l1_percent"],
        referral_l2_percent=pricing_snapshot["referral_l2_percent"],
        has_creator=casino_creator_account is not None,
        has_referral_l1=referral_l1_id is not None,
        has_referral_l2=referral_l2_id is not None,
        commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub"),
        commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub"),
    )
    await _record_commissions(
        conn,
        game_pk=int(game["id"]),
        game_id=body.game_id,
        casino_creator_account=casino_creator_account,
        referral_l1_id=referral_l1_id,
        referral_l2_id=referral_l2_id,
        allocations=allocations,
    )
    outcome = {"kind": "win" if won else "loss", "winner_id": body.telegram_id if won else None}
    await conn.execute(
        """
        INSERT INTO casino_house_ledger (
            account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
        ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)
        """,
        int(profile["account_id"]), body.game_id, f"cub-settlement-{body.game_id}",
        settlement.house_delta, money(account["balance_rub"]), f"Cub {'win' if won else 'loss'} settlement",
    )
    await conn.execute(
        """
        UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        body.game_id,
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    await conn.execute(
        """
        UPDATE casino_games
        SET status = 'finished', winner_id = $2, outcome = $3::jsonb,
            commission_rub = $4, finished_at = now(), updated_at = now()
        WHERE game_id = $1
        """,
        body.game_id, body.telegram_id if won else None,
        json.dumps(outcome, separators=(",", ":")), settlement.commission,
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, body.telegram_id)
    return {
        "success": True,
        "idempotent": False,
        "game_id": body.game_id,
        "outcome": outcome,
        "stake_rub": _text_money(stake),
        "commission_rub": _text_money(settlement.commission),
        "payout_rub": _text_money(settlement.payout),
        "house_balance_rub": _text_money(account["balance_rub"]),
        "rng": game_data["rng_audit"],
        "player_pips": player_pips,
        "house_pips": house_pips,
    }


def _cub_open_payload(game_id: str, stake, *, already_open: bool) -> dict:
    return {
        "success": True,
        "already_open": already_open,
        "game_id": game_id,
        "status": "waiting_player_roll",
        "stake_rub": _text_money(stake),
    }


def _cub_finished_payload(existing: Mapping[str, object], *, idempotent: bool) -> dict:
    game_data = _json_object(existing.get("game_data"))
    return {
        "success": True,
        "idempotent": idempotent,
        "tie": False,
        "game_id": str(existing.get("game_id") or ""),
        "outcome": _json_object(existing.get("outcome")),
        "stake_rub": _text_money(existing.get("bet_rub") or 0),
        "commission_rub": _text_money(existing.get("commission_rub") or 0),
        "payout_rub": _text_money(existing.get("payout_rub") or 0),
        "player_value": game_data.get("player_value"),
        "house_value": game_data.get("house_value"),
        "source": game_data.get("source") or "telegram_dice",
    }


async def _load_cub_house_for_open(conn, *, telegram_id: int, stake: Decimal) -> dict:
    """Policy, robot, and max house exposure for a new cub hold."""
    settings_snapshot = await load_casino_settings(conn)
    commission_rate = await commission_rate_for_player(conn, telegram_id)
    commission_profile, _ = await commission_profile_for_player(conn, telegram_id)
    if not settings_snapshot.enabled_games.get("cub", False):
        raise HTTPException(status_code=409, detail="Cub is disabled")

    policy = await conn.fetchrow(
        """
        SELECT id, payout_multiplier, win_probability, terms
        FROM casino_house_policies
        WHERE game_type = 'cub' AND is_active = TRUE
        FOR UPDATE
        """
    )
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.account_id, rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub,
               ha.account_key, ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND rp.allowed_games ? 'cub'
        ORDER BY rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """
    )
    if not policy or not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="Cub house robot is unavailable")
    if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
        raise HTTPException(status_code=409, detail="Stake is outside the robot limits")

    win_probability = Decimal(str(policy["win_probability"]))
    payout_multiplier = Decimal(str(policy["payout_multiplier"]))
    if not Decimal("0") < win_probability < Decimal("1"):
        raise HTTPException(status_code=409, detail="Cub policy is invalid")
    _assert_stake_within_limits(
        settings_snapshot,
        "cub",
        stake,
        payout_multiplier=payout_multiplier,
        bankroll_rub=money(profile["balance_rub"]),
    )
    max_settlement = calculate_house_settlement(
        stake,
        payout_multiplier,
        commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    exposure_limit = money(profile["max_exposure_rub"])
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"])
    if (exposure_limit > 0 and max_settlement.payout > exposure_limit) or available < max_settlement.payout:
        raise HTTPException(status_code=409, detail="Cub house bankroll is insufficient")
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    return {
        "settings_snapshot": settings_snapshot,
        "policy": policy,
        "profile": profile,
        "commission_rate": commission_rate,
        "commission_profile": commission_profile,
        "payout_multiplier": payout_multiplier,
        "max_settlement": max_settlement,
        "creator_cut_percent": creator_cut_percent,
        "referral_l1_percent": referral_l1_percent,
        "referral_l2_percent": referral_l2_percent,
    }


async def pending_cub_with_conn(conn, telegram_id: int) -> dict:
    row = await conn.fetchrow(
        """
        SELECT game_id, bet_rub, status, game_data
        FROM casino_games
        WHERE creator_id = $1 AND game_type = 'cub' AND counterparty_kind = 'house_robot'
          AND status = 'waiting'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        telegram_id,
    )
    if not row:
        return {"success": True, "pending": None}
    return {
        "success": True,
        "pending": {
            "game_id": str(row["game_id"]),
            "stake_rub": _text_money(row["bet_rub"]),
            "status": "waiting_player_roll",
        },
    }


async def open_cub_with_conn(conn, body: CubOpenRequest) -> dict:
    """Hold a house cub stake and wait for live Telegram dice."""
    await lock_casino_users(conn, (body.telegram_id,))
    stake = money(body.stake_rub)
    existing = await conn.fetchrow(
        """
        SELECT game_id, bet_rub, status, creator_id, game_type
        FROM casino_games
        WHERE creator_id = $1 AND game_type = 'cub' AND counterparty_kind = 'house_robot'
          AND status = 'waiting'
        ORDER BY created_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        body.telegram_id,
    )
    if existing:
        if money(existing["bet_rub"]) != stake:
            raise HTTPException(status_code=409, detail="A cub round is already waiting for your dice")
        return _cub_open_payload(str(existing["game_id"]), stake, already_open=True)

    ctx = await _load_cub_house_for_open(conn, telegram_id=body.telegram_id, stake=stake)
    policy = ctx["policy"]
    profile = ctx["profile"]
    max_settlement = ctx["max_settlement"]
    game_id = str(uuid4())
    await lock_casino_game(conn, game_id)

    hold_id = f"casino-{game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    await reserve_unified_funds(
        conn, user_id=body.telegram_id, order_ref=order_ref, amount_rub=stake
    )
    game_data = {
        "phase": "waiting_player_roll",
        "source": "telegram_dice",
        "reserved_payout_rub": _text_money(max_settlement.payout),
        "house_policy_snapshot": {
            "policy_id": int(policy["id"]),
            "payout_multiplier": _text_money(ctx["payout_multiplier"]),
            "win_probability": str(Decimal(str(policy["win_probability"]))),
        },
        "pricing_snapshot": _pricing_snapshot_payload(
            commission_profile=ctx["commission_profile"],
            commission_rate=ctx["commission_rate"],
            creator_cut_percent=ctx["creator_cut_percent"],
            referral_l1_percent=ctx["referral_l1_percent"],
            referral_l2_percent=ctx["referral_l2_percent"],
            commission_cap_rub=ctx["settings_snapshot"].commission_cap_rub,
            commission_min_rub=ctx["settings_snapshot"].commission_min_rub,
        ),
    }
    game = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, game_data, started_at
        ) VALUES (
            $1, 'cub', $2, $3, $3, 0, $4, 'waiting', 'house_robot', $5,
            $6, $7, $8::jsonb, now()
        )
        RETURNING id
        """,
        game_id, body.telegram_id, stake, hold_id,
        int(profile["account_id"]), int(profile["id"]), int(policy["id"]),
        json.dumps(game_data, separators=(",", ":")),
    )
    if not game:
        raise HTTPException(status_code=409, detail="Cub game creation conflicts")
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, body.telegram_id, game_id, stake, order_ref,
    )
    reservation = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $2, updated_at = now()
        WHERE id = $1 AND balance_rub - reserved_rub >= $2
        RETURNING balance_rub, reserved_rub
        """,
        int(profile["account_id"]), max_settlement.payout,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="Cub house bankroll is insufficient")
    await conn.execute(
        """
        INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
        VALUES ($1, $2, $3, $4)
        """,
        f"cub-reserve-{game_id}", int(profile["account_id"]), game_id,
        max_settlement.payout,
    )
    return _cub_open_payload(game_id, stake, already_open=False)


async def _settle_waiting_cub_with_conn(
    conn,
    *,
    existing: Mapping[str, object],
    player_value: int,
    house_value: int,
) -> dict:
    game_id = str(existing["game_id"])
    telegram_id = int(existing["creator_id"])
    stake = money(existing["bet_rub"])
    hold_id = str(existing["creator_hold_id"])
    game_data = _json_object(existing.get("game_data"))
    policy_snap = _json_object(game_data.get("house_policy_snapshot"))
    pricing_snapshot = _json_object(game_data.get("pricing_snapshot"))
    if not policy_snap or not pricing_snapshot:
        raise HTTPException(status_code=409, detail="Cub pricing snapshot is missing")
    payout_multiplier = Decimal(str(policy_snap.get("payout_multiplier") or "0"))
    commission_rate = Decimal(str(pricing_snapshot.get("commission_rate") or "0"))
    won = player_value > house_value
    settlement = calculate_house_settlement(
        stake,
        payout_multiplier if won else Decimal("0"),
        commission_rate,
        commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub"),
        commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub"),
    )
    reservation = await conn.fetchrow(
        """
        SELECT amount_rub, account_id
        FROM casino_house_reservations
        WHERE game_id = $1 AND status = 'active'
        FOR UPDATE
        """,
        game_id,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="Cub house reservation is missing")
    reserved_payout = money(reservation["amount_rub"])
    house_account_id = int(reservation["account_id"])
    order_ref = casino_ledger_order_ref(hold_id)
    await confirm_unified_hold(
        conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake,
        note=f"Casino cub stake: {game_id}",
    )
    if won:
        await _credit_winner(
            conn, game_id=game_id, winner_id=telegram_id, payout_rub=settlement.payout
        )
    account = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $2 - $3,
            reserved_rub = reserved_rub - $4,
            updated_at = now()
        WHERE id = $1 AND reserved_rub >= $4
        RETURNING balance_rub, reserved_rub
        """,
        house_account_id, stake, settlement.payout, reserved_payout,
    )
    if not account:
        raise HTTPException(status_code=409, detail="Cub house reservation conflicts")
    casino_creator_account = await _resolve_active_creator_account(conn)
    referral_l1_id, referral_l2_id = await _resolve_loser_referrals(conn, telegram_id)
    allocations = allocate_commission(
        stake,
        commission_rate=pricing_snapshot["commission_rate"],
        creator_percent=pricing_snapshot["creator_cut_percent"],
        referral_l1_percent=pricing_snapshot["referral_l1_percent"],
        referral_l2_percent=pricing_snapshot["referral_l2_percent"],
        has_creator=casino_creator_account is not None,
        has_referral_l1=referral_l1_id is not None,
        has_referral_l2=referral_l2_id is not None,
        commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub"),
        commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub"),
    )
    await _record_commissions(
        conn,
        game_pk=int(existing["id"]),
        game_id=game_id,
        casino_creator_account=casino_creator_account,
        referral_l1_id=referral_l1_id,
        referral_l2_id=referral_l2_id,
        allocations=allocations,
    )
    outcome = {"kind": "win" if won else "loss", "winner_id": telegram_id if won else None}
    game_data["phase"] = "finished"
    game_data["source"] = "telegram_dice"
    game_data["player_value"] = player_value
    game_data["house_value"] = house_value
    game_data["won"] = won
    await conn.execute(
        """
        INSERT INTO casino_house_ledger (
            account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
        ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)
        """,
        house_account_id, game_id, f"cub-settlement-{game_id}",
        settlement.house_delta, money(account["balance_rub"]),
        f"Cub {'win' if won else 'loss'} settlement",
    )
    await conn.execute(
        """
        UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    finished = await conn.fetchrow(
        """
        UPDATE casino_games
        SET status = 'finished', winner_id = $2, outcome = $3::jsonb,
            commission_rub = $4, payout_rub = $5, game_data = $6::jsonb,
            finished_at = now(), updated_at = now()
        WHERE game_id = $1 AND status = 'waiting'
        RETURNING *
        """,
        game_id, telegram_id if won else None,
        json.dumps(outcome, separators=(",", ":")), settlement.commission, settlement.payout,
        json.dumps(game_data, separators=(",", ":")),
    )
    if not finished:
        raise HTTPException(status_code=409, detail="Cub game requires manual recovery")
    payload = _cub_finished_payload(finished, idempotent=False)
    payload["house_balance_rub"] = _text_money(account["balance_rub"])
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    return payload


async def resolve_cub_with_conn(conn, body: CubResolveRequest) -> dict:
    """Settle a waiting house cub from two live Telegram dice, or keep the hold on a tie."""
    await lock_casino_game(conn, body.game_id)
    await lock_casino_users(conn, (body.telegram_id,))
    existing = await conn.fetchrow(
        "SELECT * FROM casino_games WHERE game_id = $1 FOR UPDATE", body.game_id
    )
    if not existing:
        raise HTTPException(status_code=409, detail="Cub game is missing")
    if (
        str(existing["game_type"]) != "cub"
        or int(existing["creator_id"]) != body.telegram_id
        or str(existing.get("counterparty_kind") or "") != "house_robot"
    ):
        raise HTTPException(status_code=409, detail="Existing cub game conflicts")
    if str(existing["status"]) == "finished":
        return _cub_finished_payload(existing, idempotent=True)
    if str(existing["status"]) != "waiting":
        raise HTTPException(status_code=409, detail="Cub game requires manual recovery")

    if body.player_value == body.house_value:
        game_data = _json_object(existing.get("game_data"))
        ties = list(game_data.get("ties") or [])
        ties.append({"player_value": body.player_value, "house_value": body.house_value})
        game_data["ties"] = ties
        game_data["source"] = "telegram_dice"
        game_data["phase"] = "waiting_player_roll"
        await conn.execute(
            """
            UPDATE casino_games
            SET game_data = $2::jsonb, updated_at = now()
            WHERE game_id = $1 AND status = 'waiting'
            """,
            body.game_id,
            json.dumps(game_data, separators=(",", ":")),
        )
        return {
            "success": True,
            "idempotent": False,
            "tie": True,
            "game_id": body.game_id,
            "player_value": body.player_value,
            "house_value": body.house_value,
            "source": "telegram_dice",
            "stake_rub": _text_money(existing.get("bet_rub") or 0),
        }

    return await _settle_waiting_cub_with_conn(
        conn,
        existing=existing,
        player_value=body.player_value,
        house_value=body.house_value,
    )


async def create_pvp_from_dm_with_conn(conn, body: CasinoDmPvpCreateRequest) -> dict:
    """Atomically reserve a DM-created PVP game and its group invitation intent.

    The shared binding lock serializes this transaction with admin binding rotation.
    Existing games retain their pinned chat; only a new game reads the active binding.
    """
    await conn.execute("SELECT pg_advisory_xact_lock(741921)")
    await lock_casino_game(conn, body.game_id)
    await lock_casino_users(conn, (body.creator_id,))
    existing = await conn.fetchrow("SELECT * FROM casino_games WHERE game_id = $1 FOR UPDATE", body.game_id)
    if existing:
        existing_pvp = _json_object(_json_object(existing.get("game_data")).get("pvp"))
        if (
            str(existing["game_type"]) != body.game_type
            or int(existing["creator_id"]) != body.creator_id
            or money(existing["bet_rub"]) != money(body.stake_rub)
            or int(existing_pvp.get("rounds") or 1) != body.rounds
        ):
            raise HTTPException(status_code=409, detail="Existing game conflicts")
        intent = await conn.fetchrow(
            "SELECT id, status, telegram_message_id FROM casino_pvp_invitation_outbox WHERE game_id = $1",
            body.game_id,
        )
        return {
            "success": True,
            "idempotent": True,
            "game": _game_response(existing),
            "invitation": _invitation_outbox_response(intent) if intent else None,
        }

    binding = await conn.fetchrow(
        """
        SELECT id, chat_id, updated_at
        FROM casino_game_chat_bindings
        WHERE status = 'active'
        ORDER BY confirmed_at DESC NULLS LAST, id DESC
        LIMIT 1
        FOR UPDATE
        """
    )
    if not binding:
        raise HTTPException(status_code=409, detail="No active casino game chat binding")

    casino_settings = await load_casino_settings(conn)
    stake = money(body.stake_rub)
    if not casino_settings.enabled_games.get(body.game_type, False):
        raise HTTPException(status_code=409, detail="Game type is disabled")
    _assert_stake_within_limits(casino_settings, body.game_type, stake)

    hold_id = f"casino-{body.game_id}-creator"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=body.creator_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Insufficient balance") from exc
    binding_revision = int(_utc(binding["updated_at"]).timestamp() * 1_000_000)
    game_data = {"pvp": {"rounds": body.rounds}}
    scope = await active_scope(conn, body.creator_id)
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_games", scope, next_index=10
    )
    row = await conn.fetchrow(
        f"""
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, creator_hold_id, status, game_state,
            game_chat_binding_id, game_chat_id, game_chat_binding_revision, game_data{scope_cols}
        ) VALUES ($1, $2, $3, $4, $5, 'waiting', '{{}}'::jsonb, $6, $7, $8, $9::jsonb{scope_params})
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
                  game_chat_binding_revision
        """,
        body.game_id, body.game_type, body.creator_id, stake, hold_id, int(binding["id"]),
        int(binding["chat_id"]), binding_revision, json.dumps(game_data, separators=(",", ":")),
        *scope_values,
    )
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at)
        VALUES ($1, $2, $3, $4, 'creator', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, body.creator_id, body.game_id, stake, order_ref,
    )
    
    # Создаём outbox запись только если игра должна быть опубликована в группу
    intent = None
    if body.publish_to_group:
        intent = await conn.fetchrow(
            """
            INSERT INTO casino_pvp_invitation_outbox (event_key, game_id, chat_id, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id, status, telegram_message_id
            """,
            f"casino-pvp-invitation:{body.game_id}", body.game_id, int(binding["chat_id"]),
            json.dumps({"game_id": body.game_id, "chat_id": int(binding["chat_id"]), "game_type": body.game_type,
                        "creator_id": body.creator_id, "stake_rub": _text_money(stake), "rounds": body.rounds}, separators=(",", ":")),
        )
    
    return {"success": True, "idempotent": False, "game": _game_response(row), "invitation": _invitation_outbox_response(intent)}


def _invitation_outbox_response(row: Mapping[str, object] | None) -> dict | None:
    if not row:
        return None
    item = _row_dict(row)
    return {"outbox_id": int(item["id"]), "status": str(item["status"]), "telegram_message_id": item.get("telegram_message_id")}


async def claim_pvp_invitation_outbox_with_conn(conn, body: ClaimRequest) -> dict:
    claim_token = f"{body.worker_id}:{uuid4().hex}"
    rows = await conn.fetch(
        """
        WITH candidates AS (
            SELECT id FROM casino_pvp_invitation_outbox
            WHERE (status = 'pending' AND available_at <= now())
               OR (status = 'processing' AND claimed_at < now() - make_interval(secs => $3))
            ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT $2
        )
        UPDATE casino_pvp_invitation_outbox outbox
        SET status = 'processing', claim_token = $1, claimed_at = now(), attempts = attempts + 1, updated_at = now()
        FROM candidates WHERE outbox.id = candidates.id
        RETURNING outbox.id, outbox.game_id, outbox.chat_id, outbox.payload, outbox.attempts, outbox.claimed_at
        """, claim_token, body.limit, body.lease_seconds,
    )
    return {"success": True, "items": [
        {"outbox_id": int(row["id"]), "game_id": str(row["game_id"]), "chat_id": int(row["chat_id"]),
         "payload": _json_object(row["payload"]), "attempts": int(row["attempts"]), "claim_token": claim_token,
         "claimed_at": _utc(row["claimed_at"]).isoformat()}
        for row in rows
    ]}


async def complete_pvp_invitation_outbox_with_conn(conn, body: InvitationOutboxCompleteRequest) -> dict:
    row = await conn.fetchrow(
        """UPDATE casino_pvp_invitation_outbox
           SET status = 'completed', telegram_message_id = $3, completed_at = now(), claim_token = NULL, updated_at = now()
           WHERE id = $1 AND status = 'processing' AND claim_token = $2
             AND claimed_at >= now() - interval '1 hour'
           RETURNING id, game_id, telegram_message_id, completed_at""",
        body.outbox_id, body.claim_token, body.telegram_message_id,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Invitation outbox claim is not owned or has expired")
    game = await conn.fetchrow(
        """UPDATE casino_games
           SET game_state = jsonb_build_object(
                 'game_id', game_id,
                 'game_type', CASE
                     WHEN game_type = 'pvp_dice' AND COALESCE((game_data #>> '{pvp,rounds}')::integer, 1) = 2 THEN '2cub'
                     WHEN game_type = 'pvp_dice' THEN 'cub'
                     WHEN game_type = 'pvp_darts' AND COALESCE((game_data #>> '{pvp,rounds}')::integer, 1) = 2 THEN '2darts'
                     WHEN game_type = 'pvp_darts' THEN 'darts'
                     WHEN game_type = 'pvp_bowling' AND COALESCE((game_data #>> '{pvp,rounds}')::integer, 1) = 2 THEN '2boul'
                     WHEN game_type = 'pvp_bowling' THEN 'boul'
                     WHEN game_type = 'pvp_football' AND COALESCE((game_data #>> '{pvp,rounds}')::integer, 1) = 2 THEN '2fut'
                     WHEN game_type = 'pvp_football' THEN 'fut'
                     WHEN game_type = 'pvp_basketball' AND COALESCE((game_data #>> '{pvp,rounds}')::integer, 1) = 2 THEN '2basket'
                     WHEN game_type = 'pvp_basketball' THEN 'basket'
                     WHEN game_type = 'baccara' THEN 'baccara'
                     WHEN game_type = 'blackjack' THEN 'blackjack'
                 END,
                 'chat_id', game_chat_id,
                 'message_id', $2::integer,
                 'roll_msg_id', NULL,
                 'creator_rolls', '[]'::jsonb,
                 'opponent_rolls', '[]'::jsonb,
                 'status', 'waiting'
               ),
               state_version = state_version + 1, updated_at = now()
           WHERE game_id = $1 AND status = 'waiting' AND game_chat_id IS NOT NULL
           RETURNING game_id""",
        str(row["game_id"]), body.telegram_message_id,
    )
    if not game:
        raise HTTPException(status_code=409, detail="Invitation game is no longer publishable")
    return {"success": True, "outbox_id": int(row["id"]), "game_id": str(row["game_id"]),
            "telegram_message_id": int(row["telegram_message_id"]), "completed_at": _utc(row["completed_at"]).isoformat()}


async def _cancel_unpublished_pvp_invitation_game_with_conn(conn, game_id: str, *, reason: str) -> None:
    """Refund a never-published DM game once its invitation becomes permanently undeliverable."""
    await lock_casino_game(conn, game_id)
    game = await conn.fetchrow(
        """SELECT game_id, creator_id, creator_hold_id, bet_rub, status
           FROM casino_games WHERE game_id = $1 FOR UPDATE""", game_id,
    )
    if not game or str(game["status"]) != "waiting":
        return
    creator_id = int(game["creator_id"])
    hold_id = str(game["creator_hold_id"] or "")
    if not hold_id:
        raise HTTPException(status_code=409, detail="Unpublished game has no creator hold")
    await lock_casino_users(conn, (creator_id,))
    hold = await conn.fetchrow(
        """SELECT hold_id, telegram_id, game_id, amount_rub, ledger_order_ref, status
           FROM casino_balance_holds WHERE hold_id = $1 FOR UPDATE""", hold_id,
    )
    if not hold or str(hold["status"]) != "active" or int(hold["telegram_id"]) != creator_id \
            or str(hold["game_id"]) != game_id or money(hold["amount_rub"]) != money(game["bet_rub"]) \
            or not hold["ledger_order_ref"]:
        raise HTTPException(status_code=409, detail="Unpublished game hold conflicts")
    await release_unified_hold(
        conn, user_id=creator_id, order_ref=str(hold["ledger_order_ref"]), amount_rub=money(game["bet_rub"]),
        note=f"Casino invitation unavailable: {game_id}",
    )
    await conn.execute(
        "UPDATE casino_balance_holds SET status = 'released', released_at = now() WHERE hold_id = $1 AND status = 'active'",
        hold_id,
    )
    cancelled = await conn.fetchrow(
        """UPDATE casino_games SET status = 'cancelled', finished_at = now(), updated_at = now(),
               game_data = game_data || jsonb_build_object('release_reason', $2::text)
           WHERE game_id = $1 AND status = 'waiting'
           RETURNING game_id""", game_id, reason,
    )
    if not cancelled:
        raise HTTPException(status_code=409, detail="Unpublished game cancellation conflicts")


async def fail_pvp_invitation_outbox_with_conn(conn, body: OutboxFailRequest) -> dict:
    row = await conn.fetchrow(
        """UPDATE casino_pvp_invitation_outbox
           SET status = CASE WHEN attempts >= 10 THEN 'dead' ELSE 'pending' END,
               available_at = now() + make_interval(secs => LEAST(3600, 5 * (2 ^ LEAST(attempts, 9))::integer)),
               claim_token = NULL, last_error = $3, updated_at = now()
           WHERE id = $1 AND status = 'processing' AND claim_token = $2
           RETURNING id, game_id, status, attempts, available_at, payload""",
        body.outbox_id, body.claim_token, body.error,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Invitation outbox claim is not owned or has expired")
    payload = _json_object(row.get("payload"))
    if str(row["status"]) == "dead" and str(payload.get("origin") or "") != "web":
        await _cancel_unpublished_pvp_invitation_game_with_conn(
            conn, str(row["game_id"]), reason=f"Invitation delivery failed: {body.error}",
        )
    return {"success": True, "outbox_id": int(row["id"]), "game_id": str(row["game_id"]),
            "status": str(row["status"]), "attempts": int(row["attempts"]),
            "available_at": _utc(row["available_at"]).isoformat()}


_WEB_INVITATION_ORIGIN = "web"


async def enqueue_web_duel_invitation_with_conn(
    conn,
    *,
    game_id: str,
    game_type: str,
    creator_id: int,
    stake_rub,
) -> dict | None:
    """Pin a site-created waiting duel to the active game group and enqueue the Telegram card.

    Telegram-created games post locally or use create_pvp_from_dm. Do not call this from
    create_or_resume: that would double-post group baccarat/blackjack. Missing binding skips
    silently so the site game still exists.
    """
    await conn.execute("SELECT pg_advisory_xact_lock(741921)")
    existing = await conn.fetchrow(
        "SELECT id, status, telegram_message_id FROM casino_pvp_invitation_outbox WHERE game_id = $1",
        game_id,
    )
    if existing:
        return _invitation_outbox_response(existing)
    binding = await conn.fetchrow(
        """
        SELECT id, chat_id, updated_at
        FROM casino_game_chat_bindings
        WHERE status = 'active'
        ORDER BY confirmed_at DESC NULLS LAST, id DESC
        LIMIT 1
        FOR UPDATE
        """
    )
    if not binding:
        return None
    binding_revision = int(_utc(binding["updated_at"]).timestamp() * 1_000_000)
    pinned = await conn.fetchrow(
        """
        UPDATE casino_games
        SET game_chat_binding_id = $2,
            game_chat_id = $3,
            game_chat_binding_revision = $4,
            updated_at = now()
        WHERE game_id = $1 AND status = 'waiting'
          AND (game_chat_id IS NULL OR game_chat_id = $3)
        RETURNING game_id
        """,
        game_id, int(binding["id"]), int(binding["chat_id"]), binding_revision,
    )
    if not pinned:
        return None
    rounds = 0 if game_type in CARD_GAME_TYPES else 1
    intent = await conn.fetchrow(
        """
        INSERT INTO casino_pvp_invitation_outbox (event_key, game_id, chat_id, payload)
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (game_id) DO NOTHING
        RETURNING id, status, telegram_message_id
        """,
        f"casino-pvp-invitation:{game_id}", game_id, int(binding["chat_id"]),
        json.dumps(
            {
                "game_id": game_id,
                "chat_id": int(binding["chat_id"]),
                "game_type": game_type,
                "creator_id": creator_id,
                "stake_rub": _text_money(stake_rub),
                "rounds": rounds,
                "origin": _WEB_INVITATION_ORIGIN,
            },
            separators=(",", ":"),
        ),
    )
    if intent:
        return _invitation_outbox_response(intent)
    replay = await conn.fetchrow(
        "SELECT id, status, telegram_message_id FROM casino_pvp_invitation_outbox WHERE game_id = $1",
        game_id,
    )
    return _invitation_outbox_response(replay)


async def create_or_resume_game_with_conn(conn, body: CasinoGameCreateRequest) -> dict:
    if body.game_type in RETIRED_SPORT_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Эта игра больше не доступна")
    await lock_casino_game(conn, body.game_id)
    await lock_casino_users(conn, (body.creator_id,))
    existing = await conn.fetchrow("SELECT * FROM casino_games WHERE game_id = $1 FOR UPDATE", body.game_id)
    if existing:
        if (
            str(existing["game_type"]) != body.game_type
            or int(existing["creator_id"]) != body.creator_id
            or money(existing["bet_rub"]) != money(body.stake_rub)
        ):
            raise HTTPException(status_code=409, detail="Existing game conflicts")
        return {"success": True, "idempotent": True, "game": _game_response(existing)}

    casino_settings = await load_casino_settings(conn)
    stake = money(body.stake_rub)
    if not casino_settings.enabled_games.get(body.game_type, False):
        raise HTTPException(status_code=409, detail="Game type is disabled")
    _assert_stake_within_limits(casino_settings, body.game_type, stake)

    hold_id = f"casino-{body.game_id}-creator"
    order_ref = casino_ledger_order_ref(hold_id)
    scope = await active_scope(conn, body.creator_id)
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_games", scope, next_index=6
    )
    try:
        await reserve_unified_funds(conn, user_id=body.creator_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Insufficient balance") from exc
    row = await conn.fetchrow(
        f"""
        INSERT INTO casino_games (game_id, game_type, creator_id, bet_rub, creator_hold_id, status, game_state{scope_cols})
        VALUES ($1, $2, $3, $4, $5, 'waiting', '{{}}'::jsonb{scope_params})
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        body.game_id, body.game_type, body.creator_id, stake, hold_id,
        *scope_values,
    )
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at)
        VALUES ($1, $2, $3, $4, 'creator', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, body.creator_id, body.game_id, stake, order_ref,
    )
    game = _game_response(row)
    if body.game_type in CARD_GAME_TYPES:
        rng_commit = await _bind_card_commit_to_game(
            conn,
            game_id=body.game_id,
            game_type=body.game_type,
            telegram_id=body.creator_id,
        )
        game["rng_commit"] = rng_commit
    return {"success": True, "idempotent": False, "game": game}


async def join_robot_and_reserve_game_with_conn(conn, body: CasinoGameJoinRobotRequest) -> dict:
    """Match a waiting PVP game with a house-backed robot, never a Telegram user."""
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    if str(game.get("counterparty_kind") or "player") == "pvp_robot":
        return {
            "success": True,
            "idempotent": True,
            "game": _game_response(game),
            "robot": _json_object(_json_object(game.get("game_data")).get("robot_profile")),
        }
    if str(game["status"]) != "waiting" or game["opponent_id"] is not None:
        raise HTTPException(status_code=409, detail="Game cannot be joined by a robot")
    if not str(game["game_type"]).startswith("pvp_"):
        raise HTTPException(status_code=409, detail="Only PVP games support a robot opponent")

    creator_id = int(game["creator_id"])
    await lock_casino_users(conn, (creator_id,))
    stake = money(game["bet_rub"])
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.profile_key, rp.display_name, rp.account_id, rp.min_bet_rub,
               rp.max_bet_rub, rp.max_concurrent_games, rp.max_exposure_rub,
               ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'pvp_robot' AND rp.is_active = TRUE
          AND rp.allowed_games ? $1
        ORDER BY rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """,
        str(game["game_type"]),
    )
    if not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="PVP robot is unavailable")
    if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
        raise HTTPException(status_code=409, detail="Stake is outside the robot limits")

    concurrent = await conn.fetchval(
        """SELECT COUNT(*) FROM casino_games
           WHERE robot_profile_id = $1 AND status IN ('active', 'outcome_committed')""",
        int(profile["id"]),
    )
    if int(concurrent or 0) >= int(profile["max_concurrent_games"]):
        raise HTTPException(status_code=409, detail="PVP robot concurrency limit reached")

    settings_snapshot = await load_casino_settings(conn)
    settlement = calculate_equal_stake_settlement(stake, settings_snapshot.commission_rate)
    exposure = stake * Decimal("2")
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"])
    if (money(profile["max_exposure_rub"]) > 0 and exposure > money(profile["max_exposure_rub"])) or available < exposure:
        raise HTTPException(status_code=409, detail="PVP robot bankroll is insufficient")

    reservation = await conn.fetchrow(
        """UPDATE casino_house_accounts
           SET reserved_rub = reserved_rub + $2, updated_at = now()
           WHERE id = $1 AND balance_rub - reserved_rub >= $2
           RETURNING balance_rub, reserved_rub""",
        int(profile["account_id"]), exposure,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="PVP robot bankroll is insufficient")
    await conn.execute(
        """INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
           VALUES ($1, $2, $3, $4)""",
        f"pvp-robot-reserve-{body.game_id}", int(profile["account_id"]), body.game_id, exposure,
    )
    row = await conn.fetchrow(
        """UPDATE casino_games
           SET counterparty_kind = 'pvp_robot', house_account_id = $2, robot_profile_id = $3,
               status = 'active', started_at = COALESCE(started_at, now()), updated_at = now(),
               game_data = game_data || jsonb_build_object('robot_profile', jsonb_build_object(
                   'profile_key', $4::text, 'display_name', $5::text
               ))
           WHERE game_id = $1 AND status = 'waiting' AND opponent_id IS NULL
           RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                     opponent_hold_id, status, state_version, game_state, outcome, created_at,
                     started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision""",
        body.game_id, int(profile["account_id"]), int(profile["id"]),
        str(profile["profile_key"]), str(profile["display_name"]),
    )
    if not row:
        raise HTTPException(status_code=409, detail="Game robot join conflicts")
    return {
        "success": True,
        "idempotent": False,
        "game": _game_response(row),
        "robot": {"profile_key": str(profile["profile_key"]), "display_name": str(profile["display_name"])},
    }


async def join_and_hold_game_with_conn(conn, body: CasinoGameJoinRequest) -> dict:
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    if str(game["status"]) not in {"waiting", "active"}:
        raise HTTPException(status_code=409, detail="Game cannot be joined")
    from casino_pvp_cards import assert_card_duel_joinable

    assert_card_duel_joinable(dict(game))
    creator_id = int(game["creator_id"])
    if body.opponent_id == creator_id:
        raise HTTPException(status_code=409, detail="Creator cannot join own game")
    from casino_duels import reserved_opponent_of

    reserved = reserved_opponent_of(game)
    if reserved is not None and int(reserved) != int(body.opponent_id):
        raise HTTPException(status_code=409, detail="Этот вызов для другого игрока")
    await lock_casino_users(conn, (creator_id, body.opponent_id))
    if game["opponent_id"] is not None:
        if int(game["opponent_id"]) != body.opponent_id:
            raise HTTPException(status_code=409, detail="Game already has another opponent")
        from casino_pvp_cards import complete_site_card_duel_after_join

        latest = await complete_site_card_duel_after_join(conn, dict(game))
        return {"success": True, "idempotent": True, "game": _game_response(latest)}

    stake = money(game["bet_rub"])
    await assert_may_sit_at(conn, "casino_games", "game_id", body.game_id, body.opponent_id)
    casino_settings = await load_casino_settings(conn)
    _assert_stake_within_limits(casino_settings, str(game["game_type"]), stake)
    hold_id = f"casino-{body.game_id}-opponent"
    order_ref = casino_ledger_order_ref(hold_id)
    try:
        await reserve_unified_funds(conn, user_id=body.opponent_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Insufficient balance") from exc
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at)
        VALUES ($1, $2, $3, $4, 'opponent', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, body.opponent_id, body.game_id, stake, order_ref,
    )
    row = await conn.fetchrow(
        """
        UPDATE casino_games
        SET opponent_id = $2, opponent_hold_id = $3, status = 'active', started_at = COALESCE(started_at, now()), updated_at = now()
        WHERE game_id = $1
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, counterparty_kind, game_data, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        body.game_id, body.opponent_id, hold_id,
    )
    from casino_pvp_dice import (
        activate_on_join,
        is_group_chat_id,
        is_player_counterparty,
        is_pvp_dice,
        touch_active_holds,
        _chat_id_from_game as pvp_play_chat_id,
    )

    if not row:
        raise HTTPException(status_code=409, detail="Game join conflicts")
    latest = dict(row)
    if is_pvp_dice(latest) and is_player_counterparty(latest):
        latest = await activate_on_join(conn, latest)
    else:
        await touch_active_holds(conn, str(body.game_id))
    from casino_inbox import notify_player_joined
    from casino_pvp_cards import complete_site_card_duel_after_join

    await notify_player_joined(
        conn,
        joiner_id=int(body.opponent_id),
        other_ids=[creator_id],
        kind="duel",
        game_id=str(body.game_id),
        game_type=str(latest.get("game_type") or ""),
        stake_rub=stake,
        notify_joiner=not is_group_chat_id(pvp_play_chat_id(latest)),
    )
    latest = await complete_site_card_duel_after_join(conn, latest)
    response = _game_response(latest)
    return {"success": True, "idempotent": False, "game": response}


async def persist_game_state_with_conn(conn, body: CasinoGameStateRequest) -> dict:
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    if str(game["status"]) not in {"waiting", "active"}:
        raise HTTPException(status_code=409, detail="Game state is no longer mutable")
    from casino_pvp_dice import is_pvp_dice, merge_persisted_game_state

    incoming = dict(body.game_state)
    if is_pvp_dice(game):
        incoming = merge_persisted_game_state(_json_object(game.get("game_state")), incoming)
    row = await conn.fetchrow(
        """
        UPDATE casino_games SET game_state = $3::jsonb, state_version = state_version + 1, updated_at = now()
        WHERE game_id = $1 AND status IN ('waiting', 'active') AND state_version = $2
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        body.game_id, body.expected_state_version, json.dumps(incoming, separators=(",", ":")),
    )
    if not row:
        raise HTTPException(status_code=409, detail="Game state version conflicts")
    return {"success": True, "idempotent": False, "game": _game_response(row)}


async def commit_game_outcome_with_conn(conn, body: CasinoGameOutcomeRequest) -> dict:
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    if str(game["status"]) == "outcome_committed":
        persisted_winner = game["winner_id"]
        if (persisted_winner != body.winner_id) or _json_object(game.get("outcome")) != body.outcome:
            raise HTTPException(status_code=409, detail="Committed outcome conflicts")
        return {"success": True, "idempotent": True, "game": _game_response(game)}
    kind = str(body.outcome["kind"])
    allowed_statuses = {"active"} if kind in {"winner", "draw"} else {"waiting", "active"}
    if str(game["status"]) not in allowed_statuses:
        raise HTTPException(status_code=409, detail="Game outcome cannot be committed in its current state")
    if kind == "winner":
        if str(game.get("counterparty_kind") or "player") == "pvp_robot":
            if body.winner_id != int(game["creator_id"]):
                raise HTTPException(status_code=409, detail="PVP robot games may only name the player as winner")
        else:
            if game["opponent_id"] is None:
                raise HTTPException(status_code=409, detail="Winner outcome requires an opponent")
            if body.winner_id not in (int(game["creator_id"]), int(game["opponent_id"])):
                raise HTTPException(status_code=409, detail="Winner must be a game player")
    if kind == "house_win" and str(game.get("counterparty_kind") or "player") != "pvp_robot":
        raise HTTPException(status_code=409, detail="House win is only valid for a PVP robot game")

    # Freeze the rates at the irreversible outcome boundary. The active creator
    # and referral relationships are deliberately resolved at settlement time.
    pricing = await load_casino_settings(conn)
    player_id = (
        int(game["creator_id"])
        if str(game.get("counterparty_kind") or "player") == "pvp_robot"
        else int(body.winner_id or game["creator_id"])
    )
    commission_rate = await commission_rate_for_player(conn, player_id)
    commission_profile, _ = await commission_profile_for_player(conn, player_id)
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        pricing,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    pricing_snapshot = _pricing_snapshot_payload(
        commission_profile=commission_profile,
        commission_rate=commission_rate,
        creator_cut_percent=creator_cut_percent,
        referral_l1_percent=referral_l1_percent,
        referral_l2_percent=referral_l2_percent,
        commission_cap_rub=pricing.commission_cap_rub,
        commission_min_rub=pricing.commission_min_rub,
    )
    row = await conn.fetchrow(
        """
        UPDATE casino_games
        SET winner_id = $3, outcome = $4::jsonb, status = 'outcome_committed',
            outcome_committed_at = now(), state_version = state_version + 1, updated_at = now(),
            game_data = game_data || jsonb_build_object('pricing_snapshot', $5::jsonb)
        WHERE game_id = $1 AND status IN ('waiting', 'active') AND state_version = $2
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        body.game_id, body.expected_state_version, body.winner_id,
        json.dumps(body.outcome, separators=(",", ":")),
        json.dumps(pricing_snapshot, separators=(",", ":")),
    )
    if not row:
        raise HTTPException(status_code=409, detail="Game state version conflicts")
    response = _game_response(row)
    return {"success": True, "idempotent": False, "game": response}


async def _mark_game_manual_review(
    conn,
    *,
    game_id: str,
    reason: str,
) -> dict:
    """Persist an invariant failure without moving any money."""
    row = await conn.fetchrow(
        """
        UPDATE casino_games
        SET status = 'manual_review', updated_at = now(),
            game_data = game_data || jsonb_build_object('manual_review_reason', $2::text)
        WHERE game_id = $1
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                  opponent_hold_id, status, state_version, game_state, outcome, created_at,
                  started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision
        """,
        game_id,
        reason,
    )
    return {"success": False, "manual_review": True, "game": _game_response(row)}


async def _settle_non_winner_outcome_with_conn(conn, game: Mapping[str, object], *, reason: str | None = None) -> dict:
    """Atomically refund exactly the holds named by a committed non-winner outcome."""
    game_id = str(game["game_id"])
    expected_holds = [(str(game["creator_hold_id"] or ""), int(game["creator_id"]))]
    if game["opponent_id"] is not None:
        expected_holds.append((str(game["opponent_hold_id"] or ""), int(game["opponent_id"])))
    if any(not hold_id for hold_id, _ in expected_holds):
        return await _mark_game_manual_review(conn, game_id=game_id, reason="game is missing an expected hold reference")

    await lock_casino_users(conn, [user_id for _, user_id in expected_holds])
    holds = await conn.fetch(
        """SELECT hold_id, telegram_id, game_id, amount_rub, ledger_order_ref, status
           FROM casino_balance_holds WHERE game_id = $1 AND status = 'active' FOR UPDATE""",
        game_id,
    )
    holds_by_id = {str(hold["hold_id"]): hold for hold in holds}
    expected_hold_ids = {hold_id for hold_id, _ in expected_holds}
    if set(holds_by_id) != expected_hold_ids:
        return await _mark_game_manual_review(conn, game_id=game_id, reason="active holds do not match the immutable game contract")

    stake = money(game["bet_rub"])
    for hold_id, user_id in expected_holds:
        hold = holds_by_id[hold_id]
        if (
            int(hold["telegram_id"]) != user_id or str(hold["game_id"]) != game_id
            or money(hold["amount_rub"]) != stake or not hold["ledger_order_ref"]
        ):
            return await _mark_game_manual_review(conn, game_id=game_id, reason=f"hold {hold_id} violates the immutable game contract")

    for hold_id, user_id in expected_holds:
        hold = holds_by_id[hold_id]
        await release_unified_hold(
            conn, user_id=user_id, order_ref=str(hold["ledger_order_ref"]), amount_rub=stake,
            note=f"Casino outcome refunded: {game_id}",
        )
    await conn.execute(
        "UPDATE casino_balance_holds SET status = 'released', released_at = now() "
        "WHERE hold_id = ANY($1::varchar[]) AND status = 'active'", list(expected_hold_ids),
    )
    row = await conn.fetchrow(
        """UPDATE casino_games
           SET status = 'cancelled', finished_at = now(), updated_at = now(),
               game_data = game_data || jsonb_build_object('release_reason', $2::text)
           WHERE game_id = $1 AND status = 'outcome_committed'
           RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                     opponent_hold_id, status, state_version, game_state, outcome, created_at,
                     started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision""",
        game_id, reason,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Game release conflicts")
    response = _game_response(row)
    await _enqueue_notification(conn, game_id=game_id, event_type="game_released", payload=response)
    return {"success": True, "idempotent": False, "game": response, "state_version": response["state_version"]}


async def _settle_pvp_robot_outcome_with_conn(conn, game: Mapping[str, object], *, release: bool = False) -> dict:
    """Settle a robot match against the house account, never through PVP ledgers."""
    game_id = str(game["game_id"])
    creator_id = int(game["creator_id"])
    hold_id = str(game["creator_hold_id"] or "")
    account_id = game["house_account_id"]
    if not hold_id or account_id is None:
        return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot game is missing its house contract")

    await lock_casino_users(conn, (creator_id,))
    hold = await conn.fetchrow(
        """SELECT hold_id, telegram_id, game_id, amount_rub, ledger_order_ref, status
           FROM casino_balance_holds WHERE hold_id = $1 FOR UPDATE""",
        hold_id,
    )
    reservation = await conn.fetchrow(
        """SELECT id, amount_rub, status FROM casino_house_reservations
           WHERE game_id = $1 FOR UPDATE""",
        game_id,
    )
    if not hold or not reservation or str(reservation["status"]) != "active":
        return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot hold or reservation is unavailable")
    stake = money(game["bet_rub"])
    if (
        int(hold["telegram_id"]) != creator_id or str(hold["game_id"]) != game_id
        or money(hold["amount_rub"]) != stake or not hold["ledger_order_ref"]
    ):
        return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot hold violates its immutable contract")

    outcome = _json_object(game.get("outcome"))
    kind = str(outcome.get("kind") or "")
    reserve_amount = money(reservation["amount_rub"])
    commission = Decimal("0.00")
    if release:
        await release_unified_hold(
            conn, user_id=creator_id, order_ref=str(hold["ledger_order_ref"]), amount_rub=stake,
            note=f"Casino PVP robot refund: {game_id}",
        )
        account = await conn.fetchrow(
            """UPDATE casino_house_accounts SET reserved_rub = reserved_rub - $2, updated_at = now()
               WHERE id = $1 AND reserved_rub >= $2 RETURNING balance_rub, reserved_rub""",
            int(account_id), reserve_amount,
        )
        if not account:
            return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot reservation release conflicts")
        await conn.execute(
            """UPDATE casino_balance_holds SET status = 'released', released_at = now()
               WHERE hold_id = $1 AND status = 'active'""", hold_id,
        )
        await conn.execute(
            """UPDATE casino_house_reservations SET status = 'released', released_at = now()
               WHERE id = $1 AND status = 'active'""", int(reservation["id"]),
        )
        status, payout, house_delta = "cancelled", Decimal("0"), Decimal("0")
    else:
        if kind not in {"winner", "house_win"}:
            return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot outcome is invalid")
        pricing_snapshot = _json_object(_json_object(game.get("game_data")).get("pricing_snapshot"))
        if not pricing_snapshot:
            return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot game has no immutable pricing snapshot")
        settlement = calculate_house_settlement(
            stake,
            Decimal("2") if kind == "winner" else Decimal("0"),
            pricing_snapshot["commission_rate"],
            commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub"),
            commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub"),
        )
        payout = settlement.payout
        commission = settlement.commission
        house_delta = settlement.house_delta
        await confirm_unified_hold(
            conn, user_id=creator_id, order_ref=str(hold["ledger_order_ref"]), amount_rub=stake,
            note=f"Casino PVP robot stake: {game_id}",
        )
        if payout:
            await _credit_winner(conn, game_id=game_id, winner_id=creator_id, payout_rub=payout)
        account = await conn.fetchrow(
            """UPDATE casino_house_accounts
               SET balance_rub = balance_rub + $2 - $3, reserved_rub = reserved_rub - $4, updated_at = now()
               WHERE id = $1 AND reserved_rub >= $4 RETURNING balance_rub, reserved_rub""",
            int(account_id), stake, payout, reserve_amount,
        )
        if not account:
            return await _mark_game_manual_review(conn, game_id=game_id, reason="PVP robot settlement reservation conflicts")
        casino_creator_account = await _resolve_active_creator_account(conn)
        referral_l1_id, referral_l2_id = await _resolve_loser_referrals(conn, creator_id)
        allocations = allocate_commission(
            stake,
            commission_rate=pricing_snapshot["commission_rate"],
            creator_percent=pricing_snapshot["creator_cut_percent"],
            referral_l1_percent=pricing_snapshot["referral_l1_percent"],
            referral_l2_percent=pricing_snapshot["referral_l2_percent"],
            has_creator=casino_creator_account is not None,
            has_referral_l1=referral_l1_id is not None,
            has_referral_l2=referral_l2_id is not None,
            commission_cap_rub=_snapshot_amount(pricing_snapshot, "commission_cap_rub"),
            commission_min_rub=_snapshot_amount(pricing_snapshot, "commission_min_rub"),
        )
        await _record_commissions(
            conn,
            game_pk=int(game["id"]),
            game_id=game_id,
            casino_creator_account=casino_creator_account,
            referral_l1_id=referral_l1_id,
            referral_l2_id=referral_l2_id,
            allocations=allocations,
        )
        await conn.execute(
            """INSERT INTO casino_house_ledger (
                   account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
               ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)""",
            int(account_id), game_id, f"pvp-robot-settlement-{game_id}", house_delta,
            money(account["balance_rub"]), f"PVP robot {'player win' if payout else 'house win'} settlement",
        )
        await conn.execute(
            """UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
               WHERE hold_id = $1 AND status = 'active'""", hold_id,
        )
        await conn.execute(
            """UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
               WHERE id = $1 AND status = 'active'""", int(reservation["id"]),
        )
        status = "finished"

    response = {
        "success": True, "idempotent": False, "game_id": game_id,
        "counterparty_kind": "pvp_robot", "outcome": outcome,
        "stake_rub": _text_money(stake), "commission_rub": _text_money(commission), "payout_rub": _text_money(payout),
        "house_delta_rub": _text_money(house_delta), "status": status,
    }
    row = await conn.fetchrow(
        """UPDATE casino_games SET status = $2, commission_rub = $3, payout_rub = $4,
               settlement_base_rub = $5, finished_at = now(), updated_at = now(),
               game_data = game_data || jsonb_build_object('settlement_response', $6::jsonb)
           WHERE game_id = $1 AND status = 'outcome_committed'
           RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id,
                     opponent_hold_id, status, state_version, game_state, outcome, created_at,
                     started_at, outcome_committed_at, finished_at, game_chat_binding_id, game_chat_id,
               game_chat_binding_revision""",
        game_id, status, commission, payout, stake, json.dumps(response, separators=(",", ":")),
    )
    if not row:
        raise HTTPException(status_code=409, detail="PVP robot outcome settlement conflicts")
    response["game"] = _game_response(row)
    response["state_version"] = response["game"]["state_version"]
    return response


async def settle_committed_outcome_with_conn(conn, body: CasinoGameIdRequest) -> dict:
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    status = str(game["status"])
    if str(game.get("counterparty_kind") or "player") == "pvp_robot":
        if status == "finished":
            response = _json_object(_json_object(game.get("game_data")).get("settlement_response"))
            return {**response, "success": True, "idempotent": True, "game": _game_response(game)}
        if status == "cancelled":
            return {"success": True, "idempotent": True, "game": _game_response(game), "state_version": int(game["state_version"])}
        if status == "manual_review":
            return {"success": False, "manual_review": True, "game": _game_response(game)}
        if status != "outcome_committed":
            raise HTTPException(status_code=409, detail="Game has no committed outcome")
        outcome_kind = str(_json_object(game.get("outcome")).get("kind") or "")
        if outcome_kind in {"draw", "cancel", "timeout"}:
            result = await _settle_pvp_robot_outcome_with_conn(conn, game, release=True)
            await _enqueue_notification(conn, game_id=body.game_id, event_type="game_released", payload=result)
            return result
        result = await _settle_pvp_robot_outcome_with_conn(conn, game)
        await _enqueue_notification(conn, game_id=body.game_id, event_type="game_settled", payload=result)
        return result
    if status == "cancelled":
        return {"success": True, "idempotent": True, "game": _game_response(game), "state_version": int(game["state_version"])}
    if status == "manual_review":
        return {"success": False, "manual_review": True, "game": _game_response(game)}
    if status == "finished":
        settlement_body = SettlementRequest.model_validate({
            "game_id": game["game_id"], "game_type": game["game_type"], "creator_id": game["creator_id"],
            "opponent_id": game["opponent_id"], "winner_id": game["winner_id"],
            "creator_hold_id": game["creator_hold_id"], "opponent_hold_id": game["opponent_hold_id"], "stake_rub": game["bet_rub"],
        })
        return await settle_game_with_conn(conn, settlement_body)
    if status != "outcome_committed":
        raise HTTPException(status_code=409, detail="Game has no committed outcome")
    outcome = _json_object(game.get("outcome"))
    if outcome.get("kind") in {"draw", "cancel", "timeout"}:
        return await _settle_non_winner_outcome_with_conn(conn, game)
    if outcome.get("kind") != "winner" or game["opponent_id"] is None or game["winner_id"] is None:
        return await _mark_game_manual_review(conn, game_id=body.game_id, reason="committed winner outcome violates game contract")
    settlement_body = SettlementRequest.model_validate({
        "game_id": game["game_id"], "game_type": game["game_type"], "creator_id": game["creator_id"],
        "opponent_id": game["opponent_id"], "winner_id": game["winner_id"],
        "creator_hold_id": game["creator_hold_id"], "opponent_hold_id": game["opponent_hold_id"], "stake_rub": game["bet_rub"],
    })
    result = await settle_game_with_conn(conn, settlement_body)
    await _enqueue_notification(conn, game_id=body.game_id, event_type="game_settled", payload=result)
    return result


async def release_game_with_conn(conn, body: CasinoGameReleaseRequest) -> dict:
    """Refund a committed non-winner outcome; never infer an outcome for a live game."""
    await lock_casino_game(conn, body.game_id)
    game = await _game_for_update(conn, body.game_id)
    status = str(game["status"])
    if status == "cancelled":
        return {"success": True, "idempotent": True, "game": _game_response(game), "state_version": int(game["state_version"])}
    if status == "manual_review":
        return {"success": False, "manual_review": True, "game": _game_response(game)}
    if str(game.get("counterparty_kind") or "player") == "pvp_robot":
        if status in {"waiting", "active"}:
            return await _mark_game_manual_review(
                conn,
                game_id=body.game_id,
                reason="release requires a committed draw, cancel, or timeout outcome",
            )
        if status != "outcome_committed":
            raise HTTPException(status_code=409, detail="Finished game cannot be released")
        if _json_object(game.get("outcome")).get("kind") not in {"draw", "cancel", "timeout"}:
            raise HTTPException(status_code=409, detail="Winner outcome must be settled")
        return await _settle_pvp_robot_outcome_with_conn(conn, game, release=True)
    if status in {"waiting", "active"}:
        return await _mark_game_manual_review(
            conn,
            game_id=body.game_id,
            reason="release requires a committed draw, cancel, or timeout outcome",
        )
    if status != "outcome_committed":
        raise HTTPException(status_code=409, detail="Finished game cannot be released")
    if _json_object(game.get("outcome")).get("kind") not in {"draw", "cancel", "timeout"}:
        raise HTTPException(status_code=409, detail="Winner outcome must be settled")
    return await _settle_non_winner_outcome_with_conn(conn, game, reason=body.reason)


async def claim_recovery_with_conn(conn, body: ClaimRequest) -> dict:
    claim_token = f"{body.worker_id}:{uuid4().hex}"
    rows = await conn.fetch(
        """
        WITH candidates AS (
            SELECT game_id
            FROM casino_games
            WHERE status = 'outcome_committed'
              AND recovery_completed_at IS NULL
              AND (recovery_claimed_at IS NULL OR recovery_claimed_at < now() - make_interval(secs => $3))
            ORDER BY updated_at, game_id
            FOR UPDATE SKIP LOCKED
            LIMIT $2
        )
        UPDATE casino_games game
        SET recovery_claim_token = $1, recovery_claimed_at = now()
        FROM candidates
        WHERE game.game_id = candidates.game_id
        RETURNING game.game_id, game.status, game.state_version, game.game_state, game.outcome,
                  game.creator_id, game.opponent_id, game.bet_rub, game.creator_hold_id, game.opponent_hold_id,
                  game.recovery_claimed_at
        """,
        claim_token, body.limit, body.lease_seconds,
    )
    return {
        "success": True,
        "items": [
            {
                "game_id": str(row["game_id"]), "status": str(row["status"]),
                "state_version": int(row["state_version"]), "game_state": _json_object(row["game_state"]),
                "outcome": _json_object(row["outcome"]) or None,
                "creator_id": int(row["creator_id"]),
                "opponent_id": int(row["opponent_id"]) if row["opponent_id"] is not None else None,
                "stake_rub": _text_money(row["bet_rub"]), "creator_hold_id": row["creator_hold_id"],
                "opponent_hold_id": row["opponent_hold_id"], "claim_token": claim_token,
                "claimed_at": _utc(row["recovery_claimed_at"]).isoformat(),
            }
            for row in rows
        ],
    }


async def complete_recovery_with_conn(conn, body: RecoveryCompleteRequest) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE casino_games SET recovery_completed_at = now(), recovery_claim_token = NULL, updated_at = now()
        WHERE game_id = $1 AND recovery_claim_token = $2
          AND recovery_claimed_at >= now() - interval '1 hour'
        RETURNING game_id, recovery_completed_at
        """, body.game_id, body.claim_token,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Recovery claim is not owned or has expired")
    return {"success": True, "game_id": str(row["game_id"]), "completed_at": _utc(row["recovery_completed_at"]).isoformat()}


async def recovery_snapshot_with_conn(conn) -> dict:
    rows = await conn.fetch(
        """
        SELECT status, COUNT(*)::integer AS count
        FROM casino_games
        WHERE status IN ('waiting', 'active', 'outcome_committed')
          AND recovery_completed_at IS NULL
        GROUP BY status
        """
    )
    pending = {str(row["status"]): int(row["count"]) for row in rows}
    return {"success": True, "pending": pending, "total": sum(pending.values())}


async def claim_outbox_with_conn(conn, body: ClaimRequest) -> dict:
    claim_token = f"{body.worker_id}:{uuid4().hex}"
    rows = await conn.fetch(
        """
        WITH candidates AS (
            SELECT id
            FROM casino_notification_outbox
            WHERE (status = 'pending' AND available_at <= now())
               OR (status = 'processing' AND claimed_at < now() - make_interval(secs => $3))
            ORDER BY available_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT $2
        )
        UPDATE casino_notification_outbox outbox
        SET status = 'processing', claim_token = $1, claimed_at = now(), attempts = attempts + 1, updated_at = now()
        FROM candidates
        WHERE outbox.id = candidates.id
        RETURNING outbox.id, outbox.event_type, outbox.game_id, outbox.recipient_id, outbox.payload,
                  outbox.attempts, outbox.claimed_at
        """, claim_token, body.limit, body.lease_seconds,
    )
    return {
        "success": True,
        "items": [
            {
                "outbox_id": int(row["id"]), "event_type": str(row["event_type"]),
                "game_id": str(row["game_id"]), "recipient_id": int(row["recipient_id"]),
                "payload": _json_object(row["payload"]),
                "attempts": int(row["attempts"]), "claim_token": claim_token,
                "claimed_at": _utc(row["claimed_at"]).isoformat(),
            }
            for row in rows
        ],
    }


async def complete_outbox_with_conn(conn, body: OutboxCompleteRequest) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE casino_notification_outbox
        SET status = 'completed', completed_at = now(), claim_token = NULL, updated_at = now()
        WHERE id = $1 AND status = 'processing' AND claim_token = $2
          AND claimed_at >= now() - interval '1 hour'
        RETURNING id, completed_at
        """, body.outbox_id, body.claim_token,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Outbox claim is not owned or has expired")
    return {"success": True, "outbox_id": int(row["id"]), "completed_at": _utc(row["completed_at"]).isoformat()}


def _game_chat_binding_response(row: Mapping[str, object]) -> dict:
    binding = _row_dict(row)
    return {
        "id": int(binding["id"]),
        "chat_id": int(binding["chat_id"]),
        "chat_type": str(binding["chat_type"]),
        "chat_title": binding.get("chat_title"),
        "telegram_url": binding.get("telegram_url"),
        "status": str(binding["status"]),
        "requested_by_telegram_id": int(binding["requested_by_telegram_id"]),
        "created_at": _utc(binding["created_at"]).isoformat(),
        "updated_at": _utc(binding["updated_at"]).isoformat(),
    }


async def create_pending_game_chat_binding_with_conn(
    conn, body: GameChatBindingPendingRequest
) -> dict:
    """Idempotently record a group binding request without activating it."""
    row = await conn.fetchrow(
        """
        INSERT INTO casino_game_chat_bindings (
            chat_id, chat_type, chat_title, telegram_url, status, requested_by_telegram_id
        )
        VALUES ($1, $2, $3, $4, 'pending', $5)
        ON CONFLICT (chat_id) DO UPDATE
        SET chat_type = EXCLUDED.chat_type,
            chat_title = EXCLUDED.chat_title,
            telegram_url = CASE
                WHEN casino_game_chat_bindings.status = 'active'
                    THEN casino_game_chat_bindings.telegram_url
                ELSE EXCLUDED.telegram_url
            END,
            status = CASE
                WHEN casino_game_chat_bindings.status = 'active' THEN 'active'
                ELSE 'pending'
            END,
            requested_by_telegram_id = CASE
                WHEN casino_game_chat_bindings.status = 'active'
                    THEN casino_game_chat_bindings.requested_by_telegram_id
                ELSE EXCLUDED.requested_by_telegram_id
            END,
            updated_at = now()
        RETURNING id, chat_id, chat_type, chat_title, telegram_url, status,
                  requested_by_telegram_id, created_at, updated_at
        """,
        body.chat_id,
        body.chat_type,
        body.chat_title,
        body.telegram_url,
        body.requested_by_telegram_id,
    )
    return {"success": True, "binding": _game_chat_binding_response(row)}


async def active_game_chat_binding_with_conn(conn) -> dict:
    row = await conn.fetchrow(
        """
        SELECT id, chat_id, chat_type, chat_title, telegram_url, status,
               requested_by_telegram_id, created_at, updated_at
        FROM casino_game_chat_bindings
        WHERE status = 'active'
        ORDER BY confirmed_at DESC NULLS LAST, id DESC
        LIMIT 1
        """
    )
    return {"success": True, "binding": _game_chat_binding_response(row) if row else None}


async def fail_outbox_with_conn(conn, body: OutboxFailRequest) -> dict:
    row = await conn.fetchrow(
        """
        UPDATE casino_notification_outbox
        SET status = CASE
                WHEN created_at <= now() - interval '72 hours' THEN 'dead'
                WHEN $4 <> 'rate_limited' AND attempts >= 10 THEN 'dead'
                ELSE 'pending'
            END,
            attempts = CASE WHEN $4 = 'rate_limited' THEN GREATEST(attempts - 1, 0) ELSE attempts END,
            available_at = now() + make_interval(secs => CASE
                WHEN $4 = 'rate_limited' THEN GREATEST(COALESCE($5, 1), 1)
                ELSE LEAST(3600, 5 * (2 ^ LEAST(attempts, 9))::integer)
            END),
            claim_token = NULL, last_error = $3, last_error_kind = $4, updated_at = now()
        WHERE id = $1 AND status = 'processing' AND claim_token = $2
        RETURNING id, status, attempts, available_at
        """, body.outbox_id, body.claim_token, body.error, body.error_kind, body.retry_after_seconds,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Outbox claim is not owned or has expired")
    return {
        "success": True, "outbox_id": int(row["id"]), "status": str(row["status"]),
        "attempts": int(row["attempts"]), "available_at": _utc(row["available_at"]).isoformat(),
    }


def _v2_idempotency_fingerprint(operation: str, body: BaseModel) -> str:
    payload = json.dumps({"operation": operation, "request": body.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


async def _replay_v2_idempotency_with_conn(conn, table: Mapping[str, object], operation: str, body: BaseModel) -> dict | None:
    """Return a durable replay response or fail closed when a key is reused differently."""
    fingerprint = _v2_idempotency_fingerprint(operation, body)
    row = await conn.fetchrow(
        "SELECT request_fingerprint,response FROM casino_v2_lifecycle_idempotency WHERE table_key=$1 AND operation=$2 AND idempotency_key=$3 FOR UPDATE",
        str(table["table_id"]), operation, str(body.idempotency_key),
    )
    # Test doubles may return the table for every SELECT; production rows always
    # contain request_fingerprint and response.
    if not row or "request_fingerprint" not in row:
        return None
    if str(row["request_fingerprint"]) != fingerprint:
        raise HTTPException(status_code=409, detail="V2 idempotency key was reused with a different request")
    response = _json_object(row["response"])
    response["idempotent"] = True
    return response


async def _record_v2_idempotency_with_conn(conn, table: Mapping[str, object], operation: str, body: BaseModel, response: dict) -> dict:
    response = {**response, "idempotent": False}
    await conn.execute(
        """INSERT INTO casino_v2_lifecycle_idempotency(table_id,table_key,operation,idempotency_key,request_fingerprint,response)
           VALUES($1,$2,$3,$4,$5,$6::jsonb)""",
        int(table["id"]), str(table["table_id"]), operation, str(body.idempotency_key), _v2_idempotency_fingerprint(operation, body),
        json.dumps(response, separators=(",", ":"), default=str),
    )
    return response


class V2TableCreateRequest(StrictModel):
    table_id: str = Field(min_length=1, max_length=64)
    game_type: Literal[
        "pvp_emoji", "pvp_dice", "blackjack", "baccara",
    ]
    creator_id: ClientUserId
    stake_rub: MoneyInput
    # max_seats is retained as a wire-compatible alias for early staging clients.
    max_players: int | None = Field(default=None, ge=2, le=6)
    max_seats: int | None = Field(default=None, ge=2, le=6)
    bot_count: int = Field(default=0, ge=0, le=5)
    expected_state_version: int = Field(default=0, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    draw_policy: Literal["tie_break", "tie_split"] = "tie_break"
    rounds: int = Field(default=1, ge=1, le=2)
    game_chat_id: int | None = None

    @field_validator("table_id", "idempotency_key")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def normalize_player_limit(self):
        limit = self.max_players if self.max_players is not None else self.max_seats
        if limit is None:
            raise ValueError("max_players is required")
        if self.max_players is not None and self.max_seats is not None and self.max_players != self.max_seats:
            raise ValueError("max_players and max_seats must match")
        self.max_players = limit
        self.max_seats = limit
        if self.bot_count >= limit:
            raise ValueError("bot_count must leave at least one player seat")
        if self.expected_state_version != 0:
            raise ValueError("new V2 table must use expected_state_version=0")
        if isinstance(self.game_chat_id, bool) or (self.game_chat_id is not None and self.game_chat_id == 0):
            raise ValueError("game_chat_id must be a Telegram chat id")
        return self


class V2LifecycleRequest(StrictModel):
    expected_state_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def strip_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be blank")
        return value


class V2TableJoinRequest(V2LifecycleRequest):
    telegram_id: ClientUserId


class V2TableAddBotRequest(V2LifecycleRequest):
    telegram_id: ClientUserId


class V2TableStartRequest(V2LifecycleRequest):
    creator_id: ClientUserId


class V2TableLeaveRequest(V2LifecycleRequest):
    telegram_id: ClientUserId


class V2TablePersistStateRequest(V2LifecycleRequest):
    game_state: dict[str, JsonValue]


class V2TableCommitOutcomeRequest(V2LifecycleRequest):
    outcome_kind: Literal["winner", "tie_split", "tie_break"]
    winner_seat_nos: list[int] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_winners(self):
        if any(seat_no < 1 or seat_no > 6 for seat_no in self.winner_seat_nos):
            raise ValueError("winner_seat_nos must be between 1 and 6")
        if len(self.winner_seat_nos) != len(set(self.winner_seat_nos)):
            raise ValueError("winner_seat_nos must be unique")
        if self.outcome_kind == "winner" and len(self.winner_seat_nos) != 1:
            raise ValueError("winner requires exactly one seat")
        if self.outcome_kind == "tie_split" and len(self.winner_seat_nos) < 2:
            raise ValueError("tie_split requires at least two seats")
        if self.outcome_kind == "tie_break" and len(self.winner_seat_nos) < 2:
            raise ValueError("tie_break requires at least two leaders")
        return self


class V2TableSettleRequest(V2TableCommitOutcomeRequest):
    """Compatibility endpoint; callers still provide strict lifecycle fencing."""


class V2TableSettleCommittedRequest(V2LifecycleRequest):
    pass


class V2TableReleaseRequest(V2LifecycleRequest):
    creator_id: ClientUserId
    reason: str = Field(min_length=1, max_length=256)


class V2TableIdRequest(StrictModel):
    table_id: str = Field(min_length=1, max_length=64)


class V2RecoveryCompleteRequest(StrictModel):
    table_id: str = Field(min_length=1, max_length=64)
    claim_token: str = Field(min_length=1, max_length=128)


class V2OutboxCompleteRequest(StrictModel):
    outbox_id: int = Field(gt=0)
    claim_token: str = Field(min_length=1, max_length=128)


class V2OutboxFailRequest(V2OutboxCompleteRequest):
    error: str = Field(min_length=1, max_length=1000)
    error_kind: Literal["dm_unavailable", "rate_limited", "temporary"] = "temporary"
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86400)


def _v2_table_response(row: Mapping[str, object], *, roster: list[dict[str, object]] | None = None) -> dict[str, object]:
    item = _row_dict(row)
    response = {
        "table_id": str(item["table_id"]), "game_type": str(item["game_type"]),
        "creator_id": int(item["creator_id"]), "stake_rub": _text_money(item["stake_rub"]),
        "max_players": int(item["max_seats"]), "max_seats": int(item["max_seats"]), "status": str(item["status"]),
        "state_version": int(item.get("state_version") or 0),
        "started_at": _utc(item["started_at"]).isoformat() if item.get("started_at") else None,
        "game_state": _json_object(item.get("game_state")),
        "game_chat_id": int(item["game_chat_id"]) if item.get("game_chat_id") is not None else None,
    }
    if roster is not None:
        occupied_seat_nos = {int(seat["seat_no"]) for seat in roster}
        response["roster"] = roster
        response["bot_count"] = sum(seat["participant_kind"] == "bot" for seat in roster)
        response["free_seats"] = [
            seat_no for seat_no in range(1, int(item["max_seats"]) + 1)
            if seat_no not in occupied_seat_nos
        ]
    return response


async def _v2_table_response_with_conn(conn, row: Mapping[str, object]) -> dict[str, object]:
    """Return a public recovery-safe roster; never expose holds or house-account data."""
    seats = await conn.fetch(
        """SELECT seat.seat_no, seat.participant_kind, seat.telegram_id,
                  profile.profile_key, profile.display_name
           FROM casino_v2_table_seats seat
           LEFT JOIN casino_robot_profiles profile ON profile.id = seat.robot_profile_id
           WHERE seat.table_id=$1 AND seat.status IN ('seated', 'settled')
           ORDER BY seat.seat_no""",
        int(row["id"]),
    )
    roster: list[dict[str, object]] = []
    for raw_seat in seats:
        seat = _row_dict(raw_seat)
        participant_kind = str(seat["participant_kind"])
        entry: dict[str, object] = {
            "seat_no": int(seat["seat_no"]),
            "participant_kind": participant_kind,
        }
        if participant_kind == "player":
            entry["telegram_id"] = int(seat["telegram_id"])
        else:
            entry["bot"] = {
                "profile_key": str(seat.get("profile_key") or "bot"),
                "display_name": str(seat.get("display_name") or "Bot"),
            }
        roster.append(entry)
    return _v2_table_response(row, roster=roster)


async def _seat_v2_bots_with_conn(conn, table: Mapping[str, object], bot_count: int) -> None:
    """Seat pvp_robot bots. One profile may occupy several seats at the same table."""
    if not bot_count:
        return
    stake = money(table["stake_rub"])
    max_seats = int(table.get("max_seats") or table.get("max_players") or 0)
    profiles = await conn.fetch(
        """SELECT rp.id, rp.account_id, rp.max_concurrent_games, rp.max_exposure_rub,
                  ha.balance_rub, ha.reserved_rub
           FROM casino_robot_profiles rp JOIN casino_house_accounts ha ON ha.id = rp.account_id
           WHERE rp.mode = 'pvp_robot' AND rp.is_active AND ha.is_active
             AND rp.allowed_games ? $1 AND rp.min_bet_rub <= $2 AND rp.max_bet_rub >= $2
           ORDER BY rp.id LIMIT 1 FOR UPDATE OF rp, ha""",
        str(table["game_type"]), stake,
    )
    if not profiles:
        raise HTTPException(status_code=409, detail="V2 bot capacity is unavailable")
    profile = profiles[0]
    profile_id = int(profile["id"])
    active_by_profile = {
        int(row["robot_profile_id"]): row
        for row in await conn.fetch(
            """SELECT seat.robot_profile_id,
                      COUNT(DISTINCT table_row.id) FILTER (WHERE table_row.id <> $2) AS concurrent_games,
                      COALESCE(SUM(table_row.stake_rub), 0) AS exposure_rub
               FROM casino_v2_table_seats seat
               JOIN casino_v2_tables table_row ON table_row.id = seat.table_id
               WHERE seat.robot_profile_id = $1 AND seat.status = 'seated'
                 AND table_row.status IN ('draft','open','ready','running','tie_break_running','outcome_committed','settling')
               GROUP BY seat.robot_profile_id""",
            profile_id, int(table["id"]),
        )
    }
    usage = active_by_profile.get(profile_id, {})
    if int(usage.get("concurrent_games") or 0) >= int(profile["max_concurrent_games"]):
        raise HTTPException(status_code=409, detail="V2 robot concurrency limit reached")
    exposure_limit = money(profile["max_exposure_rub"])
    extra_exposure = money(stake * bot_count)
    if exposure_limit > 0 and money(usage.get("exposure_rub") or 0) + extra_exposure > exposure_limit:
        raise HTTPException(status_code=409, detail="V2 robot exposure limit reached")
    occupied = {
        int(row["seat_no"])
        for row in await conn.fetch(
            "SELECT seat_no FROM casino_v2_table_seats WHERE table_id=$1 AND status IN ('seated','settled')",
            int(table["id"]),
        )
    }
    targets = [seat_no for seat_no in range(1, max_seats + 1) if seat_no not in occupied][:bot_count]
    if len(targets) < bot_count:
        raise HTTPException(status_code=409, detail="V2 table is full")
    account_id = int(profile["account_id"])
    reserve = extra_exposure
    # Фишковый стол не создаёт рублёвой экспозиции, поэтому и банкролл не резервируется.
    if scope_from_row(table).is_rub:
        reservation = await conn.fetchrow(
            """UPDATE casino_house_accounts SET reserved_rub=reserved_rub+$2, updated_at=now()
               WHERE id=$1 AND balance_rub-reserved_rub >= $2 RETURNING id""", account_id, reserve,
        )
        if not reservation:
            raise HTTPException(status_code=409, detail="V2 house bankroll is insufficient")
        existing_res = await conn.fetchrow(
            """SELECT id FROM casino_v2_house_reservations
               WHERE table_id=$1 AND status='active' FOR UPDATE""",
            int(table["id"]),
        )
        if existing_res:
            await conn.execute(
                "UPDATE casino_v2_house_reservations SET amount_rub=amount_rub+$2 WHERE id=$1",
                int(existing_res["id"]), reserve,
            )
        else:
            await conn.execute(
                """INSERT INTO casino_v2_house_reservations(reservation_key,table_id,account_id,amount_rub)
                   VALUES($1,$2,$3,$4)""",
                f"v2-reserve-{table['table_id']}", int(table["id"]), account_id, reserve,
            )
    for seat_no in targets:
        await conn.execute(
            """INSERT INTO casino_v2_table_seats(table_id,seat_no,participant_kind,robot_profile_id)
               VALUES($1,$2,'bot',$3)""",
            int(table["id"]), seat_no, profile_id,
        )


async def add_v2_bot_with_conn(conn, table_id: str, body: V2TableAddBotRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id = $1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "add_bot", body)
    if replay:
        return replay
    if str(table["status"]) != "open":
        raise HTTPException(status_code=409, detail="V2 table is not open")
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    seats = await conn.fetch(
        "SELECT * FROM casino_v2_table_seats WHERE table_id=$1 ORDER BY seat_no FOR UPDATE",
        int(table["id"]),
    )
    active = [seat for seat in seats if str(seat["status"]) == "seated"]
    if sum(1 for seat in active if str(seat["participant_kind"]) == "bot") >= MAX_BOTS_PER_TABLE:
        raise HTTPException(
            status_code=409,
            detail=f"За столом может быть не больше {MAX_BOTS_PER_TABLE} бота",
        )
    if not any(
        str(seat["participant_kind"]) == "player" and int(seat["telegram_id"] or 0) == int(body.telegram_id)
        for seat in active
    ):
        raise HTTPException(status_code=409, detail="Player is not seated at this V2 table")
    if len(active) >= int(table["max_seats"]):
        raise HTTPException(status_code=409, detail="V2 table is full")
    await _seat_v2_bots_with_conn(conn, table, 1)
    state = _json_object(table.get("game_state"))
    state["bot_count"] = int(state.get("bot_count") or 0) + 1
    is_full = len(active) + 1 >= int(table["max_seats"])
    countdown_json = _v2_countdown_state(state)[1] if is_full else json.dumps(state, separators=(",", ":"))
    row = await conn.fetchrow(
        """UPDATE casino_v2_tables
           SET status=CASE WHEN $3 THEN 'ready' ELSE 'open' END,
               state_version=state_version+1,
               game_state=$4::jsonb,
               updated_at=now()
           WHERE id=$1 AND state_version=$2 AND status='open'
           RETURNING *""",
        int(table["id"]), body.expected_state_version, is_full, countdown_json if is_full else json.dumps(state, separators=(",", ":")),
    )
    if not row:
        raise HTTPException(status_code=409, detail="V2 table join conflicts")
    return await _record_v2_idempotency_with_conn(
        conn,
        row,
        "add_bot",
        body,
        {
            "success": True,
            "auto_started": is_full,
            "table": await _v2_table_response_with_conn(conn, row),
        },
    )


async def create_v2_table_with_conn(conn, body: V2TableCreateRequest) -> dict:
    await lock_casino_game(conn, f"v2:{body.table_id}")
    await lock_casino_users(conn, (body.creator_id,))
    stake = money(body.stake_rub)
    existing = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id = $1 FOR UPDATE", body.table_id)
    if existing:
        replay = await _replay_v2_idempotency_with_conn(conn, existing, "create", body)
        if replay:
            return replay
        state = _json_object(existing.get("game_state"))
        if (str(existing["game_type"]) != body.game_type or int(existing["creator_id"]) != body.creator_id
                or money(existing["stake_rub"]) != stake or int(existing["max_seats"]) != body.max_players
                or int(state.get("bot_count") or 0) != body.bot_count
                or str(state.get("draw_policy") or "tie_break") != body.draw_policy
                or int(state.get("rounds") or 1) != body.rounds):
            raise HTTPException(status_code=409, detail="Existing v2 table conflicts")
        return {"success": True, "idempotent": True, "table": await _v2_table_response_with_conn(conn, existing)}
    from casino_live_sessions import assert_can_sit

    if int(body.bot_count) > MAX_BOTS_PER_TABLE:
        raise HTTPException(
            status_code=400,
            detail=f"За столом может быть не больше {MAX_BOTS_PER_TABLE} бота",
        )
    await assert_can_sit(conn, body.creator_id)
    settings_snapshot = await load_casino_settings(conn)
    canonical_game_type = "pvp_dice" if body.game_type == "pvp_emoji" else body.game_type
    if canonical_game_type in RETIRED_SPORT_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Эта игра больше не доступна")
    if not settings_snapshot.enabled_games.get(canonical_game_type, False):
        raise HTTPException(status_code=409, detail="Game type is disabled")
    _assert_stake_within_limits(settings_snapshot, canonical_game_type, stake)
    order_ref = casino_ledger_order_ref(f"v2-{body.table_id}-seat-1")
    # Стол наследует кошелёк создателя: фишки и рубли не встретятся за одним столом.
    scope = await active_scope(conn, body.creator_id)
    scope_cols, scope_params, scope_values = await scope_insert_sql(
        conn, "casino_v2_tables", scope, next_index=9
    )
    try:
        await reserve_unified_funds(conn, user_id=body.creator_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Insufficient balance") from exc
    table = await conn.fetchrow(
        f"""INSERT INTO casino_v2_tables (table_id, game_type, creator_id, stake_rub, max_seats, status, game_state, game_chat_id{scope_cols})
           VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8{scope_params}) RETURNING *""",
        body.table_id, body.game_type, body.creator_id, stake, body.max_players,
        "open", json.dumps(
            {"bot_count": body.bot_count, "draw_policy": body.draw_policy, "rounds": body.rounds},
            separators=(",", ":"),
        ),
        body.game_chat_id,
        *scope_values,
    )
    await conn.execute("""INSERT INTO casino_v2_table_seats(table_id,seat_no,participant_kind,telegram_id,hold_order_ref)
        VALUES ($1,1,'player',$2,$3)""", int(table["id"]), body.creator_id, order_ref)
    await _seat_v2_bots_with_conn(conn, table, body.bot_count)
    auto_started = 1 + body.bot_count >= int(body.max_players)
    if auto_started:
        _, state_json = _v2_countdown_state(table.get("game_state"))
        started = await conn.fetchrow(
            """UPDATE casino_v2_tables
               SET status='ready', state_version=state_version+1, game_state=$2::jsonb, updated_at=now()
               WHERE id=$1 AND status='open'
               RETURNING *""",
            int(table["id"]),
            state_json,
        )
        if not started:
            raise HTTPException(status_code=409, detail="V2 table start conflicts")
        table = started
    return await _record_v2_idempotency_with_conn(
        conn,
        table,
        "create",
        body,
        {
            "success": True,
            "auto_started": auto_started,
            "table": await _v2_table_response_with_conn(conn, table),
        },
    )


async def join_v2_table_with_conn(conn, table_id: str, body: V2TableJoinRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id = $1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "join", body)
    if replay:
        return replay
    if str(table["status"]) != "open":
        raise HTTPException(status_code=409, detail="V2 table is not open")
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    await lock_casino_users(conn, (body.telegram_id,))
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id = $1 ORDER BY seat_no FOR UPDATE", int(table["id"]))
    active_seats = [seat for seat in seats if str(seat["status"]) == "seated"]
    for seat in active_seats:
        if seat["telegram_id"] == body.telegram_id:
            return {"success": True, "idempotent": True, "table": await _v2_table_response_with_conn(conn, table), "seat_no": int(seat["seat_no"])}
    if len(active_seats) >= int(table["max_seats"]):
        raise HTTPException(status_code=409, detail="V2 table is full")
    from casino_live_sessions import assert_can_sit

    await assert_player_may_sit(conn, table, body.telegram_id)
    await assert_can_sit(conn, body.telegram_id)
    used_seat_nos = {int(seat["seat_no"]) for seat in seats}
    seat_no = next((number for number in range(1, int(table["max_seats"]) + 1) if number not in used_seat_nos), None)
    if seat_no is None:
        raise HTTPException(status_code=409, detail="V2 table has no reusable seat")
    stake = money(table["stake_rub"])
    settings_snapshot = await load_casino_settings(conn)
    canonical_game_type = "pvp_dice" if str(table["game_type"]) == "pvp_emoji" else str(table["game_type"])
    _assert_stake_within_limits(settings_snapshot, canonical_game_type, stake)
    order_ref = casino_ledger_order_ref(f"v2-{table_id}-seat-{seat_no}")
    try:
        await reserve_unified_funds(conn, user_id=body.telegram_id, order_ref=order_ref, amount_rub=stake)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Insufficient balance") from exc
    await conn.execute(
        """INSERT INTO casino_v2_table_seats (table_id,seat_no,participant_kind,telegram_id,hold_order_ref)
           VALUES ($1,$2,'player',$3,$4)""", int(table["id"]), seat_no, body.telegram_id, order_ref,
    )
    is_full = len(active_seats) + 1 == int(table["max_seats"])
    countdown_json = _v2_countdown_state(table.get("game_state"))[1] if is_full else None
    row = await conn.fetchrow(
        """UPDATE casino_v2_tables
           SET status=CASE WHEN $3 THEN 'ready' ELSE 'open' END,
               state_version=state_version+1,
               game_state=CASE WHEN $3 THEN $4::jsonb ELSE game_state END,
               updated_at=now()
           WHERE id=$1 AND state_version=$2 AND status='open'
           RETURNING *""",
        int(table["id"]), body.expected_state_version, is_full, countdown_json or "{}",
    )
    if not row:
        raise HTTPException(status_code=409, detail="V2 table join conflicts")
    from casino_inbox import notify_player_joined

    other_ids = [
        int(seat["telegram_id"])
        for seat in active_seats
        if seat.get("telegram_id") is not None and str(seat.get("participant_kind") or "player") == "player"
    ]
    creator = int(table["creator_id"])
    if creator not in other_ids and creator != int(body.telegram_id):
        other_ids.append(creator)
    await notify_player_joined(
        conn,
        joiner_id=int(body.telegram_id),
        other_ids=other_ids,
        kind="v2",
        game_id=str(table_id),
        game_type=str(table.get("game_type") or "pvp_dice"),
        stake_rub=stake,
    )
    return await _record_v2_idempotency_with_conn(conn, row, "join", body, {"success": True, "auto_started": is_full, "table": await _v2_table_response_with_conn(conn, row), "seat_no": seat_no})


async def start_v2_table_with_conn(conn, table_id: str, body: V2TableStartRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id = $1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "start", body)
    if replay:
        return replay
    if int(table["creator_id"]) != body.creator_id:
        raise HTTPException(status_code=403, detail="Only the table creator may start it")
    if str(table["status"]) == "running":
        return {"success": True, "idempotent": True, "table": await _v2_table_response_with_conn(conn, table)}
    if str(table["status"]) not in {"open", "ready"}:
        raise HTTPException(status_code=409, detail="V2 table cannot start")
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 ORDER BY seat_no FOR UPDATE", int(table["id"]))
    if len(seats) < 2:
        raise HTTPException(status_code=409, detail="V2 table requires at least two seated participants")
    state = _json_object(table.get("game_state"))
    if state.get("starts_at"):
        return {"success": True, "idempotent": True, "table": await _v2_table_response_with_conn(conn, table)}
    _, state_json = _v2_countdown_state(state)
    row = await conn.fetchrow(
        """UPDATE casino_v2_tables SET status='ready',state_version=state_version+1,game_state=$3::jsonb,updated_at=now()
        WHERE id=$1 AND state_version=$2 AND status IN ('open','ready') RETURNING *""",
        int(table["id"]),
        body.expected_state_version,
        state_json,
    )
    if not row:
        raise HTTPException(status_code=409, detail="V2 table start conflicts")
    return await _record_v2_idempotency_with_conn(conn, row, "start", body, {"success": True, "table": await _v2_table_response_with_conn(conn, row)})


async def leave_v2_table_with_conn(conn, table_id: str, body: V2TableLeaveRequest, *, cancel: bool = False) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    operation = "cancel" if cancel else "leave"
    replay = await _replay_v2_idempotency_with_conn(conn, table, operation, body)
    if replay:
        return replay
    if str(table["status"]) not in {"open", "ready"}:
        raise HTTPException(status_code=409, detail="Only an unstarted V2 table may be left or cancelled")
    if _json_object(table.get("game_state")).get("starts_at"):
        raise HTTPException(status_code=409, detail="Стол уже стартует")
    if cancel and int(table["creator_id"]) != body.telegram_id:
        raise HTTPException(status_code=403, detail="Only the table creator may cancel it")
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 ORDER BY seat_no FOR UPDATE", int(table["id"]))
    seat = next((row for row in seats if row["participant_kind"] == "player" and int(row["telegram_id"]) == body.telegram_id), None)
    if not seat:
        raise HTTPException(status_code=409, detail="Player is not seated at this V2 table")
    await lock_casino_users(conn, (body.telegram_id,))
    await release_unified_hold(conn, user_id=body.telegram_id, order_ref=str(seat["hold_order_ref"]), amount_rub=money(table["stake_rub"]), note=f"Casino v2 table release: {table_id}")
    await conn.execute("UPDATE casino_v2_table_seats SET status='released' WHERE id=$1", int(seat["id"]))
    if cancel or int(table["creator_id"]) == body.telegram_id:
        for other in seats:
            if other["participant_kind"] == "player" and int(other["telegram_id"]) != body.telegram_id and str(other["status"]) == "seated":
                await lock_casino_users(conn, (int(other["telegram_id"]),))
                await release_unified_hold(conn, user_id=int(other["telegram_id"]), order_ref=str(other["hold_order_ref"]), amount_rub=money(table["stake_rub"]), note=f"Casino v2 table cancelled: {table_id}")
                await conn.execute("UPDATE casino_v2_table_seats SET status='released' WHERE id=$1", int(other["id"]))
        reservation = await conn.fetchrow("SELECT * FROM casino_v2_house_reservations WHERE table_id=$1 AND status='active' FOR UPDATE", int(table["id"]))
        if reservation:
            account = await conn.fetchrow("UPDATE casino_house_accounts SET reserved_rub=reserved_rub-$2,updated_at=now() WHERE id=$1 AND reserved_rub >= $2 RETURNING id", int(reservation["account_id"]), money(reservation["amount_rub"]))
            if not account:
                raise HTTPException(status_code=409, detail="V2 house reservation conflicts")
            await conn.execute("UPDATE casino_v2_house_reservations SET status='released',released_at=now() WHERE id=$1", int(reservation["id"]))
        row = await conn.fetchrow("UPDATE casino_v2_tables SET status='cancelled',state_version=state_version+1,settled_at=now(),updated_at=now() WHERE id=$1 AND state_version=$2 RETURNING *", int(table["id"]), body.expected_state_version)
        await _enqueue_v2_cancelled_outbox(conn, row or table, seats)
        return await _record_v2_idempotency_with_conn(conn, row, operation, body, {"success": True, "cancelled": True, "table": await _v2_table_response_with_conn(conn, row)})
    await conn.execute("DELETE FROM casino_v2_table_seats WHERE id=$1", int(seat["id"]))
    row = await conn.fetchrow("UPDATE casino_v2_tables SET status='open',state_version=state_version+1,updated_at=now() WHERE id=$1 AND state_version=$2 RETURNING *", int(table["id"]), body.expected_state_version)
    if not row:
        raise HTTPException(status_code=409, detail="V2 table leave conflicts")
    await _enqueue_v2_cancelled_outbox(conn, row, [seat])
    return await _record_v2_idempotency_with_conn(conn, row, operation, body, {"success": True, "left": True, "table": await _v2_table_response_with_conn(conn, row)})


async def persist_v2_table_state_with_conn(conn, table_id: str, body: V2TablePersistStateRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "persist_state", body)
    if replay:
        return replay
    row = await conn.fetchrow("""UPDATE casino_v2_tables SET game_state=game_state || $3::jsonb,state_version=state_version+1,updated_at=now()
        WHERE table_id=$1 AND state_version=$2 AND status IN ('open','ready','running','tie_break_running') RETURNING *""", table_id, body.expected_state_version, json.dumps(body.game_state, separators=(',', ':')))
    if not row:
        raise HTTPException(status_code=409, detail="V2 table state is not mutable or its version conflicts")
    return await _record_v2_idempotency_with_conn(conn, row, "persist_state", body, {"success": True, "table": await _v2_table_response_with_conn(conn, row)})


async def commit_v2_table_outcome_with_conn(conn, table_id: str, body: V2TableCommitOutcomeRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "commit_outcome", body)
    if replay:
        return replay
    outcome = {"kind": body.outcome_kind, "winner_seat_nos": sorted(body.winner_seat_nos)}
    if str(table["status"]) == "outcome_committed":
        if _json_object(table.get("outcome")) != outcome:
            raise HTTPException(status_code=409, detail="Committed V2 outcome conflicts")
        return {"success": True, "idempotent": True, "table": await _v2_table_response_with_conn(conn, table)}
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    seats = await conn.fetch("SELECT seat_no FROM casino_v2_table_seats WHERE table_id=$1 AND status='seated' FOR UPDATE", int(table["id"]))
    seated = {int(row["seat_no"]) for row in seats}
    if set(body.winner_seat_nos) - seated:
        raise HTTPException(status_code=409, detail="V2 winner seat is not seated")
    if body.outcome_kind == "tie_break":
        row = await conn.fetchrow("""UPDATE casino_v2_tables SET status='tie_break_running',game_state=game_state || jsonb_build_object('tie_break_leaders',$2::jsonb),state_version=state_version+1,updated_at=now()
            WHERE id=$1 AND status IN ('running','tie_break_running') RETURNING *""", int(table["id"]), json.dumps(sorted(body.winner_seat_nos)))
        if not row:
            raise HTTPException(status_code=409, detail="V2 table cannot enter tie break")
        return await _record_v2_idempotency_with_conn(conn, row, "commit_outcome", body, {"success": True, "tie_break": True, "table": await _v2_table_response_with_conn(conn, row)})
    allowed = {'running'} if body.outcome_kind == 'tie_split' else {'running', 'tie_break_running'}
    if str(table['status']) not in allowed:
        raise HTTPException(status_code=409, detail='V2 outcome cannot be committed in this state')
    if str(table['status']) == 'tie_break_running':
        leaders = set(_json_object(table.get('game_state')).get('tie_break_leaders') or [])
        if body.outcome_kind != 'winner' or body.winner_seat_nos[0] not in leaders:
            raise HTTPException(status_code=409, detail='Tie break winner must be one of the recorded leaders')
    row = await conn.fetchrow("""UPDATE casino_v2_tables SET status='outcome_committed',outcome=$3::jsonb,outcome_committed_at=now(),state_version=state_version+1,updated_at=now()
        WHERE id=$1 AND state_version=$2 RETURNING *""", int(table['id']), body.expected_state_version, json.dumps(outcome, separators=(',', ':')))
    if not row:
        raise HTTPException(status_code=409, detail='V2 outcome commit conflicts')
    return await _record_v2_idempotency_with_conn(conn, row, "commit_outcome", body, {"success": True, "table": await _v2_table_response_with_conn(conn, row)})


class V2SettlementFinancialFailure(RuntimeError):
    def __init__(self, *, table_id: str, table_db_id: int, cause: Exception):
        self.table_id = table_id
        self.table_db_id = table_db_id
        self.cause = cause
        self.reason = f"settlement financial exception: {type(cause).__name__}: {cause}"[:1000]
        super().__init__(self.reason)


async def _mark_v2_table_manual_review_with_conn(
    conn,
    *,
    table_id: str,
    table_db_id: int,
    reason: str,
) -> None:
    await lock_casino_game(conn, f"v2:{table_id}")
    row = await conn.fetchrow(
        """UPDATE casino_v2_tables
           SET status='manual_review', updated_at=now(),
               recovery_completed_at=now(), recovery_claim_token=NULL, recovery_claimed_at=NULL,
               game_state=game_state || jsonb_build_object('manual_review_reason',$2::text)
           WHERE id=$1 AND status IN ('outcome_committed','settling')
           RETURNING id""",
        table_db_id,
        reason,
    )
    if not row:
        raise HTTPException(status_code=409, detail="V2 table cannot be marked for manual review")


async def _persist_v2_settlement_manual_review(pool, failure: V2SettlementFinancialFailure) -> None:
    try:
        async with pool.acquire() as compensation_conn:
            async with compensation_conn.transaction():
                await _mark_v2_table_manual_review_with_conn(
                    compensation_conn,
                    table_id=failure.table_id,
                    table_db_id=failure.table_db_id,
                    reason=failure.reason,
                )
    except Exception:
        # Preserve the original financial failure if compensation itself fails.
        pass


async def settle_v2_table_with_conn(conn, table_id: str, body: V2TableSettleRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "settle", body)
    if replay:
        return replay
    if str(table["status"]) == "finished":
        settled = await conn.fetchrow("SELECT payload FROM casino_v2_settlements WHERE table_id=$1", int(table["id"]))
        return {**_json_object(settled["payload"]), "success": True, "idempotent": True}
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    if str(table["status"]) == "outcome_committed":
        committed = _json_object(table.get("outcome"))
        if committed != {"kind": body.outcome_kind, "winner_seat_nos": sorted(body.winner_seat_nos)}:
            raise HTTPException(status_code=409, detail="Committed V2 outcome conflicts")
    if body.outcome_kind == "tie_break":
        row = await conn.fetchrow("""UPDATE casino_v2_tables SET status='tie_break_running',state_version=state_version+1,updated_at=now()
             WHERE id=$1 AND state_version=$2 AND status IN ('running','tie_break_running') RETURNING *""", int(table["id"]), body.expected_state_version)
        if not row:
            raise HTTPException(status_code=409, detail="V2 table cannot enter tie break")
        return {"success": True, "idempotent": False, "table": await _v2_table_response_with_conn(conn, row), "tie_break": True}
    if str(table["status"]) not in {"outcome_committed"}:
        raise HTTPException(status_code=409, detail="V2 table cannot settle")
    settling = await conn.fetchrow("""UPDATE casino_v2_tables SET status='settling',state_version=state_version+1,updated_at=now()
        WHERE id=$1 AND state_version=$2 AND status='outcome_committed' RETURNING *""", int(table["id"]), body.expected_state_version)
    if not settling:
        raise HTTPException(status_code=409, detail="V2 table settlement conflicts")
    table = settling
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 ORDER BY seat_no FOR UPDATE", int(table["id"]))
    by_no = {int(seat["seat_no"]): seat for seat in seats}
    if set(body.winner_seat_nos) - set(by_no):
        raise HTTPException(status_code=409, detail="V2 winner seat is not seated")
    player_seats = [seat for seat in seats if seat["participant_kind"] == "player"]
    await lock_casino_users(conn, [int(seat["telegram_id"]) for seat in player_seats])
    stake, seat_count = money(table["stake_rub"]), len(seats)
    pot, commission = money(stake * seat_count), money(stake * seat_count * Decimal("0.05"))
    distributable = money(pot - commission)
    winners = sorted(body.winner_seat_nos)
    base, remainder = divmod(int(distributable * 100), len(winners))
    payouts = {seat_no: money(Decimal(base + (1 if index < remainder else 0)) / 100) for index, seat_no in enumerate(winners)}
    try:
        async with conn.transaction():
            for seat in player_seats:
                await confirm_unified_hold(conn, user_id=int(seat["telegram_id"]), order_ref=str(seat["hold_order_ref"]), amount_rub=stake,
                                           note=f"Casino v2 stake: {table_id}")
            for seat_no, payout in payouts.items():
                seat = by_no[seat_no]
                if seat["participant_kind"] == "player" and payout:
                    await _credit_winner(conn, game_id=f"v2-{table_id}", winner_id=int(seat["telegram_id"]), payout_rub=payout)
            reservation = await conn.fetchrow("SELECT * FROM casino_v2_house_reservations WHERE table_id=$1 FOR UPDATE", int(table["id"]))
            player_stakes = money(stake * len(player_seats))
            player_payouts = money(sum((payouts.get(int(seat["seat_no"]), Decimal("0")) for seat in player_seats), Decimal("0")))
            table_scope = scope_from_row(table)
            if not table_scope.is_rub:
                # Фишковый стол: банкролл и рейк в рублях не двигаются вообще.
                if reservation:
                    await conn.execute(
                        "UPDATE casino_v2_house_reservations SET status='settled',settled_at=now() WHERE id=$1",
                        int(reservation["id"]),
                    )
            elif reservation:
                # Bots are fully backed by the house. Their stake and payout net internally;
                # only player cash-flow changes the house balance. The reservation is an
                # exposure lock, never a second debit. Rake is inside player_stakes − player_payouts.
                account = await conn.fetchrow("""UPDATE casino_house_accounts SET balance_rub=balance_rub+$2-$3,reserved_rub=reserved_rub-$4,updated_at=now()
                     WHERE id=$1 AND reserved_rub >= $4 RETURNING balance_rub""", int(reservation["account_id"]), player_stakes, player_payouts, money(reservation["amount_rub"]))
                if not account:
                    raise HTTPException(status_code=409, detail="V2 house reservation conflicts")
                await conn.execute("UPDATE casino_v2_house_reservations SET status='settled',settled_at=now() WHERE id=$1", int(reservation["id"]))
                await conn.execute("""INSERT INTO casino_v2_house_ledger(table_id,account_id,operation_key,entry_type,amount_rub,balance_after_rub,reason)
                    VALUES($1,$2,$3,'game_settlement',$4,$5,$6)
                    ON CONFLICT (operation_key) DO NOTHING""", int(table["id"]), int(reservation["account_id"]),
                    f"v2-settlement-{table_id}", money(player_stakes-player_payouts), money(account["balance_rub"]),
                    f"Casino v2 table settlement: {table_id}")
            elif any(seat["participant_kind"] == "bot" for seat in seats):
                raise HTTPException(status_code=409, detail="V2 bot table is missing its house reservation")
            elif commission > 0:
                # All-human table: 5% left the pot and must land on the house, not vanish.
                account = await conn.fetchrow(
                    """UPDATE casino_house_accounts
                       SET balance_rub = balance_rub + $1, updated_at = now()
                       WHERE account_key = 'main'
                       RETURNING id, balance_rub""",
                    commission,
                )
                if not account:
                    raise HTTPException(status_code=409, detail="V2 house rake has no house account")
                await conn.execute(
                    """INSERT INTO casino_v2_house_ledger(table_id,account_id,operation_key,entry_type,amount_rub,balance_after_rub,reason)
                    VALUES($1,$2,$3,'game_settlement',$4,$5,$6)
                    ON CONFLICT (operation_key) DO NOTHING""",
                    int(table["id"]),
                    int(account["id"]),
                    f"v2-settlement-{table_id}",
                    commission,
                    money(account["balance_rub"]),
                    f"Casino v2 table rake: {table_id}",
                )
            payload = {
                "success": True, "idempotent": False, "table_id": table_id,
                "outcome_kind": body.outcome_kind,
                "winner_seat_nos": winners,
                "game_type": str(table["game_type"]),
                "stake_rub": _text_money(stake),
                "pot_rub": _text_money(pot), "commission_rub": _text_money(commission),
                "payouts": [{"seat_no": seat_no, "amount_rub": _text_money(amount)} for seat_no, amount in payouts.items()],
            }
            await conn.execute("""INSERT INTO casino_v2_settlements(table_id,outcome_kind,commission_rub,pot_rub,payout_rub,payload)
                VALUES($1,$2,$3,$4,$5,$6::jsonb)""", int(table["id"]), body.outcome_kind, commission, pot, distributable, json.dumps(payload, separators=(",", ":")))
            row = await conn.fetchrow("""UPDATE casino_v2_tables SET status='finished',state_version=state_version+1,settled_at=now(),settlement_payload=$2::jsonb,updated_at=now()
                WHERE id=$1 AND status='settling' RETURNING *""", int(table["id"]), json.dumps(payload, separators=(",", ":")))
            if not row:
                raise HTTPException(status_code=409, detail="V2 table finish conflicts")
            await conn.execute("UPDATE casino_v2_table_seats SET status='settled' WHERE table_id=$1 AND status='seated'", int(table["id"]))
            for seat in player_seats:
                recipient_id = int(seat["telegram_id"])
                seat_no = int(seat["seat_no"])
                your_payout = payouts.get(seat_no, Decimal("0"))
                result = _v2_seat_result(
                    outcome_kind=body.outcome_kind, seat_no=seat_no, winner_seat_nos=winners,
                )
                available = await _snapshot_available_rub(conn, recipient_id)
                personal = {
                    **payload,
                    "game_chat_id": int(table["game_chat_id"]) if table.get("game_chat_id") is not None else None,
                    "result": result,
                    "your_payout_rub": _text_money(your_payout),
                    "available_rub": available,
                    "seat_no": seat_no,
                    "public_delivery_separate": True,
                    "text": format_personal_result_html(
                        result=result,
                        game_type=str(table["game_type"]),
                        game_id=table_id,
                        payout_rub=your_payout,
                        available_rub=available,
                    ),
                }
                await conn.execute("""INSERT INTO casino_v2_notification_outbox(event_key,table_id,recipient_id,event_type,payload)
                    VALUES($1,$2,$3,'settled',$4::jsonb) ON CONFLICT(table_id,event_type,recipient_id) DO NOTHING""",
                    f"v2:{table_id}:settled:{recipient_id}", int(table["id"]), recipient_id, json.dumps(personal, separators=(",", ":")))
            await _enqueue_v2_public_outbox(
                conn,
                row,
                event_type="public_settled",
                payload=payload,
            )
            return await _record_v2_idempotency_with_conn(conn, row, "settle", body, {**payload, "table": await _v2_table_response_with_conn(conn, row)})
    except Exception as exc:
        # The nested transaction rolls financial work back. The endpoint records
        # manual_review in a separate transaction after the outer rollback.
        raise V2SettlementFinancialFailure(
            table_id=table_id,
            table_db_id=int(table["id"]),
            cause=exc,
        ) from exc


async def settle_committed_v2_table_with_conn(conn, table_id: str, body: V2TableSettleCommittedRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "settle_committed", body)
    if replay:
        return replay
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    if str(table["status"]) != "outcome_committed":
        if str(table["status"]) == "finished":
            settled = await conn.fetchrow("SELECT payload FROM casino_v2_settlements WHERE table_id=$1", int(table["id"]))
            return {**_json_object(settled["payload"]), "success": True, "idempotent": True}
        raise HTTPException(status_code=409, detail="V2 table has no committed outcome")
    outcome = _json_object(table.get("outcome"))
    if outcome.get("kind") not in {"winner", "tie_split"}:
        raise HTTPException(status_code=409, detail="V2 committed outcome is not settleable")
    result = await settle_v2_table_with_conn(conn, table_id, V2TableSettleRequest(expected_state_version=body.expected_state_version, outcome_kind=outcome["kind"], winner_seat_nos=outcome["winner_seat_nos"], idempotency_key=body.idempotency_key))
    return await _record_v2_idempotency_with_conn(conn, table, "settle_committed", body, result)


async def release_v2_table_with_conn(conn, table_id: str, body: V2TableReleaseRequest) -> dict:
    await lock_casino_game(conn, f"v2:{table_id}")
    table = await conn.fetchrow("SELECT * FROM casino_v2_tables WHERE table_id=$1 FOR UPDATE", table_id)
    if not table:
        raise HTTPException(status_code=404, detail="V2 table not found")
    replay = await _replay_v2_idempotency_with_conn(conn, table, "release", body)
    if replay:
        return replay
    if int(table["creator_id"]) != body.creator_id:
        raise HTTPException(status_code=403, detail="Only the table creator may release it")
    if int(table["state_version"]) != body.expected_state_version:
        raise HTTPException(status_code=409, detail="V2 table state version conflicts")
    if str(table["status"]) not in {"open", "ready", "outcome_committed", "settling"}:
        raise HTTPException(status_code=409, detail="V2 table cannot be released")
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 AND status='seated' FOR UPDATE", int(table["id"]))
    player_ids = sorted({int(seat["telegram_id"]) for seat in seats if seat["participant_kind"] == "player"})
    await lock_casino_users(conn, player_ids)
    for seat in seats:
        if seat["participant_kind"] == "player":
            await release_unified_hold(conn, user_id=int(seat["telegram_id"]), order_ref=str(seat["hold_order_ref"]), amount_rub=money(table["stake_rub"]), note=body.reason)
    await conn.execute("UPDATE casino_v2_table_seats SET status='released' WHERE table_id=$1 AND status='seated'", int(table["id"]))
    reservation = await conn.fetchrow("SELECT * FROM casino_v2_house_reservations WHERE table_id=$1 AND status='active' FOR UPDATE", int(table["id"]))
    if reservation:
        account = await conn.fetchrow("UPDATE casino_house_accounts SET reserved_rub=reserved_rub-$2,updated_at=now() WHERE id=$1 AND reserved_rub >= $2 RETURNING id", int(reservation["account_id"]), money(reservation["amount_rub"]))
        if not account:
            raise HTTPException(status_code=409, detail="V2 house reservation conflicts")
        await conn.execute("UPDATE casino_v2_house_reservations SET status='released',released_at=now() WHERE id=$1", int(reservation["id"]))
    row = await conn.fetchrow("UPDATE casino_v2_tables SET status='cancelled',state_version=state_version+1,settled_at=now(),updated_at=now() WHERE id=$1 AND state_version=$2 RETURNING *", int(table["id"]), body.expected_state_version)
    if not row:
        raise HTTPException(status_code=409, detail="V2 release conflicts")
    await _enqueue_v2_cancelled_outbox(conn, row, seats)
    return await _record_v2_idempotency_with_conn(conn, row, "release", body, {"success": True, "released": True, "table": await _v2_table_response_with_conn(conn, row)})


async def active_v2_tables_with_conn(conn) -> dict:
    rows = await conn.fetch("SELECT * FROM casino_v2_tables WHERE status IN ('draft','open','ready','running','tie_break_running','outcome_committed','settling') ORDER BY created_at")
    return {"success": True, "tables": [await _v2_table_response_with_conn(conn, row) for row in rows]}


async def recovery_snapshot_v2_with_conn(conn) -> dict:
    rows = await conn.fetch("SELECT * FROM casino_v2_tables WHERE status IN ('draft','open','ready','running','tie_break_running','outcome_committed','settling') ORDER BY updated_at")
    return {"success": True, "tables": [await _v2_table_response_with_conn(conn, row) for row in rows]}


async def _expire_locked_v2_unstarted(conn, table) -> dict:
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 AND status='seated' FOR UPDATE", int(table['id']))
    for seat in seats:
        if seat['participant_kind'] == 'player':
            await lock_casino_users(conn, (int(seat['telegram_id']),))
            await release_unified_hold(conn, user_id=int(seat['telegram_id']), order_ref=str(seat['hold_order_ref']), amount_rub=money(table['stake_rub']), note=f"Casino v2 table expired: {table['table_id']}")
    reservation = await conn.fetchrow("SELECT * FROM casino_v2_house_reservations WHERE table_id=$1 AND status='active' FOR UPDATE", int(table['id']))
    if reservation:
        account = await conn.fetchrow("UPDATE casino_house_accounts SET reserved_rub=reserved_rub-$2,updated_at=now() WHERE id=$1 AND reserved_rub >= $2 RETURNING id", int(reservation['account_id']), money(reservation['amount_rub']))
        if not account:
            raise HTTPException(status_code=409, detail='V2 house reservation conflicts during expiry')
        await conn.execute("UPDATE casino_v2_house_reservations SET status='released',released_at=now() WHERE id=$1", int(reservation['id']))
    await conn.execute("UPDATE casino_v2_table_seats SET status='released' WHERE table_id=$1 AND status='seated'", int(table['id']))
    row = await conn.fetchrow("UPDATE casino_v2_tables SET status='expired',state_version=state_version+1,settled_at=now(),updated_at=now() WHERE id=$1 AND status IN ('draft','open','ready') RETURNING *", int(table['id']))
    if not row:
        raise HTTPException(status_code=409, detail='V2 table expiry conflicts')
    await _enqueue_v2_cancelled_outbox(conn, row, seats)
    return await _v2_table_response_with_conn(conn, row)


async def _expire_stale_v2_play_table(conn, table) -> dict:
    seats = await conn.fetch("SELECT * FROM casino_v2_table_seats WHERE table_id=$1 AND status='seated' FOR UPDATE", int(table['id']))
    for seat in seats:
        if seat['participant_kind'] == 'player':
            await lock_casino_users(conn, (int(seat['telegram_id']),))
            await release_unified_hold(conn, user_id=int(seat['telegram_id']), order_ref=str(seat['hold_order_ref']), amount_rub=money(table['stake_rub']), note=f"Casino v2 table expired: {table['table_id']}")
    reservation = await conn.fetchrow("SELECT * FROM casino_v2_house_reservations WHERE table_id=$1 AND status='active' FOR UPDATE", int(table['id']))
    if reservation:
        account = await conn.fetchrow("UPDATE casino_house_accounts SET reserved_rub=reserved_rub-$2,updated_at=now() WHERE id=$1 AND reserved_rub >= $2 RETURNING id", int(reservation['account_id']), money(reservation['amount_rub']))
        if not account:
            raise HTTPException(status_code=409, detail='V2 house reservation conflicts during expiry')
        await conn.execute("UPDATE casino_v2_house_reservations SET status='released',released_at=now() WHERE id=$1", int(reservation['id']))
    await conn.execute("UPDATE casino_v2_table_seats SET status='released' WHERE table_id=$1 AND status='seated'", int(table['id']))
    row = await conn.fetchrow(
        "UPDATE casino_v2_tables SET status='expired',state_version=state_version+1,settled_at=now(),updated_at=now() WHERE id=$1 AND status IN ('running','tie_break_running') RETURNING *",
        int(table['id']),
    )
    if not row:
        raise HTTPException(status_code=409, detail='V2 stale play expiry conflicts')
    await _enqueue_v2_cancelled_outbox(conn, row, seats)
    return await _v2_table_response_with_conn(conn, row)


async def expire_stale_v2_play_with_conn(conn, *, now: datetime | None = None, limit: int = 20) -> int:
    from casino_v2_web import v2_play_is_stale

    clock = now or datetime.now(timezone.utc)
    rows = await conn.fetch(
        """
        SELECT * FROM casino_v2_tables
        WHERE status IN ('running', 'tie_break_running')
        ORDER BY updated_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
        """,
        int(limit),
    )
    expired = 0
    for table in rows:
        if not v2_play_is_stale(table, now=clock):
            continue
        await _expire_stale_v2_play_table(conn, table)
        expired += 1
    return expired


async def expire_v2_tables_with_conn(conn) -> dict:
    """Release unstarted tables idle for 24 hours and stale in-play leftovers."""
    rows = await conn.fetch("""SELECT * FROM casino_v2_tables WHERE status IN ('draft','open','ready')
        AND created_at <= now() - interval '24 hours' FOR UPDATE SKIP LOCKED""")
    expired = []
    for table in rows:
        expired.append(await _expire_locked_v2_unstarted(conn, table))
    stale_play = await expire_stale_v2_play_with_conn(conn)
    return {'success': True, 'expired': expired, 'stale_play': stale_play}


async def expire_unjoined_v2_tables_with_conn(conn, *, cutoff, limit: int = 20) -> int:
    """Expire open/ready V2 tables older than cutoff with fewer than two humans."""
    rows = await conn.fetch(
        """
        /* v2:expire-unjoined */
        SELECT t.* FROM casino_v2_tables t
        WHERE t.status IN ('draft','open','ready')
          AND t.created_at <= $1
          AND (
            SELECT count(*) FROM casino_v2_table_seats s
            WHERE s.table_id = t.id AND s.status = 'seated' AND s.participant_kind = 'player'
          ) < 2
        ORDER BY t.created_at
        LIMIT $2
        FOR UPDATE OF t SKIP LOCKED
        """,
        cutoff,
        int(limit),
    )
    expired = 0
    for table in rows:
        await _expire_locked_v2_unstarted(conn, table)
        expired += 1
    return expired


async def claim_v2_recovery_with_conn(conn, body: ClaimRequest) -> dict:
    token_prefix = f"{body.worker_id}:{uuid4().hex}"
    rows = await conn.fetch("""WITH candidates AS (
        SELECT id FROM casino_v2_tables WHERE status IN ('running','tie_break_running','outcome_committed','settling')
          AND (recovery_claimed_at IS NULL OR recovery_claimed_at < now() - make_interval(secs => $2))
        ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT $1
    ) UPDATE casino_v2_tables t SET recovery_claim_token=$3 || ':' || t.id::text,recovery_claimed_at=now(),updated_at=now()
      FROM candidates WHERE t.id=candidates.id RETURNING t.*""", body.limit, body.lease_seconds, token_prefix)
    return {'success': True, 'items': [{'table': await _v2_table_response_with_conn(conn, row), 'claim_token': str(row['recovery_claim_token'])} for row in rows]}


async def complete_v2_recovery_with_conn(conn, body: V2RecoveryCompleteRequest) -> dict:
    row = await conn.fetchrow("""UPDATE casino_v2_tables SET recovery_completed_at=now(),recovery_claim_token=NULL,recovery_claimed_at=NULL,updated_at=now()
        WHERE table_id=$1 AND recovery_claim_token=$2 RETURNING *""", body.table_id, body.claim_token)
    if not row:
        raise HTTPException(status_code=409, detail='V2 recovery claim is not owned or has expired')
    return {'success': True, 'table': await _v2_table_response_with_conn(conn, row)}


async def claim_v2_outbox_with_conn(conn, body: ClaimRequest) -> dict:
    prefix = f"{body.worker_id}:{uuid4().hex}"
    rows = await conn.fetch("""WITH candidates AS (
        SELECT id FROM casino_v2_notification_outbox WHERE (status='pending' AND available_at <= now())
           OR (status='processing' AND claimed_at < now() - make_interval(secs => $2))
        ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT $1
    ) UPDATE casino_v2_notification_outbox o SET status='processing',attempts=attempts+1,claim_token=$3 || ':' || o.id::text,claimed_at=now(),updated_at=now()
       FROM candidates WHERE o.id=candidates.id RETURNING o.*""", body.limit, body.lease_seconds, prefix)
    return {'success': True, 'items': [{'outbox_id': int(row['id']), 'recipient_id': int(row['recipient_id']), 'event_type': str(row['event_type']), 'payload': _json_object(row['payload']), 'claim_token': str(row['claim_token'])} for row in rows]}


async def complete_v2_outbox_with_conn(conn, body: V2OutboxCompleteRequest) -> dict:
    row = await conn.fetchrow("""UPDATE casino_v2_notification_outbox SET status='completed',completed_at=now(),updated_at=now()
        WHERE id=$1 AND status='processing' AND claim_token=$2 RETURNING id""", body.outbox_id, body.claim_token)
    if not row:
        raise HTTPException(status_code=409, detail='V2 outbox claim is not owned or has expired')
    return {'success': True, 'outbox_id': int(row['id'])}


async def fail_v2_outbox_with_conn(conn, body: V2OutboxFailRequest) -> dict:
    row = await conn.fetchrow("""UPDATE casino_v2_notification_outbox SET status=CASE
            WHEN created_at <= now() - interval '72 hours' THEN 'dead'
            WHEN $4 <> 'rate_limited' AND attempts >= 10 THEN 'dead'
            ELSE 'pending' END,
        attempts=CASE WHEN $4='rate_limited' THEN GREATEST(attempts-1,0) ELSE attempts END,
        available_at=now()+make_interval(secs => CASE
            WHEN $4='rate_limited' THEN GREATEST(COALESCE($5,1),1)
            ELSE LEAST(3600,5*(2^LEAST(attempts,9))::integer) END),
        claim_token=NULL,last_error=$3,last_error_kind=$4,updated_at=now()
        WHERE id=$1 AND status='processing' AND claim_token=$2 RETURNING id,status,attempts,available_at""",
        body.outbox_id, body.claim_token, body.error, body.error_kind, body.retry_after_seconds)
    if not row:
        raise HTTPException(status_code=409, detail='V2 outbox claim is not owned or has expired')
    return {
        'success': True,
        'outbox_id': int(row['id']),
        'status': str(row['status']),
        'attempts': int(row['attempts']),
        'available_at': _utc(row['available_at']).isoformat(),
    }


async def resume_blocked_notifications_with_conn(conn, body: NotificationResumeRequest) -> dict:
    """Requeue a small recipient-only batch after a real private ``/start``.

    Financial settlement is never repeated: only already-created notification
    rows explicitly classified as an unavailable DM are made claimable again.
    Group board jobs are delivered through the game chat and never resumed as
    personal notifications, even for the creator's recipient id.
    """
    public_types = sorted(V2_NON_RESUMABLE_EVENT_TYPES)
    v2_rows = await conn.fetch(
        """WITH candidates AS (
            SELECT id FROM casino_v2_notification_outbox
            WHERE recipient_id=$1 AND status IN ('pending','dead')
              AND last_error_kind='dm_unavailable'
              AND NOT (event_type = ANY($3::text[]))
            ORDER BY id DESC LIMIT $2 FOR UPDATE SKIP LOCKED
        ) UPDATE casino_v2_notification_outbox o
          SET status='pending',attempts=0,available_at=now(),claim_token=NULL,
              claimed_at=NULL,updated_at=now()
          FROM candidates c WHERE o.id=c.id RETURNING o.id""",
        body.telegram_id,
        body.limit,
        public_types,
    )
    remaining = max(0, body.limit - len(v2_rows))
    legacy_rows = []
    if remaining:
        legacy_rows = await conn.fetch(
            """WITH candidates AS (
                SELECT id FROM casino_notification_outbox
                WHERE recipient_id=$1 AND status IN ('pending','dead')
                  AND last_error_kind='dm_unavailable'
                ORDER BY id DESC LIMIT $2 FOR UPDATE SKIP LOCKED
            ) UPDATE casino_notification_outbox o
              SET status='pending',attempts=0,available_at=now(),claim_token=NULL,
                  claimed_at=NULL,updated_at=now()
              FROM candidates c WHERE o.id=c.id RETURNING o.id""",
            body.telegram_id,
            remaining,
        )
    return {
        'success': True,
        'resumed': len(v2_rows) + len(legacy_rows),
        'v2_outbox_ids': [int(row['id']) for row in v2_rows],
        'legacy_outbox_ids': [int(row['id']) for row in legacy_rows],
    }


@router.post("/v2/tables")
async def create_v2_table(body: V2TableCreateRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    _ensure_v2_web_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_v2_table_with_conn(conn, body)


@router.post("/v2/tables/{table_id}/seats")
async def join_v2_table(table_id: str, body: V2TableJoinRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    _ensure_v2_web_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_v2_table_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/bots")
async def add_v2_table_bot(table_id: str, body: V2TableAddBotRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    _ensure_v2_web_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await add_v2_bot_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/start")
async def start_v2_table(table_id: str, body: V2TableStartRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    _ensure_v2_web_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await start_v2_table_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/settle")
async def settle_v2_table(table_id: str, body: V2TableSettleRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await settle_v2_table_with_conn(conn, table_id, body)
    except V2SettlementFinancialFailure as failure:
        await _persist_v2_settlement_manual_review(pool, failure)
        raise failure.cause from failure


@router.post("/v2/tables/{table_id}/leave")
async def leave_v2_table(table_id: str, body: V2TableLeaveRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_v2_table_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/cancel")
async def cancel_v2_table(table_id: str, body: V2TableLeaveRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_v2_table_with_conn(conn, table_id, body, cancel=True)


@router.post("/v2/tables/{table_id}/persist-state")
async def persist_v2_table_state(table_id: str, body: V2TablePersistStateRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await persist_v2_table_state_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/cards/prepare")
async def prepare_v2_table_cards(table_id: str, body: V2CardsPrepareRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await prepare_v2_table_cards_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/cards/deal")
async def deal_v2_table_cards(table_id: str, body: V2CardsDealRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await deal_v2_table_cards_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/cards/reveal")
async def reveal_v2_table_cards(table_id: str, body: V2CardsRevealRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await reveal_v2_table_cards_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/commit-outcome")
async def commit_v2_table_outcome(table_id: str, body: V2TableCommitOutcomeRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await commit_v2_table_outcome_with_conn(conn, table_id, body)


@router.post("/v2/tables/{table_id}/settle-committed-outcome")
async def settle_committed_v2_table(table_id: str, body: V2TableSettleCommittedRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await settle_committed_v2_table_with_conn(conn, table_id, body)
    except V2SettlementFinancialFailure as failure:
        await _persist_v2_settlement_manual_review(pool, failure)
        raise failure.cause from failure


@router.post("/v2/tables/{table_id}/release")
async def release_v2_table(table_id: str, body: V2TableReleaseRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await release_v2_table_with_conn(conn, table_id, body)


@router.get("/v2/tables/active")
async def active_v2_tables(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await active_v2_tables_with_conn(conn)


@router.get("/v2/recovery/snapshot")
async def recovery_snapshot_v2(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await recovery_snapshot_v2_with_conn(conn)


@router.post("/v2/tables/expire")
async def expire_v2_tables(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await expire_v2_tables_with_conn(conn)


@router.post("/v2/recovery/claim")
async def claim_v2_recovery(body: ClaimRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await claim_v2_recovery_with_conn(conn, body)


@router.post("/v2/recovery/complete")
async def complete_v2_recovery(body: V2RecoveryCompleteRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await complete_v2_recovery_with_conn(conn, body)


@router.post("/v2/outbox/claim")
async def claim_v2_outbox(body: ClaimRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await claim_v2_outbox_with_conn(conn, body)


@router.post("/v2/outbox/complete")
async def complete_v2_outbox(body: V2OutboxCompleteRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await complete_v2_outbox_with_conn(conn, body)


@router.post("/v2/outbox/fail")
async def fail_v2_outbox(body: V2OutboxFailRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(): return await fail_v2_outbox_with_conn(conn, body)


@router.post("/notifications/resume")
async def resume_blocked_notifications(
    body: NotificationResumeRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await resume_blocked_notifications_with_conn(conn, body)


@router.post("/chat-binding/pending")
async def create_pending_game_chat_binding(
    body: GameChatBindingPendingRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_pending_game_chat_binding_with_conn(conn, body)


@router.get("/chat-binding/active")
async def get_active_game_chat_binding(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await active_game_chat_binding_with_conn(conn)


@router.post("/cards/prepare")
async def prepare_cards(
    body: CardsPrepareRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await prepare_cards_with_conn(conn, body)


@router.post("/cards/deal")
async def deal_cards(
    body: CardsDealRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await deal_cards_with_conn(conn, body)


@router.post("/cards/reveal")
async def reveal_cards(
    body: CardsRevealRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await reveal_cards_with_conn(conn, body)


@router.get("/fairness/session")
async def fairness_session(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    if telegram_id < 1:
        raise HTTPException(status_code=422, detail="telegram_id must be positive")
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await public_fairness_session(conn, telegram_id)


@router.post("/fairness/client-seed")
async def fairness_client_seed(
    body: FairnessClientSeedRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await set_client_seed(conn, body.telegram_id, body.client_seed)


@router.post("/fairness/rotate")
async def fairness_rotate(
    body: FairnessSessionRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await rotate_fairness_session(conn, body.telegram_id)


@router.post("/cub/prepare")
async def prepare_cub(
    body: PrepareCubRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await prepare_cub_with_conn(conn, body)


@router.post("/cub/play")
async def play_cub(body: CubPlayRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await play_cub_with_conn(conn, body)


@router.post("/cub/open")
async def open_cub(body: CubOpenRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await open_cub_with_conn(conn, body)


@router.post("/cub/resolve")
async def resolve_cub(
    body: CubResolveRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await resolve_cub_with_conn(conn, body)


@router.get("/cub/pending")
async def get_pending_cub(
    telegram_id: PositiveTelegramId,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await pending_cub_with_conn(conn, telegram_id)


@router.get("/roulette-table")
async def get_internal_roulette_table(
    telegram_id: PositiveTelegramId | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_roulette_table import ensure_closer as roulette_table_ensure_closer
    from casino_roulette_table import snapshot as roulette_table_snapshot

    roulette_table_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_snapshot(conn, viewer_id=telegram_id)
    return {"success": True, **snap}


@router.post("/roulette-table/bet")
async def post_internal_roulette_table_bet(
    body: RouletteTableBetRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_roulette_table import ensure_closer as roulette_table_ensure_closer
    from casino_roulette_table import place_bets as roulette_table_place_bets

    roulette_table_ensure_closer()
    chips = (
        [{"bet": chip.bet, "amount_rub": chip.amount_rub} for chip in body.chips]
        if body.chips
        else [{"bet": body.bet, "amount_rub": body.amount_rub}]
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await roulette_table_place_bets(
                conn,
                user_id=int(body.telegram_id),
                chips=chips,
                notify_chat_id=int(body.notify_chat_id),
            )
    return {"success": True, **snap}


@router.get("/jackpot")
async def get_internal_jackpot(
    telegram_id: PositiveTelegramId | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_jackpot import ensure_closer as jackpot_ensure_closer
    from casino_jackpot import snapshot as jackpot_snapshot

    jackpot_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await jackpot_snapshot(conn, viewer_id=telegram_id)
    return {"success": True, **snap}


@router.post("/jackpot/bet")
async def post_internal_jackpot_bet(
    body: JackpotBetRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_jackpot import ensure_closer as jackpot_ensure_closer
    from casino_jackpot import place_bet as jackpot_place_bet

    jackpot_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await jackpot_place_bet(
                conn,
                user_id=int(body.telegram_id),
                amount_rub=body.amount_rub,
                notify_chat_id=int(body.notify_chat_id),
            )
    return {"success": True, **snap}


def _strip_room_id(room_id: str) -> str:
    token = str(room_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="room_id must not be blank")
    return token


@router.get("/rooms")
async def get_internal_fixed_rooms(
    telegram_id: PositiveTelegramId | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import list_open as rooms_list_open

    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            payload = await rooms_list_open(conn, viewer_id=telegram_id)
    return {"success": True, **payload}


@router.get("/rooms/{room_id}")
async def get_internal_fixed_room(
    room_id: str,
    telegram_id: PositiveTelegramId | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import snapshot as rooms_snapshot

    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_snapshot(conn, _strip_room_id(room_id), viewer_id=telegram_id)
    return {"success": True, **snap}


@router.post("/rooms")
async def post_internal_fixed_room(
    body: FixedRoomCreateRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import create_room as rooms_create
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer

    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_create(
                conn,
                user_id=int(body.telegram_id),
                stake_rub=body.stake_rub,
                seat_count=int(body.seat_count),
            )
    return {"success": True, **snap}


@router.post("/rooms/{room_id}/join")
async def post_internal_fixed_room_join(
    room_id: str,
    body: FixedRoomActorRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer
    from casino_fixed_rooms import join_room as rooms_join

    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_join(
                conn, user_id=int(body.telegram_id), room_id=_strip_room_id(room_id)
            )
    return {"success": True, **snap}


@router.post("/rooms/{room_id}/leave")
async def post_internal_fixed_room_leave(
    room_id: str,
    body: FixedRoomActorRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import leave_room as rooms_leave

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_leave(
                conn, user_id=int(body.telegram_id), room_id=_strip_room_id(room_id)
            )
    return {"success": True, **snap}


@router.post("/rooms/{room_id}/cancel")
async def post_internal_fixed_room_cancel(
    room_id: str,
    body: FixedRoomActorRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import cancel_room as rooms_cancel

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_cancel(
                conn, user_id=int(body.telegram_id), room_id=_strip_room_id(room_id)
            )
    return {"success": True, **snap}


@router.post("/rooms/{room_id}/bots")
async def post_internal_fixed_room_bot(
    room_id: str,
    body: FixedRoomActorRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    from casino_fixed_rooms import add_bot as rooms_add_bot
    from casino_fixed_rooms import ensure_closer as rooms_ensure_closer

    rooms_ensure_closer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            snap = await rooms_add_bot(
                conn, user_id=int(body.telegram_id), room_id=_strip_room_id(room_id)
            )
    return {"success": True, **snap}


@router.get("/games/active")
async def get_active_pvp_games(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await active_pvp_games_with_conn(conn)


@router.post("/games/create-or-resume")
async def create_or_resume_game(body: CasinoGameCreateRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_or_resume_game_with_conn(conn, body)


@router.post("/games/create-from-dm")
async def create_pvp_from_dm(body: CasinoDmPvpCreateRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await create_pvp_from_dm_with_conn(conn, body)


@router.post("/games/join-and-hold")
async def join_and_hold_game(body: CasinoGameJoinRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_and_hold_game_with_conn(conn, body)


@router.post("/games/join-pvp-robot")
async def join_pvp_robot_game(body: CasinoGameJoinRobotRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await join_robot_and_reserve_game_with_conn(conn, body)


@router.post("/games/persist-state")
async def persist_game_state(body: CasinoGameStateRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await persist_game_state_with_conn(conn, body)


@router.post("/games/record-roll")
async def record_pvp_dice_roll(body: CasinoGameDiceRollRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    from casino_pvp_dice import record_roll as record_pvp_dice_roll_with_conn

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await record_pvp_dice_roll_with_conn(
                conn,
                game_id=body.game_id,
                telegram_id=body.telegram_id,
                value=body.value,
            )


@router.post("/games/commit-outcome")
async def commit_game_outcome(body: CasinoGameOutcomeRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await commit_game_outcome_with_conn(conn, body)


@router.post("/games/settle-committed-outcome")
async def settle_committed_outcome(body: CasinoGameIdRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await settle_committed_outcome_with_conn(conn, body)


@router.post("/games/release-game")
async def release_game(body: CasinoGameReleaseRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await release_game_with_conn(conn, body)


@router.post("/recovery/claim")
async def claim_recovery(body: ClaimRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await claim_recovery_with_conn(conn, body)


@router.post("/recovery/complete")
async def complete_recovery(body: RecoveryCompleteRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await complete_recovery_with_conn(conn, body)


@router.get("/recovery/snapshot")
async def recovery_snapshot(x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await recovery_snapshot_with_conn(conn)


@router.post("/pvp-invitations/claim")
async def claim_pvp_invitations(body: ClaimRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await claim_pvp_invitation_outbox_with_conn(conn, body)


@router.post("/pvp-invitations/complete")
async def complete_pvp_invitation(body: InvitationOutboxCompleteRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await complete_pvp_invitation_outbox_with_conn(conn, body)


@router.post("/pvp-invitations/fail")
async def fail_pvp_invitation(body: OutboxFailRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await fail_pvp_invitation_outbox_with_conn(conn, body)


@router.post("/outbox/claim")
async def claim_outbox(body: ClaimRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await claim_outbox_with_conn(conn, body)


@router.post("/outbox/complete")
async def complete_outbox(body: OutboxCompleteRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await complete_outbox_with_conn(conn, body)


@router.post("/outbox/fail")
async def fail_outbox(body: OutboxFailRequest, x_internal_token: str | None = Header(None, alias="X-Internal-Token")):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await fail_outbox_with_conn(conn, body)


@router.get("/users/{telegram_id}/profile")
async def get_player_profile(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Return the casino-only balance, wagering, and weekly cashback snapshot."""
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    current_day = datetime.now(_CASINO_TIMEZONE).date()
    week_start = current_day - timedelta(days=current_day.weekday())
    commission_profile = "wagering_complete"
    applied_commission_rate = Decimal("0")
    volume_tier = None
    tier_config = None
    async with pool.acquire() as conn:
        identity = await conn.fetchrow(
            "SELECT first_name, username FROM bot_users WHERE user_id = $1",
            telegram_id,
        )
        unified = money(await unified_available(conn, telegram_id))
        legacy_holds = money(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM casino_balance_holds
                WHERE telegram_id = $1
                  AND status = 'active'
                  AND expires_at > now()
                  AND ledger_order_ref IS NULL
                """,
                telegram_id,
            )
            or 0
        )
        wagering = await wagering_progress(conn, telegram_id)
        weekly = await conn.fetchrow(
            """
            WITH week AS (
                SELECT ($4::date::timestamp AT TIME ZONE 'Europe/Moscow') AS start_at,
                       (($4::date + 7)::timestamp AT TIME ZONE 'Europe/Moscow') AS end_at,
                       $4::date AS week_start
            ), player_games AS (
                SELECT bet_rub,
                       CASE
                           WHEN counterparty_kind = 'player'
                                AND opponent_id IS NOT NULL
                                AND winner_id IN (creator_id, opponent_id)
                                AND winner_id <> $1 THEN bet_rub
                           WHEN counterparty_kind = 'pvp_robot'
                                AND game_type = ANY($3::text[])
                                AND creator_id = $1
                                AND winner_id IS NULL
                                AND outcome->>'kind' = 'house_win' THEN bet_rub
                           WHEN game_type = 'cub'
                                AND counterparty_kind = 'house_robot'
                                AND creator_id = $1
                                AND winner_id IS NULL
                                AND outcome->>'kind' = 'loss' THEN bet_rub
                           ELSE 0
                       END AS loss_rub
                FROM casino_games, week
                WHERE status = 'finished'
                  AND finished_at >= week.start_at
                  AND finished_at < week.end_at
                  AND game_type = ANY($2::text[])
                  AND (creator_id = $1 OR opponent_id = $1)
            )
            SELECT week.week_start,
                   COALESCE((SELECT SUM(bet_rub) FROM player_games), 0)::numeric AS wager_rub,
                   COALESCE((SELECT SUM(loss_rub) FROM player_games), 0)::numeric AS loss_rub
            FROM week
            """,
            telegram_id,
            list(_CASHBACK_GAME_TYPES),
            list(_PVP_GAME_TYPES),
            week_start,
        )
        previous = await conn.fetchrow(
            """
            SELECT week_start, net_loss_rub, cashback_rub,
                   COALESCE((to_jsonb(casino_player_cashback) ->> 'cashback_percent')::numeric, 0) AS cashback_percent,
                   status
            FROM casino_player_cashback
            WHERE telegram_id = $1
              AND week_start < $2::date
            ORDER BY week_start DESC, id DESC
            LIMIT 1
            """,
            telegram_id,
            week_start,
        )
        tier_config = await load_tier_config(conn)
        weekly_wager = money(weekly["wager_rub"] if weekly else 0)
        commission_profile, applied_commission_rate = await commission_profile_for_player(conn, telegram_id)
        volume_tier = resolve_commission_volume_tier(tier_config.commission_volume_tiers, weekly_wager)
        clan_brief = await clan_brief_for_user(conn, telegram_id)

    wager_rub = money(weekly["wager_rub"] if weekly else 0)
    loss_rub = money(weekly["loss_rub"] if weekly else 0)
    cashback_percent = resolve_cashback_percent(tier_config.cashback_volume_tiers, wager_rub)
    estimated_cashback_rub = money(loss_rub * cashback_percent / Decimal("100"))
    week_start = weekly["week_start"] if weekly else None
    next_tier = next_cashback_tier(tier_config.cashback_volume_tiers, wager_rub)
    next_threshold_rub = money(next_tier.min_wager_rub) if next_tier is not None else None
    next_percent = money(next_tier.percent) if next_tier is not None else None
    tier_progress = {
        "wager_rub": _text_money(wager_rub),
        "next_threshold_rub": _text_money(next_threshold_rub) if next_threshold_rub is not None else None,
        "remaining_wager_rub": _text_money(next_threshold_rub - wager_rub) if next_threshold_rub is not None else None,
        "next_cashback_percent": _text_money(next_percent) if next_percent is not None else None,
    }
    prior_cashback = None
    if previous:
        prior_cashback = {
            "week_start": previous["week_start"].isoformat(),
            "loss_rub": _text_money(previous["net_loss_rub"]),
            "cashback_rub": _text_money(previous["cashback_rub"]),
            "cashback_percent": _text_money(previous["cashback_percent"] or 0),
            "status": str(previous["status"]),
        }
    return {
        "telegram_id": telegram_id,
        "identity": {
            "first_name": str(identity["first_name"]) if identity and identity["first_name"] else None,
            "username": str(identity["username"]) if identity and identity["username"] else None,
        },
        "available_rub": _text_money(max(Decimal("0.00"), money(unified - legacy_holds))),
        "wagering": serialize_wagering_progress(wagering),
        "current_week": {
            "week_start": week_start.isoformat() if week_start else None,
            "wager_rub": _text_money(wager_rub),
            "loss_rub": _text_money(loss_rub),
            "tier": _text_money(cashback_percent),
            "progress": tier_progress,
            "cashback_percent": _text_money(cashback_percent),
            "estimated_cashback_rub": _text_money(estimated_cashback_rub),
            "commission_profile": commission_profile,
            "commission_rate": _text_money(applied_commission_rate),
            "commission_active_rate": _text_money(volume_tier.active_rate if volume_tier else applied_commission_rate),
            "commission_complete_rate": _text_money(volume_tier.complete_rate if volume_tier else applied_commission_rate),
        },
        "prior_cashback": prior_cashback,
        "clan": clan_brief,
    }


@router.get("/users/{telegram_id}/avatar")
async def get_player_avatar(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Prefer the uploaded casino avatar, then the cached Telegram photo."""
    _verify_internal_token(x_internal_token)
    from bot_user_avatars import fetch_and_cache_bot_user_avatar, resolve_bot_user_avatar_path
    from casino_player_cosmetics import resolve_cosmetics_avatar_path

    path = resolve_cosmetics_avatar_path(telegram_id)
    if not path:
        path = resolve_bot_user_avatar_path(telegram_id)
    if not path:
        path = await fetch_and_cache_bot_user_avatar(telegram_id)
    if not path:
        raise HTTPException(status_code=404, detail="Avatar not found")
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/users/{telegram_id}/balance", response_model=BalanceResponse)
async def get_player_balance(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        unified = money(await unified_available(conn, telegram_id))
        legacy_holds = money(
            await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)
                FROM casino_balance_holds
                WHERE telegram_id = $1
                  AND status = 'active'
                  AND expires_at > now()
                  AND ledger_order_ref IS NULL
                """,
                telegram_id,
            )
            or 0
        )
    return BalanceResponse(
        telegram_id=telegram_id,
        available_rub=max(Decimal("0.00"), money(unified - legacy_holds)),
    )


@router.get("/users/{telegram_id}/wagering")
async def get_player_wagering(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Прогресс отыгрыша: сколько депозита заперто и сколько ещё нужно поставить.

    remaining_rub — объём ставок. remaining_house_take_rub — плюс казино,
    который ещё нужно набрать комиссией с этого игрока.
    """
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        progress = await wagering_progress(conn, telegram_id)
    return {
        "telegram_id": telegram_id,
        **serialize_wagering_progress(progress),
    }


@router.post("/games/hold")
async def hold_balance(
    body: HoldBalanceRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    game_id = body.game_id.strip()
    hold_id = f"casino-{game_id}-{body.role}"
    amount = money(body.amount_rub)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
    order_ref = casino_ledger_order_ref(hold_id)

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await lock_casino_game(conn, game_id)
            await lock_casino_users(conn, (body.telegram_id,))
            existing = await conn.fetchrow(
                "SELECT * FROM casino_balance_holds WHERE hold_id = $1 FOR UPDATE",
                hold_id,
            )
            if existing:
                if (
                    int(existing["telegram_id"]) != body.telegram_id
                    or str(existing["game_id"]) != game_id
                    or money(existing["amount_rub"]) != amount
                ):
                    raise HTTPException(status_code=409, detail="Existing hold conflicts")
                if existing["status"] != "active" or _utc(existing["expires_at"]) <= datetime.now(timezone.utc):
                    raise HTTPException(status_code=409, detail=f"Hold is {existing['status']}")
                persisted_ref = existing.get("ledger_order_ref") if isinstance(existing, dict) else existing["ledger_order_ref"]
                if persisted_ref:
                    if await unified_hold_amount(conn, body.telegram_id, str(persisted_ref)) != amount:
                        raise HTTPException(status_code=409, detail="Existing hold is not fully backed")
                    return {
                        "success": True,
                        "idempotent": True,
                        "hold_id": hold_id,
                        "telegram_id": body.telegram_id,
                        "amount_rub": _text_money(amount),
                        "expires_at": _utc(existing["expires_at"]).isoformat(),
                        "status": "active",
                    }

            try:
                await reserve_unified_funds(
                    conn,
                    user_id=body.telegram_id,
                    order_ref=order_ref,
                    amount_rub=amount,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Insufficient balance") from exc

            if existing:
                await conn.execute(
                    """
                    UPDATE casino_balance_holds
                    SET ledger_order_ref = $2, expires_at = $3
                    WHERE hold_id = $1
                    """,
                    hold_id,
                    order_ref,
                    expires_at,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO casino_balance_holds (
                        hold_id, telegram_id, game_id, amount_rub,
                        role, ledger_order_ref, status, expires_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                    """,
                    hold_id,
                    body.telegram_id,
                    game_id,
                    amount,
                    body.role,
                    order_ref,
                    expires_at,
                )
    return {
        "success": True,
        "idempotent": False,
        "hold_id": hold_id,
        "telegram_id": body.telegram_id,
        "amount_rub": _text_money(amount),
        "expires_at": expires_at.isoformat(),
        "status": "active",
    }


async def _hold_context(conn, hold_id: str):
    row = await conn.fetchrow(
        "SELECT telegram_id, game_id FROM casino_balance_holds WHERE hold_id = $1",
        hold_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Hold not found")
    return row


@router.post("/games/confirm")
async def confirm_bet(
    body: ConfirmReleaseRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _hold_context(conn, body.hold_id)
            await lock_casino_game(conn, str(context["game_id"]))
            await lock_casino_users(conn, (int(context["telegram_id"]),))
            hold = await conn.fetchrow(
                "SELECT * FROM casino_balance_holds WHERE hold_id = $1 FOR UPDATE",
                body.hold_id,
            )
            if hold["status"] == "confirmed":
                return {"success": True, "idempotent": True, "hold_id": body.hold_id, "status": "confirmed"}
            if hold["status"] != "active":
                raise HTTPException(status_code=409, detail=f"Hold is {hold['status']}")
            if _utc(hold["expires_at"]) <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail="Hold has expired")
            order_ref = hold["ledger_order_ref"]
            if not order_ref:
                raise HTTPException(status_code=409, detail="Hold has no unified balance reserve")
            await confirm_unified_hold(
                conn,
                user_id=int(hold["telegram_id"]),
                order_ref=str(order_ref),
                amount_rub=money(hold["amount_rub"]),
                note=f"Casino stake: {hold['game_id']}",
            )
            await conn.execute(
                "UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now() WHERE hold_id = $1",
                body.hold_id,
            )
    return {"success": True, "idempotent": False, "hold_id": body.hold_id, "status": "confirmed"}


@router.post("/games/release")
async def release_bet(
    body: ConfirmReleaseRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            context = await _hold_context(conn, body.hold_id)
            await lock_casino_game(conn, str(context["game_id"]))
            await lock_casino_users(conn, (int(context["telegram_id"]),))
            hold = await conn.fetchrow(
                "SELECT * FROM casino_balance_holds WHERE hold_id = $1 FOR UPDATE",
                body.hold_id,
            )
            if hold["status"] in {"released", "expired"}:
                return {"success": True, "idempotent": True, "hold_id": body.hold_id, "status": hold["status"]}
            if hold["status"] != "active":
                raise HTTPException(status_code=409, detail=f"Hold is {hold['status']}")
            order_ref = hold["ledger_order_ref"]
            if order_ref:
                await release_unified_hold(
                    conn,
                    user_id=int(hold["telegram_id"]),
                    order_ref=str(order_ref),
                    amount_rub=money(hold["amount_rub"]),
                    note=f"Casino hold released: {hold['game_id']}",
                )
            await conn.execute(
                "UPDATE casino_balance_holds SET status = 'released', released_at = now() WHERE hold_id = $1",
                body.hold_id,
            )
    return {"success": True, "idempotent": False, "hold_id": body.hold_id, "status": "released"}


@router.post("/games/settle")
async def settle_game(
    body: SettlementRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await settle_game_with_conn(conn, body)


@router.post("/deposits/credit")
async def credit_deposit(
    body: DepositCreditRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await credit_deposit_with_conn(conn, body)


@router.post("/deposits/{deal_id}/cancel")
async def cancel_deposit(
    deal_id: int,
    telegram_id: int | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Отменить casino-депозит игрока, пока он не оплачен (awaiting_receipt).

    Отменять можно только собственную неоплаченную заявку игрока: сверяем, что
    сделка — именно casino-депозит и принадлежит переданному telegram_id.
    Оплаченную/зачисленную сделку отменить нельзя → 409.
    """
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            deal = await conn.fetchrow(
                "SELECT id, client_transaction_id, status FROM external_deals WHERE id = $1 FOR UPDATE",
                deal_id,
            )
            if not deal:
                raise HTTPException(status_code=404, detail="Deposit not found")
            client_tx = str(deal["client_transaction_id"] or "").strip()
            if not _CASINO_DEPOSIT_TRANSACTION_RE.fullmatch(client_tx):
                raise HTTPException(status_code=404, detail="Not a casino deposit")
            if telegram_id is not None:
                owner = _telegram_id_from_deposit_transaction_id(deal["client_transaction_id"])
                if owner != int(telegram_id):
                    raise HTTPException(status_code=403, detail="Deposit belongs to another player")
            from external_exchange_service import cancel_external_deal

            try:
                await cancel_external_deal(conn, deal_id)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"success": True, "deal_id": deal_id, "status": "cancelled"}


@router.post("/games/payout")
async def payout_winnings(
    body: PayoutRequest,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Legacy idempotent payout. New games must use /games/settle."""
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await lock_casino_game(conn, body.game_id)
            await lock_casino_users(conn, (body.telegram_id,))
            order_id = casino_operation_ref("payout", body.game_id, str(body.telegram_id))
            existing = await conn.fetchrow(
                "SELECT user_id, amount_rub FROM user_cashback_ledger WHERE order_id = $1",
                order_id,
            )
            if existing:
                if int(existing["user_id"]) != body.telegram_id or money(existing["amount_rub"]) != money(body.amount_rub):
                    raise HTTPException(status_code=409, detail="Existing casino payout conflicts")
                return {
                    "success": True,
                    "idempotent": True,
                    "telegram_id": body.telegram_id,
                    "amount_rub": _text_money(body.amount_rub),
                }
            await _credit_winner(
                conn,
                game_id=body.game_id,
                winner_id=body.telegram_id,
                payout_rub=money(body.amount_rub),
            )
    return {
        "success": True,
        "idempotent": False,
        "telegram_id": body.telegram_id,
        "amount_rub": _text_money(body.amount_rub),
    }


@router.post("/games/{game_id}/commissions")
async def distribute_commissions(
    game_id: int,
    body: EmptyCommissionRequest | None = None,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    """Legacy readback: commission amounts are calculated only by /games/settle."""
    _verify_internal_token(x_internal_token)
    _ = body
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT recipient_type, recipient_id, amount_rub, status
            FROM casino_commission_ledger
            WHERE game_id = $1
            ORDER BY recipient_type
            """,
            game_id,
        )
    if not rows:
        raise HTTPException(status_code=409, detail="Game has not been atomically settled")
    return {
        "success": True,
        "idempotent": True,
        "game_id": game_id,
        "allocations": {
            row["recipient_type"]: {
                "recipient_id": row["recipient_id"],
                "amount_rub": _text_money(row["amount_rub"]),
                "status": row["status"],
            }
            for row in rows
        },
    }


class ClanCreateInternal(StrictModel):
    telegram_id: int = Field(gt=0)
    tag: str
    name: str


class ClanJoinInternal(StrictModel):
    telegram_id: int = Field(gt=0)
    code: str


class ClanActorInternal(StrictModel):
    telegram_id: int = Field(gt=0)


class ClanKickInternal(StrictModel):
    telegram_id: int = Field(gt=0)
    target_id: int = Field(gt=0)


class ClanTransferInternal(StrictModel):
    telegram_id: int = Field(gt=0)
    target_id: int = Field(gt=0)


@router.get("/users/{telegram_id}/clan")
async def internal_my_clan(
    telegram_id: int,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await my_clan(conn, telegram_id)


@router.get("/clans/top")
async def internal_clan_top(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await clans_list_top(conn, limit=10)


@router.get("/clans/{tag}")
async def internal_clan_page(
    tag: str,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await clan_snapshot(conn, tag=tag)


@router.post("/clans")
async def internal_create_clan(
    body: ClanCreateInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await create_clan(conn, user_id=body.telegram_id, tag=body.tag, name=body.name)
    return {"success": True, "clan": clan}


@router.post("/clans/join")
async def internal_join_clan(
    body: ClanJoinInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await join_clan(conn, user_id=body.telegram_id, code=body.code)
    return {"success": True, "clan": clan}


@router.post("/clans/leave")
async def internal_leave_clan(
    body: ClanActorInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await leave_clan(conn, user_id=body.telegram_id)


@router.post("/clans/kick")
async def internal_kick_clan(
    body: ClanKickInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await kick_member(conn, owner_id=body.telegram_id, target_id=body.target_id)
    return {"success": True, "clan": clan}


@router.post("/clans/invite")
async def internal_rotate_invite(
    body: ClanActorInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await rotate_invite(conn, owner_id=body.telegram_id)
    return {"success": True, "clan": clan}


@router.post("/clans/transfer")
async def internal_transfer_clan(
    body: ClanTransferInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            clan = await transfer_owner(conn, owner_id=body.telegram_id, target_id=body.target_id)
    return {"success": True, "clan": clan}


@router.post("/clans/disband")
async def internal_disband_clan(
    body: ClanActorInternal,
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await disband_clan(conn, actor_id=body.telegram_id)


@router.get("/settings", response_model=CasinoSettingsResponse)
async def get_casino_settings(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
):
    _verify_internal_token(x_internal_token)
    pool = await get_pool()
    async with pool.acquire() as conn:
        casino_settings = await load_casino_settings(conn)
    return CasinoSettingsResponse(**casino_settings.public_dict())

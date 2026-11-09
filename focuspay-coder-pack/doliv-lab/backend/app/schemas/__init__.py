from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import DolivRequestStatus, RequisiteStatus, UserRole


def _basename(v: str) -> str:
    """Return only the filename portion of a server path."""
    return Path(v).name if v else v


def _validate_password_strength(v: str) -> str:
    if len(v) < 12:
        raise ValueError("Password must be at least 12 characters")
    if not re.search(r"[A-Za-z]", v):
        raise ValueError("Password must contain a letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain a digit")
    return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    login: str
    password: str

    @field_validator("login", "password", mode="before")
    @classmethod
    def strip_credentials(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    full_name: str
    role: UserRole
    is_active: bool
    last_login: datetime | None = None
    profit_percent: Decimal | None = None
    doliv_salary_usdt: Decimal | None = None
    teamlead_percent: Decimal | None = None
    teamlead_id: int | None = None
    deposit_exempt: bool = False
    created_at: datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    message: str
    kind: str
    link: str | None
    is_read: bool
    created_at: datetime


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=128)
    role: UserRole
    profit_percent: Decimal | None = Field(default=None, ge=0)
    doliv_salary_usdt: Decimal | None = Field(default=None, ge=0)
    teamlead_percent: Decimal | None = Field(default=None, ge=0)
    teamlead_id: int | None = None
    deposit_exempt: bool = False

    @field_validator("login", "full_name", mode="before")
    @classmethod
    def strip_user_fields(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password", mode="before")
    @classmethod
    def strip_and_validate_password(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


class UserUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=12)
    role: UserRole | None = None
    is_active: bool | None = None
    profit_percent: Decimal | None = Field(default=None, ge=0)
    doliv_salary_usdt: Decimal | None = Field(default=None, ge=0)
    teamlead_percent: Decimal | None = Field(default=None, ge=0)
    teamlead_id: int | None = None
    deposit_exempt: bool | None = None

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_optional_fields(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password", mode="before")
    @classmethod
    def strip_and_validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


class TeamleadTraderCreate(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=128)
    profit_percent: Decimal = Field(ge=0)

    @field_validator("login", "full_name", mode="before")
    @classmethod
    def strip_tl_trader_fields(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password", mode="before")
    @classmethod
    def strip_and_validate_tl_password(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


class TeamleadTraderUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=128)
    profit_percent: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_tl_update_name(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v


class TeamleadTraderRow(BaseModel):
    id: int
    login: str
    full_name: str
    is_active: bool
    profit_percent: Decimal | None = None
    teamlead_keep_percent: Decimal | None = None
    deposit_exempt: bool = False
    total_float_rub: Decimal
    token_available: Decimal | None = None
    token_held: Decimal | None = None
    commissions_usdt: Decimal | None = None


class TeamleadMeResponse(BaseModel):
    id: int
    login: str
    full_name: str
    teamlead_percent: Decimal | None = None  # pool %
    pool_percent: Decimal | None = None
    max_trader_percent: Decimal | None = None


class TeamleadSummaryResponse(BaseModel):
    teamlead_percent: Decimal | None = None  # pool %
    pool_percent: Decimal | None = None
    max_trader_percent: Decimal | None = None
    traders_count: int
    token_balance: Decimal | None = None
    token_available: Decimal | None = None
    token_held: Decimal | None = None
    credits_usdt: Decimal = Decimal("0")
    team_float_rub: Decimal = Decimal("0")


class DolivRequestAssign(BaseModel):
    dolivshchik_id: int


class RequisiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    total_amount: Decimal = Field(gt=0)
    target_rate: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=2000)


class RequisiteUpdate(BaseModel):
    name: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


class ZalivResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    rate: Decimal
    profit_percent: Decimal
    receipt_path: str
    created_at: datetime

    @field_validator("receipt_path", mode="before")
    @classmethod
    def _strip_path(cls, v: str) -> str:
        return _basename(v)


class RequisiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trader_id: int
    trader_name: str | None = None
    name: str
    total_amount: Decimal
    target_rate: Decimal
    comment: str | None
    status: RequisiteStatus
    float_rub: Decimal = Decimal("0")
    hold_usdt: Decimal | None = None
    work_token_id: int | None = None
    created_at: datetime
    updated_at: datetime


class FakeCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requisite_id: int
    amount_rub: Decimal
    rate: Decimal
    amount_usdt: Decimal
    comment: str | None
    file_path: str | None
    operation_date: date
    created_by_id: int
    created_by_name: str | None = None
    created_at: datetime


class FakeCheckAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    requisite_id: int
    fake_check_id: int | None
    amount_rub: Decimal | None
    rate: Decimal | None
    amount_usdt: Decimal | None
    comment: str | None
    file_path: str | None
    user_id: int
    user_name: str | None = None
    created_at: datetime


class FakeCheckTopRequisite(BaseModel):
    requisite_id: int
    name: str
    loss_usdt: Decimal
    count: int


class FakeCheckTopTrader(BaseModel):
    trader_id: int
    name: str
    loss_usdt: Decimal
    count: int


class AnalyticsChartPoint(BaseModel):
    label: str
    profit: float
    doliv_loss: float
    fake_check_loss: float
    net_profit: float


class RequisiteDetail(RequisiteResponse):
    zalivs: list[ZalivResponse] = []
    zaliv_total: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    avg_rate: Decimal | None = None
    current_profit: Decimal = Decimal("0")
    trader_name: str | None = None
    fake_checks: list[FakeCheckResponse] = []
    gross_profit: Decimal = Decimal("0")
    fake_check_loss: Decimal = Decimal("0")
    doliv_loss: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")


class DolivRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requisite_id: int
    required_amount: Decimal
    status: DolivRequestStatus
    sent_at: datetime
    assigned_dolivshchik_id: int | None
    assigned_dolivshchik_name: str | None = None
    requisite_name: str | None = None
    target_rate: Decimal | None = None
    trader_name: str | None = None
    zaliv_total: Decimal | None = None


class AppSettingsResponse(BaseModel):
    currency: str
    timezone: str
    default_profit_percent: Decimal
    trader_salary_percent: Decimal
    doliv_salary_percent: Decimal
    payout_bonus_percent: Decimal = Decimal("1")
    default_teamlead_percent: Decimal = Decimal("12")
    withdraw_fee_usdt: Decimal = Decimal("3")
    date_format: str
    receipt_formats: list[str]
    max_upload_mb: int


class AppSettingsUpdate(BaseModel):
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    default_profit_percent: Decimal | None = Field(default=None, ge=0)
    trader_salary_percent: Decimal | None = Field(default=None, ge=0, le=100)
    doliv_salary_percent: Decimal | None = Field(default=None, ge=0)
    payout_bonus_percent: Decimal | None = Field(default=None, ge=0)
    default_teamlead_percent: Decimal | None = Field(default=None, ge=0)
    withdraw_fee_usdt: Decimal | None = Field(default=None, ge=0)
    date_format: str | None = Field(default=None, min_length=1, max_length=32)
    receipt_formats: list[str] | None = None
    max_upload_mb: int | None = Field(default=None, gt=0, le=100)


class RolePermissionsUpdate(BaseModel):
    permissions: dict[str, list[str]]


class DolivResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    rate: Decimal
    receipt_path: str
    completed_at: datetime
    dolivshchik_name: str | None = None

    @field_validator("receipt_path", mode="before")
    @classmethod
    def _strip_path(cls, v: str) -> str:
        return _basename(v)


class AdminDolivResponse(BaseModel):
    id: int
    request_id: int
    requisite_id: int
    requisite_name: str
    trader_name: str
    dolivshchik_name: str
    amount: Decimal
    rate: Decimal
    receipt_path: str
    status: DolivRequestStatus
    completed_at: datetime

    @field_validator("receipt_path", mode="before")
    @classmethod
    def _strip_path(cls, v: str) -> str:
        return _basename(v)


class ReceiptResponse(BaseModel):
    id: int
    type: str
    requisite_id: int
    requisite_name: str
    uploader_name: str
    amount: Decimal
    rate: Decimal
    receipt_path: str
    created_at: datetime

    @field_validator("receipt_path", mode="before")
    @classmethod
    def _strip_path(cls, v: str) -> str:
        return _basename(v)


class DealResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_turnover: Decimal
    avg_rate: Decimal
    doliv_amount: Decimal
    doliv_rate: Decimal = Decimal("0")
    zaliv_profit: Decimal
    doliv_profit_loss: Decimal
    final_profit: Decimal
    merged_receipt_path: str | None
    calculated_at: datetime

    @field_validator("merged_receipt_path", mode="before")
    @classmethod
    def _strip_merged_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _basename(v)


class StatsOverview(BaseModel):
    total_turnover: Decimal
    total_turnover_usdt: Decimal = Decimal("0")
    total_profit: Decimal
    requisites_count: int
    dolivs_count: int
    profit_by_day: list[dict[str, Any]]
    profit_by_week: list[dict[str, Any]] = []
    profit_by_month: list[dict[str, Any]] = []
    fake_check_count: int = 0
    fake_check_loss_rub: Decimal = Decimal("0")
    fake_check_loss_usdt: Decimal = Decimal("0")
    fake_check_avg_rate: Decimal = Decimal("0")
    fake_check_top_requisites: list[FakeCheckTopRequisite] = []
    fake_check_top_traders: list[FakeCheckTopTrader] = []


class TraderStats(BaseModel):
    user_id: int
    login: str = ""
    full_name: str
    requisites_count: int
    total_turnover: Decimal
    total_turnover_usdt: Decimal = Decimal("0")
    total_profit: Decimal
    avg_profit_per_requisite: Decimal
    profit_day: Decimal
    profit_week: Decimal
    profit_month: Decimal
    active_profit: Decimal = Decimal("0")


class DolivshchikStats(BaseModel):
    user_id: int
    login: str = ""
    full_name: str
    dolivs_count: int
    total_doliv_amount: Decimal
    total_doliv_amount_usdt: Decimal = Decimal("0")
    avg_doliv_rate: Decimal
    total_processed: Decimal
    total_doliv_loss: Decimal = Decimal("0")
    salary_per_doliv_usdt: Decimal = Decimal("0")
    dolivs_today: int = 0
    earnings_today: Decimal = Decimal("0")


class AdminCreate(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12)
    full_name: str = Field(min_length=1, max_length=128)

    @field_validator("login", "full_name", mode="before")
    @classmethod
    def strip_admin_fields(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password", mode="before")
    @classmethod
    def strip_and_validate_password(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


class AdminUpdate(BaseModel):
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=12)
    is_active: bool | None = None

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_admin_optional(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("password", mode="before")
    @classmethod
    def strip_and_validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


class OwnerAdminSummary(BaseModel):
    total: int
    active: int
    inactive: int
    admins: list[UserResponse]


class OwnerDashboardResponse(BaseModel):
    stats: dict[str, Any]
    admin_summary: OwnerAdminSummary


class WorkTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    owner_id: int | None = None
    deposit_exempt: bool = False
    member_user_ids: list[int] = Field(default_factory=list)


class WorkTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_id: int | None
    deposit_exempt: bool
    is_active: bool
    created_at: datetime
    balance: Decimal | None = None
    held: Decimal | None = None
    available: Decimal | None = None
    member_ids: list[int] = Field(default_factory=list)
    withdraw_fee_usdt: Decimal | None = None


class TokenAmountRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=128)


class TraderWalletAmountRequest(BaseModel):
    amount_usdt: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=128)


class TokenLedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_token_id: int
    entry_type: str
    amount: Decimal
    idempotency_key: str
    requisite_id: int | None
    actor_id: int | None
    comment: str | None
    created_at: datetime


class FloatSettleRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)


class PayoutRequest(BaseModel):
    amount_usdt: Decimal = Field(gt=0)
    requisite_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ChargebackRequest(BaseModel):
    amount_usdt: Decimal = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: str = "read:balance,read:float,read:holds"


class ApiKeyResponse(BaseModel):
    id: int
    work_token_id: int
    name: str
    key_prefix: str
    scopes: str
    is_active: bool
    created_at: datetime
    raw_key: str | None = None


class RateResponse(BaseModel):
    rate: Decimal
    source: str


class WorkingRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rate: Decimal
    mode: str
    valid_until: datetime | None = None
    comment: str | None = None
    set_by_id: int | None = None
    created_at: datetime


class WorkingRateSetRequest(BaseModel):
    rate: Decimal = Field(gt=0)
    mode: str = "manual"  # manual | rapira_snap | fixed
    valid_until: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)


class WorkingRateFromRapiraRequest(BaseModel):
    valid_until: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)


class PaymentBand(BaseModel):
    min_rub: Decimal = Field(gt=0)
    max_rub: Decimal = Field(gt=0)


class TraderCardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    last4: str | None = Field(default=None, max_length=8)
    bank: str | None = Field(default=None, max_length=64)
    status: str = "active"
    purchase_cost_rub: Decimal = Field(default=Decimal("0"), ge=0)
    linked_requisite_id: int | None = None
    notes: str | None = Field(default=None, max_length=2000)
    recipient_name: str | None = Field(default=None, max_length=128)
    card_number: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    channel: str = "c2c"  # c2c | sbp
    daily_limit_rub: Decimal | None = Field(default=None, gt=0)
    min_payment_rub: Decimal | None = Field(default=None, gt=0)
    max_payment_rub: Decimal | None = Field(default=None, gt=0)
    payment_bands: list[PaymentBand] | None = None
    # If purchase_cost_rub > 0, optionally auto-create expense
    record_purchase_expense: bool = True
    rate: Decimal | None = Field(default=None, gt=0)
    # Card-first: open accept session immediately (legacy alias of daily_limit)
    accept_limit_rub: Decimal | None = Field(default=None, gt=0)
    target_rate: Decimal | None = Field(default=None, gt=0)  # ignored — office rate
    go_online: bool = False


class TraderCardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    last4: str | None = Field(default=None, max_length=8)
    bank: str | None = Field(default=None, max_length=64)
    status: str | None = None
    purchase_cost_rub: Decimal | None = Field(default=None, ge=0)
    linked_requisite_id: int | None = None
    notes: str | None = Field(default=None, max_length=2000)
    recipient_name: str | None = Field(default=None, max_length=128)
    card_number: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    channel: str | None = None
    daily_limit_rub: Decimal | None = Field(default=None, gt=0)
    min_payment_rub: Decimal | None = Field(default=None, gt=0)
    max_payment_rub: Decimal | None = Field(default=None, gt=0)
    payment_bands: list[PaymentBand] | None = None
    accept_limit_rub: Decimal | None = Field(default=None, gt=0)
    target_rate: Decimal | None = Field(default=None, gt=0)  # ignored on go-online


class AdminCardTrafficUpdate(BaseModel):
    """Admin-only audience filter. Omitted fields stay; explicit null clears the bound."""

    traffic_min_orders: int | None = Field(default=None, ge=0)
    traffic_max_orders: int | None = Field(default=None, ge=0)
    traffic_min_volume_rub: Decimal | None = Field(default=None, ge=0)
    traffic_max_volume_rub: Decimal | None = Field(default=None, ge=0)


class TraderCardGoOnline(BaseModel):
    # Optional: defaults to card.daily_limit_rub / accept_limit_rub
    accept_limit_rub: Decimal | None = Field(default=None, gt=0)
    target_rate: Decimal | None = Field(default=None, gt=0)  # ignored — office working rate
    comment: str | None = Field(default=None, max_length=2000)


class TraderCardAccepting(BaseModel):
    enabled: bool


class TraderCardBulkRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    action: str  # enable | disable | set_daily_limit | set_status
    value: str | None = None


class TraderCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trader_id: int
    name: str
    last4: str | None
    bank: str | None
    status: str
    purchase_cost_rub: Decimal
    recipient_name: str | None = None
    card_number: str | None = None
    phone: str | None = None
    channel: str = "c2c"
    daily_limit_rub: Decimal | None = None
    min_payment_rub: Decimal | None = None
    max_payment_rub: Decimal | None = None
    payment_bands: list[PaymentBand] | None = None
    accept_limit_rub: Decimal | None = None
    target_rate: Decimal | None = None
    linked_requisite_id: int | None
    notes: str | None
    expenses_rub: Decimal = Decimal("0")
    expenses_usdt: Decimal = Decimal("0")
    session_id: int | None = None
    session_status: str | None = None
    session_total_rub: Decimal | None = None
    session_remaining_rub: Decimal | None = None
    session_hold_usdt: Decimal | None = None
    session_float_rub: Decimal | None = None
    accepting_enabled: bool = False
    paused_at: datetime | None = None
    received_today_rub: Decimal = Decimal("0")
    daily_remaining_rub: Decimal | None = None
    accepting: bool = False
    not_accepting_reason: str | None = None
    traffic_min_orders: int | None = None
    traffic_max_orders: int | None = None
    traffic_min_volume_rub: Decimal | None = None
    traffic_max_volume_rub: Decimal | None = None
    created_at: datetime
    updated_at: datetime


class TraderCardListResponse(BaseModel):
    items: list[TraderCardResponse]
    total: int


class TraderExpenseCreate(BaseModel):
    category: str
    amount_rub: Decimal = Field(gt=0)
    rate: Decimal | None = Field(default=None, gt=0)
    card_id: int | None = None
    requisite_id: int | None = None
    comment: str | None = Field(default=None, max_length=2000)
    trader_id: int | None = None  # admin/teamlead may set


class TraderExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trader_id: int
    category: str
    amount_rub: Decimal
    rate: Decimal
    amount_usdt: Decimal
    card_id: int | None
    requisite_id: int | None
    comment: str | None
    actor_id: int | None
    debited: bool
    created_at: datetime


class DisplayCurrencyUpdate(BaseModel):
    display_currency: str = Field(pattern="^(RUB|USDT)$")


class TraderNetSummary(BaseModel):
    commissions_usdt: Decimal
    expenses_usdt: Decimal
    expenses_rub: Decimal
    net_usdt: Decimal
    display_currency: str


class WalletRequestCreate(BaseModel):
    kind: str = Field(pattern="^(deposit|withdraw)$")
    amount_usdt: Decimal = Field(gt=0)
    network: str = "usdt_trc20"
    address: str | None = Field(default=None, max_length=256)
    comment: str | None = Field(default=None, max_length=500)


class WalletRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    kind: str
    amount_usdt: Decimal
    network: str
    address: str | None
    fee_usdt: Decimal
    status: str
    comment: str | None
    admin_comment: str | None
    created_at: datetime
    resolved_at: datetime | None = None


class WalletRequestResolve(BaseModel):
    approve: bool
    admin_comment: str | None = Field(default=None, max_length=500)


class PayoutJobCreate(BaseModel):
    amount_rub: Decimal = Field(gt=0)
    pay_method: str = Field(default="sbp", pattern="^(sbp|c2c)$")
    requisites: dict | None = None
    source: str = "manual"
    external_ref: str | None = Field(default=None, max_length=128)
    ttl_minutes: int = Field(default=15, ge=1, le=120)


class PayoutClaimCreate(BaseModel):
    amount_rub: Decimal = Field(gt=0)


class PayoutClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    trader_id: int
    amount_rub: Decimal
    status: str
    created_at: datetime
    paid_at: datetime | None = None


class PayoutJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_rub: Decimal
    remaining_rub: Decimal
    pay_method: str
    requisites: dict | None
    source: str
    external_ref: str | None
    status: str
    claim_deadline: datetime
    created_at: datetime
    claims: list[PayoutClaimResponse] = Field(default_factory=list)


class MerchantPartnerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    callback_url_default: str | None = Field(default=None, max_length=512)


class MerchantPartnerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    callback_url_default: str | None = Field(default=None, max_length=512)


class MerchantPartnerResponse(BaseModel):
    id: int
    name: str
    api_key: str
    secret: str | None = None
    secret_hint: str
    is_active: bool
    callback_url_default: str | None = None
    created_at: datetime


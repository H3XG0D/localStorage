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
            return None
        if isinstance(v, str):
            v = v.strip()
        return _validate_password_strength(v)


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
    name: str
    total_amount: Decimal
    target_rate: Decimal
    comment: str | None
    status: RequisiteStatus
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
    date_format: str
    receipt_formats: list[str]
    max_upload_mb: int


class AppSettingsUpdate(BaseModel):
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    default_profit_percent: Decimal | None = Field(default=None, ge=0)
    trader_salary_percent: Decimal | None = Field(default=None, ge=0, le=100)
    doliv_salary_percent: Decimal | None = Field(default=None, ge=0)
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

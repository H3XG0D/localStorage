import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    trader = "trader"
    dolivshchik = "dolivshchik"


class RequisiteStatus(str, enum.Enum):
    active = "active"
    in_work = "in_work"
    awaiting_doliv = "awaiting_doliv"
    doliv_in_progress = "doliv_in_progress"
    closed = "closed"
    archive = "archive"


class DolivRequestStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class RevokedToken(Base):
    """Stores JWTs that have been explicitly logged out before expiry."""

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginFailure(Base):
    """Failed login attempts for DB-backed rate limiting."""

    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate_key: Mapped[str] = mapped_column(String(128), index=True)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profit_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    doliv_salary_usdt: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisites: Mapped[list["Requisite"]] = relationship(back_populates="trader")
    dolivs: Mapped[list["Doliv"]] = relationship(back_populates="dolivshchik")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Requisite(Base):
    __tablename__ = "requisites"

    id: Mapped[int] = mapped_column(primary_key=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(128))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    target_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequisiteStatus] = mapped_column(
        Enum(RequisiteStatus), default=RequisiteStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    trader: Mapped["User"] = relationship(back_populates="requisites")
    zalivs: Mapped[list["Zaliv"]] = relationship(back_populates="requisite", cascade="all, delete-orphan")
    doliv_requests: Mapped[list["DolivRequest"]] = relationship(
        back_populates="requisite", cascade="all, delete-orphan"
    )
    deal_result: Mapped["DealResult | None"] = relationship(
        back_populates="requisite", uselist=False, cascade="all, delete-orphan"
    )
    fake_checks: Mapped[list["FakeCheck"]] = relationship(back_populates="requisite", cascade="all, delete-orphan")
    fake_check_audit_logs: Mapped[list["FakeCheckAuditLog"]] = relationship(
        back_populates="requisite", cascade="all, delete-orphan"
    )


class Zaliv(Base):
    __tablename__ = "zalivs"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    profit_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    receipt_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisite: Mapped["Requisite"] = relationship(back_populates="zalivs")


class DolivRequest(Base):
    __tablename__ = "doliv_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"))
    required_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[DolivRequestStatus] = mapped_column(
        Enum(DolivRequestStatus), default=DolivRequestStatus.pending
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    assigned_dolivshchik_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    requisite: Mapped["Requisite"] = relationship(back_populates="doliv_requests")
    assigned_dolivshchik: Mapped["User | None"] = relationship(foreign_keys=[assigned_dolivshchik_id])
    doliv: Mapped["Doliv | None"] = relationship(back_populates="request", uselist=False)


class Doliv(Base):
    __tablename__ = "dolivs"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("doliv_requests.id"), unique=True)
    dolivshchik_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    receipt_path: Mapped[str] = mapped_column(String(512))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    request: Mapped["DolivRequest"] = relationship(back_populates="doliv")
    dolivshchik: Mapped["User"] = relationship(back_populates="dolivs")


class DealResult(Base):
    __tablename__ = "deal_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"), unique=True)
    total_turnover: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    turnover_usdt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    avg_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    doliv_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    doliv_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"))
    zaliv_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    doliv_profit_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    final_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    merged_receipt_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisite: Mapped["Requisite"] = relationship(back_populates="deal_result")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    default_profit_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("12"))
    trader_salary_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("20"))
    doliv_salary_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1"))
    date_format: Mapped[str] = mapped_column(String(32), default="DD.MM.YYYY")
    receipt_formats: Mapped[str] = mapped_column(String(128), default="JPG,PNG,PDF")
    max_upload_mb: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="info")
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="notifications")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    section: Mapped[str] = mapped_column(String(64), index=True)
    actions: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FakeCheck(Base):
    __tablename__ = "fake_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"))
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operation_date: Mapped[date] = mapped_column(Date)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisite: Mapped["Requisite"] = relationship(back_populates="fake_checks")
    created_by: Mapped["User"] = relationship()


class FakeCheckAuditLog(Base):
    __tablename__ = "fake_check_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(16))
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"))
    fake_check_id: Mapped[int | None] = mapped_column(ForeignKey("fake_checks.id"), nullable=True)
    amount_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    amount_usdt: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisite: Mapped["Requisite"] = relationship(back_populates="fake_check_audit_logs")
    user: Mapped["User"] = relationship()

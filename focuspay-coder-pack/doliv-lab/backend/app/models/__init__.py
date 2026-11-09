import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    trader = "trader"
    dolivshchik = "dolivshchik"
    teamlead = "teamlead"


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


class TokenLedgerType(str, enum.Enum):
    deposit = "deposit"
    hold = "hold"
    release = "release"
    credit = "credit"
    debit = "debit"
    withdraw = "withdraw"
    payout_bonus = "payout_bonus"


class FloatLedgerType(str, enum.Enum):
    confirm = "confirm"
    settle = "settle"
    adjust = "adjust"
    close = "close"


class CardStatus(str, enum.Enum):
    active = "active"
    warming = "warming"
    blocked = "blocked"
    archived = "archived"


class ExpenseCategory(str, enum.Enum):
    card_purchase = "card_purchase"
    warm = "warm"
    block_loss = "block_loss"
    other = "other"


class WorkingRateMode(str, enum.Enum):
    manual = "manual"
    rapira_snap = "rapira_snap"
    fixed = "fixed"


class PaymentChannel(str, enum.Enum):
    c2c = "c2c"
    sbp = "sbp"


class WalletRequestKind(str, enum.Enum):
    deposit = "deposit"
    withdraw = "withdraw"


class WalletRequestStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    paid = "paid"


class CryptoNetwork(str, enum.Enum):
    usdt_trc20 = "usdt_trc20"
    btc = "btc"
    ltc = "ltc"
    other = "other"


class PayoutJobStatus(str, enum.Enum):
    open = "open"
    partial = "partial"
    done = "done"
    expired = "expired"
    cancelled = "cancelled"


class PayoutClaimStatus(str, enum.Enum):
    claimed = "claimed"
    paid = "paid"
    cancelled = "cancelled"


class PayoutPayMethod(str, enum.Enum):
    sbp = "sbp"
    c2c = "c2c"


class MerchantOrderStatus(str, enum.Enum):
    pending = "pending"
    issued = "issued"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


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
    teamlead_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    teamlead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deposit_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    display_currency: Mapped[str] = mapped_column(String(8), default="RUB", server_default="RUB")
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisites: Mapped[list["Requisite"]] = relationship(back_populates="trader")
    dolivs: Mapped[list["Doliv"]] = relationship(back_populates="dolivshchik")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    teamlead: Mapped["User | None"] = relationship(remote_side="User.id", foreign_keys=[teamlead_id])
    cards: Mapped[list["TraderCard"]] = relationship(
        back_populates="trader", foreign_keys="TraderCard.trader_id", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["TraderExpense"]] = relationship(
        back_populates="trader", foreign_keys="TraderExpense.trader_id", cascade="all, delete-orphan"
    )


class Requisite(Base):
    __tablename__ = "requisites"

    id: Mapped[int] = mapped_column(primary_key=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("trader_cards.id", use_alter=True, name="fk_requisites_card_id"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    target_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequisiteStatus] = mapped_column(
        Enum(RequisiteStatus), default=RequisiteStatus.active
    )
    float_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    hold_usdt: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    work_token_id: Mapped[int | None] = mapped_column(ForeignKey("work_tokens.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    trader: Mapped["User"] = relationship(back_populates="requisites")
    work_token: Mapped["WorkToken | None"] = relationship(back_populates="requisites")
    card: Mapped["TraderCard | None"] = relationship(
        back_populates="sessions", foreign_keys=[card_id]
    )
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
    float_entries: Mapped[list["RequisiteFloatLedger"]] = relationship(
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
    payout_bonus_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("1"), server_default="1")
    default_teamlead_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("12"), server_default="12")
    withdraw_fee_usdt: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("3"), server_default="3")
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


class WorkToken(Base):
    """Shared USDT working-deposit ledger that traders operate under."""

    __tablename__ = "work_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deposit_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id])
    members: Mapped[list["TokenMember"]] = relationship(back_populates="work_token", cascade="all, delete-orphan")
    ledger: Mapped[list["TokenLedger"]] = relationship(back_populates="work_token", cascade="all, delete-orphan")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="work_token", cascade="all, delete-orphan")
    requisites: Mapped[list["Requisite"]] = relationship(back_populates="work_token")


class TokenMember(Base):
    __tablename__ = "token_members"
    __table_args__ = (UniqueConstraint("work_token_id", "user_id", name="uq_token_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_token_id: Mapped[int] = mapped_column(ForeignKey("work_tokens.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    work_token: Mapped["WorkToken"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()


class TokenLedger(Base):
    __tablename__ = "token_ledger"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_token_ledger_idem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_token_id: Mapped[int] = mapped_column(ForeignKey("work_tokens.id"), index=True)
    entry_type: Mapped[TokenLedgerType] = mapped_column(Enum(TokenLedgerType), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    requisite_id: Mapped[int | None] = mapped_column(ForeignKey("requisites.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    work_token: Mapped["WorkToken"] = relationship(back_populates="ledger")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_token_id: Mapped[int] = mapped_column(ForeignKey("work_tokens.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    scopes: Mapped[str] = mapped_column(String(255), default="read:balance,read:float,read:holds")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    work_token: Mapped["WorkToken"] = relationship(back_populates="api_keys")


class RequisiteFloatLedger(Base):
    __tablename__ = "requisite_float_ledger"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_float_ledger_idem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    requisite_id: Mapped[int] = mapped_column(ForeignKey("requisites.id"), index=True)
    entry_type: Mapped[FloatLedgerType] = mapped_column(Enum(FloatLedgerType), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    zaliv_id: Mapped[int | None] = mapped_column(ForeignKey("zalivs.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    requisite: Mapped["Requisite"] = relationship(back_populates="float_entries")


class TraderCard(Base):
    """Trader's physical/virtual card inventory — primary work surface."""

    __tablename__ = "trader_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    bank: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[CardStatus] = mapped_column(Enum(CardStatus), default=CardStatus.active)
    purchase_cost_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    accept_limit_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    daily_limit_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    min_payment_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    max_payment_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_bands: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recipient_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    card_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel: Mapped[str] = mapped_column(String(8), default="c2c", server_default="c2c")
    target_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    linked_requisite_id: Mapped[int | None] = mapped_column(ForeignKey("requisites.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traffic_min_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic_max_orders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic_min_volume_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    traffic_max_volume_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    trader: Mapped["User"] = relationship(back_populates="cards", foreign_keys=[trader_id])
    expenses: Mapped[list["TraderExpense"]] = relationship(back_populates="card")
    sessions: Mapped[list["Requisite"]] = relationship(
        back_populates="card", foreign_keys="Requisite.card_id"
    )

class TraderExpense(Base):
    """Trader operating costs: card buy, warm, block loss, other."""

    __tablename__ = "trader_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), index=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("trader_cards.id"), nullable=True)
    requisite_id: Mapped[int | None] = mapped_column(ForeignKey("requisites.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    debited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trader: Mapped["User"] = relationship(back_populates="expenses", foreign_keys=[trader_id])
    card: Mapped["TraderCard | None"] = relationship(back_populates="expenses", foreign_keys=[card_id])


class WorkingRate(Base):
    """Office working FX rate — admin-owned snapshot (manual / Rapira snap / fixed until)."""

    __tablename__ = "working_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    mode: Mapped[WorkingRateMode] = mapped_column(Enum(WorkingRateMode), default=WorkingRateMode.manual)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    set_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WalletRequest(Base):
    """Trader deposit/withdraw request — admin must approve (no self-credit)."""

    __tablename__ = "wallet_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    work_token_id: Mapped[int | None] = mapped_column(ForeignKey("work_tokens.id"), nullable=True)
    kind: Mapped[WalletRequestKind] = mapped_column(Enum(WalletRequestKind), index=True)
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    network: Mapped[CryptoNetwork] = mapped_column(Enum(CryptoNetwork), default=CryptoNetwork.usdt_trc20)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fee_usdt: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"), server_default="0")
    status: Mapped[WalletRequestStatus] = mapped_column(
        Enum(WalletRequestStatus), default=WalletRequestStatus.pending, index=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PayoutJob(Base):
    """RUB payout to card/SBP — traders claim within deadline (FocusPay bridge / manual)."""

    __tablename__ = "payout_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    remaining_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    pay_method: Mapped[PayoutPayMethod] = mapped_column(Enum(PayoutPayMethod), default=PayoutPayMethod.sbp)
    requisites: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # sell|freelancer|manual
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[PayoutJobStatus] = mapped_column(Enum(PayoutJobStatus), default=PayoutJobStatus.open, index=True)
    claim_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claims: Mapped[list["PayoutClaim"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class PayoutClaim(Base):
    __tablename__ = "payout_claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("payout_jobs.id"), index=True)
    trader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[PayoutClaimStatus] = mapped_column(
        Enum(PayoutClaimStatus), default=PayoutClaimStatus.claimed, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["PayoutJob"] = relationship(back_populates="claims")


class BridgeServiceKey(Base):
    """Service API key for FocusPay ↔ Doliv bridge (not trader JWT)."""

    __tablename__ = "bridge_service_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MerchantPartner(Base):
    """Partner credentials for Merchant payin API (Payfast-compatible shape)."""

    __tablename__ = "merchant_partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret: Mapped[str] = mapped_column(String(128), default="")  # lab: needed for HMAC verify
    secret_hash: Mapped[str] = mapped_column(String(128))
    secret_hint: Mapped[str] = mapped_column(String(16), default="")
    callback_url_default: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["MerchantOrder"]] = relationship(back_populates="partner")


class MerchantOrder(Base):
    __tablename__ = "merchant_orders"
    __table_args__ = (UniqueConstraint("partner_id", "client_transaction_id", name="uq_merchant_client_tx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("merchant_partners.id"), index=True)
    client_transaction_id: Mapped[str] = mapped_column(String(128), index=True)
    amount_rub: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sub_token: Mapped[str] = mapped_column(String(32), default="SBPRUB")
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[MerchantOrderStatus] = mapped_column(
        Enum(MerchantOrderStatus), default=MerchantOrderStatus.pending, index=True
    )
    card_id: Mapped[int | None] = mapped_column(ForeignKey("trader_cards.id"), nullable=True)
    requisite_id: Mapped[int | None] = mapped_column(ForeignKey("requisites.id"), nullable=True)
    zaliv_id: Mapped[int | None] = mapped_column(ForeignKey("zalivs.id"), nullable=True)
    bill: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    partner: Mapped["MerchantPartner"] = relationship(back_populates="orders")

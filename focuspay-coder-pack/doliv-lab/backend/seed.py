import asyncio
import hashlib
from decimal import Decimal

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.config import settings
from app.core.database import async_session, engine, Base
from app.models import (
    AppSettings,
    BridgeServiceKey,
    CardStatus,
    MerchantPartner,
    Requisite,
    RequisiteStatus,
    TraderCard,
    User,
    UserRole,
    WorkingRate,
    WorkingRateMode,
)
from app.services import token_ledger
from app.services.merchant_payin import hash_secret


async def _ensure_users(db) -> tuple[User, User]:
    admin_exists = (
        await db.execute(select(User).where(User.login == "admin"))
    ).scalar_one_or_none()
    if not admin_exists:
        users = [
            User(
                login="owner",
                password_hash=hash_password("owner123"),
                full_name="Владелец",
                role=UserRole.owner,
            ),
            User(
                login="admin",
                password_hash=hash_password("admin123"),
                full_name="Администратор",
                role=UserRole.admin,
            ),
            User(
                login="teamlead1",
                password_hash=hash_password("teamlead123"),
                full_name="Тимлид Сергей",
                role=UserRole.teamlead,
                teamlead_percent=Decimal("12"),
            ),
            User(
                login="trader1",
                password_hash=hash_password("trader123"),
                full_name="Трейдер Иван",
                role=UserRole.trader,
                profit_percent=Decimal("12"),
            ),
            User(
                login="merchant1",
                password_hash=hash_password("merchant123"),
                full_name="Мерчант без депа",
                role=UserRole.trader,
                profit_percent=Decimal("12"),
                deposit_exempt=True,
            ),
            User(
                login="doliv1",
                password_hash=hash_password("doliv123"),
                full_name="Доливщик Петр",
                role=UserRole.dolivshchik,
                doliv_salary_usdt=Decimal("1"),
            ),
        ]
        for u in users:
            db.add(u)
        await db.flush()
        trader = (await db.execute(select(User).where(User.login == "trader1"))).scalar_one()
        tl = (await db.execute(select(User).where(User.login == "teamlead1"))).scalar_one()
        trader.teamlead_id = tl.id
        print("Seed users created")
    else:
        print("Users already present")
        trader = (await db.execute(select(User).where(User.login == "trader1"))).scalar_one()
        tl = (await db.execute(select(User).where(User.login == "teamlead1"))).scalar_one()
        if trader.teamlead_id is None:
            trader.teamlead_id = tl.id
    return trader, tl


async def _ensure_settings_and_rate(db) -> None:
    s = await db.get(AppSettings, 1)
    if not s:
        db.add(AppSettings(id=1, withdraw_fee_usdt=Decimal("3"), default_teamlead_percent=Decimal("12")))
        await db.flush()
    wr = (await db.execute(select(WorkingRate).order_by(WorkingRate.id.desc()).limit(1))).scalar_one_or_none()
    if not wr:
        db.add(WorkingRate(rate=Decimal("90"), mode=WorkingRateMode.manual, comment="Lab seed office rate"))
        await db.flush()


async def _ensure_bridge_and_merchant(db) -> None:
    key_hash = hashlib.sha256(settings.LAB_BRIDGE_KEY.encode()).hexdigest()
    existing = (
        await db.execute(select(BridgeServiceKey).where(BridgeServiceKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if not existing:
        db.add(
            BridgeServiceKey(
                name="focuspay-lab",
                key_prefix=settings.LAB_BRIDGE_KEY[:8],
                key_hash=key_hash,
                is_active=True,
            )
        )
        await db.flush()
        print(f"Bridge key: {settings.LAB_BRIDGE_KEY}")
    partner = (
        await db.execute(
            select(MerchantPartner).where(MerchantPartner.api_key == settings.LAB_MERCHANT_API_KEY)
        )
    ).scalar_one_or_none()
    if not partner:
        db.add(
            MerchantPartner(
                name="lab-partner",
                api_key=settings.LAB_MERCHANT_API_KEY,
                secret=settings.LAB_MERCHANT_SECRET,
                secret_hash=hash_secret(settings.LAB_MERCHANT_SECRET),
                secret_hint=settings.LAB_MERCHANT_SECRET[:4] + "…",
                is_active=True,
            )
        )
        await db.flush()
        print(f"Merchant: api_key={settings.LAB_MERCHANT_API_KEY} secret={settings.LAB_MERCHANT_SECRET}")


async def _ensure_open_float_session(db, trader: User, card: TraderCard, token_id: int | None) -> None:
    open_sess = (
        await db.execute(
            select(Requisite)
            .where(
                Requisite.trader_id == trader.id,
                Requisite.status.in_(
                    [
                        RequisiteStatus.active,
                        RequisiteStatus.in_work,
                        RequisiteStatus.awaiting_doliv,
                        RequisiteStatus.doliv_in_progress,
                    ]
                ),
            )
            .order_by(Requisite.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_sess:
        if (open_sess.float_rub or Decimal("0")) < Decimal("1000"):
            open_sess.float_rub = Decimal("80000")
            print(f"Boosted float on session #{open_sess.id} → 80000")
        return
    sess = Requisite(
        trader_id=trader.id,
        card_id=card.id,
        name=f"{card.name} · seed float",
        total_amount=Decimal("200000"),
        target_rate=Decimal("90"),
        status=RequisiteStatus.in_work,
        float_rub=Decimal("80000"),
        hold_usdt=Decimal("0"),
        work_token_id=token_id,
    )
    db.add(sess)
    await db.flush()
    card.linked_requisite_id = sess.id
    print(f"Opened float session #{sess.id} on card #{card.id} (+80k)")


async def _ensure_trader_cards(db, trader: User, token_id: int | None) -> None:
    existing = (
        await db.execute(select(TraderCard).where(TraderCard.trader_id == trader.id).limit(1))
    ).scalar_one_or_none()
    if existing:
        await _ensure_open_float_session(db, trader, existing, token_id)
        return
    sbp = TraderCard(
        trader_id=trader.id,
        name="Seed СБП",
        bank="Сбер",
        status=CardStatus.active,
        daily_limit_rub=Decimal("200000"),
        accept_limit_rub=Decimal("200000"),
        min_payment_rub=Decimal("1000"),
        max_payment_rub=Decimal("50000"),
        payment_bands=[{"min_rub": 1000, "max_rub": 50000}],
        recipient_name="Иван Тестов",
        phone="+79001112233",
        channel="sbp",
        target_rate=Decimal("90"),
    )
    c2c = TraderCard(
        trader_id=trader.id,
        name="Seed C2C",
        last4="4242",
        bank="Тинькофф",
        status=CardStatus.active,
        daily_limit_rub=Decimal("200000"),
        accept_limit_rub=Decimal("200000"),
        min_payment_rub=Decimal("1000"),
        max_payment_rub=Decimal("50000"),
        payment_bands=[{"min_rub": 1000, "max_rub": 50000}],
        recipient_name="Иван Тестов",
        card_number="2200700011114242",
        channel="c2c",
        target_rate=Decimal("90"),
    )
    db.add_all([sbp, c2c])
    await db.flush()
    sess = Requisite(
        trader_id=trader.id,
        card_id=sbp.id,
        name="СБП · +79001112233 · Иван Тестов",
        total_amount=Decimal("200000"),
        target_rate=Decimal("90"),
        status=RequisiteStatus.in_work,
        float_rub=Decimal("80000"),
        hold_usdt=Decimal("0"),
        work_token_id=token_id,
    )
    db.add(sess)
    await db.flush()
    sbp.linked_requisite_id = sess.id
    print("Seed cards: SBP (+80k float) + C2C")


async def seed():
    if not settings.DEV_MODE:
        print("Seed skipped: set DEV_MODE=true to create demo users")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        trader, tl = await _ensure_users(db)
        await _ensure_settings_and_rate(db)

        trader_token = await token_ledger.ensure_personal_token(db, trader)
        bals = await token_ledger.compute_token_balances(db, trader_token.id)
        if bals["balance"] <= 0:
            await token_ledger.deposit(
                db,
                trader_token.id,
                Decimal("1000"),
                actor_id=None,
                idempotency_key="seed-trader1-deposit",
                comment="Lab seed 1000 USDT (personal)",
            )
        await token_ledger.ensure_personal_token(db, tl)
        await _ensure_trader_cards(db, trader, trader_token.id)
        await _ensure_bridge_and_merchant(db)
        await db.commit()
        print(
            "Ready: owner/owner123, admin/admin123, teamlead1/teamlead123, "
            "trader1/trader123 (+1000 USDT + float 80k), merchant1/merchant123, doliv1/doliv123"
        )
        print(f"Bridge X-Bridge-Key={settings.LAB_BRIDGE_KEY}")
        print(f"Merchant api_key={settings.LAB_MERCHANT_API_KEY} secret={settings.LAB_MERCHANT_SECRET}")


if __name__ == "__main__":
    asyncio.run(seed())

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, auth, bridge_payouts, cards_expenses, doliv, merchant, notifications, owner, tokens, trader
from app.core.config import settings
from app.core.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS trader_salary_percent NUMERIC(6, 2) DEFAULT 20"))
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS doliv_salary_percent NUMERIC(6, 2) DEFAULT 1"))
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS payout_bonus_percent NUMERIC(6, 2) DEFAULT 1"))
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS default_teamlead_percent NUMERIC(6, 2) DEFAULT 2"))
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS withdraw_fee_usdt NUMERIC(10, 2) DEFAULT 3"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS profit_percent NUMERIC(6, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS doliv_salary_usdt NUMERIC(10, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS teamlead_percent NUMERIC(6, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS teamlead_id INTEGER"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deposit_exempt BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_currency VARCHAR(8) DEFAULT 'RUB'"))
        await conn.execute(text("ALTER TABLE deal_results ADD COLUMN IF NOT EXISTS doliv_rate NUMERIC(10, 4) DEFAULT 0"))
        await conn.execute(text("ALTER TABLE deal_results ADD COLUMN IF NOT EXISTS turnover_usdt NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE requisites ADD COLUMN IF NOT EXISTS float_rub NUMERIC(14, 2) DEFAULT 0"))
        await conn.execute(text("ALTER TABLE requisites ADD COLUMN IF NOT EXISTS hold_usdt NUMERIC(14, 6)"))
        await conn.execute(text("ALTER TABLE requisites ADD COLUMN IF NOT EXISTS work_token_id INTEGER"))
        await conn.execute(text("ALTER TABLE requisites ADD COLUMN IF NOT EXISTS card_id INTEGER"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS accept_limit_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS target_rate NUMERIC(10, 4)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS daily_limit_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS min_payment_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS max_payment_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS payment_bands JSON"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS recipient_name VARCHAR(128)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS card_number VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS phone VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS channel VARCHAR(8) DEFAULT 'c2c'"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS traffic_min_orders INTEGER"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS traffic_max_orders INTEGER"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS traffic_min_volume_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS traffic_max_volume_rub NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE merchant_partners ADD COLUMN IF NOT EXISTS secret VARCHAR(128) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS zaliv_id INTEGER"))
        if conn.dialect.name == "postgresql":
            await conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'owner'"))
            await conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'teamlead'"))
            for val in ("active", "warming", "blocked", "archived"):
                await conn.execute(text(f"DO $$ BEGIN CREATE TYPE cardstatus AS ENUM ('active','warming','blocked','archived'); EXCEPTION WHEN duplicate_object THEN NULL; END $$"))
                break
            await conn.execute(text(
                "DO $$ BEGIN CREATE TYPE expensecategory AS ENUM "
                "('card_purchase','warm','block_loss','other'); "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            ))
            await conn.execute(text(
                "DO $$ BEGIN CREATE TYPE workingratemode AS ENUM "
                "('manual','rapira_snap','fixed'); "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            ))
            await conn.execute(text(
                "DO $$ BEGIN CREATE TYPE paymentchannel AS ENUM "
                "('c2c','sbp'); "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            ))
            # If channel was added as VARCHAR earlier, coerce via text is fine for lab
    yield


app = FastAPI(
    title="P2P Doliv Panel (Lab)",
    version="1.2.0-lab",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEV_MODE else None,
    redoc_url="/redoc" if settings.DEV_MODE else None,
    openapi_url="/openapi.json" if settings.DEV_MODE else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(trader.router)
app.include_router(doliv.router)
app.include_router(admin.router)
app.include_router(owner.router)
app.include_router(notifications.router)
app.include_router(tokens.router)
app.include_router(cards_expenses.router)
app.include_router(bridge_payouts.router)
app.include_router(merchant.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": "prod" if not settings.DEV_MODE else "lab"}

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, auth, doliv, notifications, owner, trader
from app.core.config import settings
from app.core.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS trader_salary_percent NUMERIC(6, 2) DEFAULT 20"))
        await conn.execute(text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS doliv_salary_percent NUMERIC(6, 2) DEFAULT 1"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS profit_percent NUMERIC(6, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS doliv_salary_usdt NUMERIC(10, 2)"))
        await conn.execute(text("ALTER TABLE deal_results ADD COLUMN IF NOT EXISTS doliv_rate NUMERIC(10, 4) DEFAULT 0"))
        await conn.execute(text("ALTER TABLE deal_results ADD COLUMN IF NOT EXISTS turnover_usdt NUMERIC(14, 2)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0"))
        if conn.dialect.name == "postgresql":
            await conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'owner'"))
    yield


app = FastAPI(
    title="P2P Doliv Panel",
    version="1.0.0",
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


@app.get("/health")
async def health():
    return {"status": "ok"}

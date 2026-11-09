"""Shared pytest fixtures for the P2P Doliv Panel backend test suite.

Uses an in-process SQLite database (via aiosqlite) so no external PostgreSQL
instance is required. SELECT FOR UPDATE is silently ignored by SQLite which is
acceptable for unit/integration tests; race-condition tests would require a
real PostgreSQL instance.
"""
import os
import tempfile
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Point settings at SQLite before importing the app so the engine is created correctly.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_doliv.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="doliv_test_uploads_"))

from app.core.auth import hash_password
from app.core.database import Base, get_db
from app.main import app
from app.models import AppSettings, User, UserRole

TEST_DB_URL = "sqlite+aiosqlite:///./test_doliv.db"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """Create all tables once per test session."""
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    db_file = TEST_DB_URL.replace("sqlite+aiosqlite:///", "")
    if os.path.exists(db_file):
        os.remove(db_file)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh session that rolls back after each test."""
    engine = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client wired to the FastAPI app with test DB injected."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _create_user(
    db: AsyncSession,
    login: str,
    password: str,
    full_name: str,
    role: UserRole,
    profit_percent: Decimal | None = None,
    doliv_salary_usdt: Decimal | None = None,
) -> User:
    if role == UserRole.trader and profit_percent is None:
        profit_percent = Decimal("12")
    if role == UserRole.dolivshchik and doliv_salary_usdt is None:
        doliv_salary_usdt = Decimal("1")
    user = User(
        login=login,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=True,
        profit_percent=profit_percent if role == UserRole.trader else None,
        doliv_salary_usdt=doliv_salary_usdt if role == UserRole.dolivshchik else None,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    return await _create_user(db_session, "owner_test", "Ownerpass12", "Owner User", UserRole.owner)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await _create_user(db_session, "admin_test", "Adminpass12", "Admin User", UserRole.admin)


@pytest_asyncio.fixture
async def trader_user(db_session: AsyncSession) -> User:
    return await _create_user(db_session, "trader_test", "Traderpass12", "Trader User", UserRole.trader)


@pytest_asyncio.fixture
async def doliv_user(db_session: AsyncSession) -> User:
    return await _create_user(db_session, "doliv_test", "Dolivpass12", "Doliv User", UserRole.dolivshchik)


@pytest_asyncio.fixture
async def app_settings(db_session: AsyncSession) -> AppSettings:
    s = AppSettings(id=1)
    db_session.add(s)
    await db_session.flush()
    await db_session.refresh(s)
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────────────────────

async def get_token(client: AsyncClient, login: str, password: str) -> str:
    resp = await client.post("/auth/login", json={"login": login, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

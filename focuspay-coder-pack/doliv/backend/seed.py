import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.config import settings
from app.core.database import async_session, engine, Base
from app.models import User, UserRole


async def seed():
    if not settings.DEV_MODE:
        print("Seed skipped: set DEV_MODE=true to create demo users")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        owner_exists = (
            await db.execute(select(User).where(User.login == "owner"))
        ).scalar_one_or_none()
        admin_exists = (
            await db.execute(select(User).where(User.login == "admin"))
        ).scalar_one_or_none()

        if admin_exists:
            if not owner_exists:
                db.add(
                    User(
                        login="owner",
                        password_hash=hash_password("owner123"),
                        full_name="Владелец",
                        role=UserRole.owner,
                    )
                )
                await db.commit()
                print("Owner user created: owner/owner123")
            else:
                print("Seed already applied")
            return

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
                login="trader1",
                password_hash=hash_password("trader123"),
                full_name="Трейдер Иван",
                role=UserRole.trader,
                profit_percent=Decimal("12"),
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
        await db.commit()
        print("Seed users created: owner/owner123, admin/admin123, trader1/trader123, doliv1/doliv123")


if __name__ == "__main__":
    asyncio.run(seed())

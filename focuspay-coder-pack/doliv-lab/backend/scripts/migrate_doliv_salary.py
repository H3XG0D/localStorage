"""One-off migration: assign per-dolivshchik salary rate from global default.

Run from the backend directory:

    python -m scripts.migrate_doliv_salary
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.database import async_session
from app.models import AppSettings, User, UserRole


async def migrate() -> None:
    async with async_session() as session:
        settings = await session.get(AppSettings, 1)
        default_rate = (
            settings.doliv_salary_percent if settings else Decimal("1")
        )

        dolivshchiks = (
            await session.execute(select(User).where(User.role == UserRole.dolivshchik))
        ).scalars().all()

        updated = 0
        for user in dolivshchiks:
            if user.doliv_salary_usdt is None:
                user.doliv_salary_usdt = default_rate
                updated += 1
                print(f"Dolivshchik {user.login}: doliv_salary_usdt={default_rate}")

        await session.commit()
        print(f"Done. {len(dolivshchiks)} dolivshchiks, {updated} updated.")


if __name__ == "__main__":
    asyncio.run(migrate())

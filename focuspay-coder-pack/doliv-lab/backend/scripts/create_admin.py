"""Create the first admin user in production when no users exist."""
import asyncio
import getpass
import sys

from sqlalchemy import func, select

from app.core.auth import hash_password
from app.core.database import async_session, engine, Base
from app.models import User, UserRole


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        if count > 0:
            print(f"Users already exist ({count}). Skipping.")
            return

        login = input("Admin login [admin]: ").strip() or "admin"
        full_name = input("Full name [Администратор]: ").strip() or "Администратор"
        password = getpass.getpass("Password (min 12 chars): ")
        if len(password) < 12:
            print("Password must be at least 12 characters.", file=sys.stderr)
            sys.exit(1)

        db.add(
            User(
                login=login,
                password_hash=hash_password(password),
                full_name=full_name,
                role=UserRole.admin,
            )
        )
        await db.commit()
        print(f"Admin user '{login}' created.")


if __name__ == "__main__":
    asyncio.run(main())

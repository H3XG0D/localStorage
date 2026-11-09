"""Add accepting_enabled / paused_at on trader_cards for existing databases.

    python -m scripts.migrate_card_accepting
"""
import asyncio

from sqlalchemy import text

from app.core.database import engine


async def migrate() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE trader_cards "
                "ADD COLUMN IF NOT EXISTS accepting_enabled BOOLEAN NOT NULL DEFAULT false"
            )
        )
        await conn.execute(
            text("ALTER TABLE trader_cards ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ")
        )
        await conn.execute(
            text(
                """
                UPDATE trader_cards SET accepting_enabled = true
                WHERE linked_requisite_id IS NOT NULL AND status = 'active'
                """
            )
        )
    print("Done: trader_cards.accepting_enabled, paused_at")


if __name__ == "__main__":
    asyncio.run(migrate())

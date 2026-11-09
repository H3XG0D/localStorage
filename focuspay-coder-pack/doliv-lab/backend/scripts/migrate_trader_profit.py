"""One-off migration: assign per-trader profit_percent and recalculate zalivs/deal_results.

Run from the backend directory:

    python -m scripts.migrate_trader_profit
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.database import async_session
from app.models import AppSettings, User, UserRole
from app.services.trader_profit import apply_trader_profit_percent, resolve_trader_profit_percent


async def migrate() -> None:
    async with async_session() as session:
        settings = await session.get(AppSettings, 1)
        default_percent = (
            settings.default_profit_percent if settings else Decimal("12")
        )

        traders = (
            await session.execute(select(User).where(User.role == UserRole.trader))
        ).scalars().all()

        total_zalivs = 0
        total_deals = 0
        for trader in traders:
            if trader.profit_percent is None:
                trader.profit_percent = default_percent

            percent = await resolve_trader_profit_percent(session, trader)
            zalivs, deals = await apply_trader_profit_percent(session, trader.id, percent)
            total_zalivs += zalivs
            total_deals += deals
            print(f"Trader {trader.login}: profit_percent={percent}, zalivs={zalivs}, deals={deals}")

        await session.commit()
        print(
            f"Done. {len(traders)} traders, {total_zalivs} zalivs updated, "
            f"{total_deals} deal results recalculated."
        )


if __name__ == "__main__":
    asyncio.run(migrate())

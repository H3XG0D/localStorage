"""One-off migration: recompute historical DealResult profit values in USDT.

Before this change `zaliv_profit` (and therefore `final_profit`) were stored in
rubles, while `doliv_profit_loss` was already in USDT. This script recomputes all
deal result profit fields from source zalivs/dolivs so stored values are consistent
in USDT.

Run from the backend directory:

    python -m scripts.recalc_usdt
"""
import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.models import DealResult, Doliv, DolivRequest, Requisite
from app.services.profit import calc_doliv_profit_loss, calc_zaliv_profit

MIN_DOLIV_RATE = Decimal("50")
MAX_DOLIV_RATE = Decimal("200")


def _normalize_doliv_rate(rate: Decimal, target_rate: Decimal) -> Decimal:
    if rate < MIN_DOLIV_RATE or rate > MAX_DOLIV_RATE:
        return target_rate
    return rate


async def recalc() -> None:
    async with async_session() as session:
        result = await session.execute(
            select(DealResult).options(
                selectinload(DealResult.requisite).selectinload(Requisite.zalivs)
            )
        )
        deal_results = result.scalars().all()

        doliv_rows = (
            await session.execute(
                select(DolivRequest.requisite_id, Doliv.amount, Doliv.rate, Doliv.id)
                .select_from(Doliv)
                .join(DolivRequest, DolivRequest.id == Doliv.request_id)
            )
        ).all()
        doliv_by_requisite = {req_id: (amount, rate, doliv_id) for req_id, amount, rate, doliv_id in doliv_rows}

        updated = 0
        for deal in deal_results:
            requisite = deal.requisite
            if requisite is None:
                continue

            doliv_info = doliv_by_requisite.get(deal.requisite_id)
            if doliv_info is None:
                continue

            doliv_amount, doliv_rate, doliv_id = doliv_info
            normalized_rate = _normalize_doliv_rate(doliv_rate, requisite.target_rate)
            if normalized_rate != doliv_rate:
                doliv_row = await session.get(Doliv, doliv_id)
                if doliv_row is not None:
                    doliv_row.rate = normalized_rate

            doliv = Doliv(
                request_id=0,
                dolivshchik_id=0,
                amount=doliv_amount,
                rate=normalized_rate,
                receipt_path="",
            )
            new_zaliv_profit = calc_zaliv_profit(requisite.zalivs, requisite.target_rate)
            new_doliv_profit_loss = calc_doliv_profit_loss(doliv, requisite.target_rate)
            new_final = (new_zaliv_profit + new_doliv_profit_loss).quantize(Decimal("0.01"))

            if (
                deal.zaliv_profit != new_zaliv_profit
                or deal.doliv_profit_loss != new_doliv_profit_loss
                or deal.final_profit != new_final
                or deal.doliv_rate != normalized_rate
            ):
                deal.zaliv_profit = new_zaliv_profit
                deal.doliv_profit_loss = new_doliv_profit_loss
                deal.final_profit = new_final
                deal.doliv_rate = normalized_rate
                updated += 1

        await session.commit()
        print(f"Processed {len(deal_results)} deal results, updated {updated}.")


if __name__ == "__main__":
    asyncio.run(recalc())

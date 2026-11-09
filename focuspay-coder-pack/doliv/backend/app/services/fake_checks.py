from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FakeCheck, FakeCheckAuditLog, User


async def log_fake_check_action(
    db: AsyncSession,
    action: str,
    *,
    requisite_id: int,
    user: User,
    fake_check_id: int | None = None,
    amount_rub: Decimal | None = None,
    rate: Decimal | None = None,
    amount_usdt: Decimal | None = None,
    comment: str | None = None,
    file_path: str | None = None,
) -> FakeCheckAuditLog:
    entry = FakeCheckAuditLog(
        action=action,
        requisite_id=requisite_id,
        fake_check_id=fake_check_id,
        amount_rub=amount_rub,
        rate=rate,
        amount_usdt=amount_usdt,
        comment=comment,
        file_path=Path(file_path).name if file_path else None,
        user_id=user.id,
    )
    db.add(entry)
    await db.flush()
    return entry


def snapshot_fake_check(fc: FakeCheck) -> dict:
    return {
        "fake_check_id": fc.id,
        "amount_rub": fc.amount_rub,
        "rate": fc.rate,
        "amount_usdt": fc.amount_usdt,
        "comment": fc.comment,
        "file_path": fc.file_path,
    }

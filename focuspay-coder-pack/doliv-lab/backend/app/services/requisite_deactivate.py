from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    DolivRequest,
    DolivRequestStatus,
    Requisite,
    RequisiteStatus,
    User,
    UserRole,
)
from app.services.notifications import notify_roles, notify_user

_DEACTIVATABLE = {
    RequisiteStatus.active,
    RequisiteStatus.in_work,
    RequisiteStatus.awaiting_doliv,
    RequisiteStatus.doliv_in_progress,
    RequisiteStatus.closed,
}


async def deactivate_requisite(
    db: AsyncSession,
    requisite: Requisite,
    actor: User,
) -> Requisite:
    if requisite.status == RequisiteStatus.archive:
        raise HTTPException(status_code=400, detail="Requisite is already deactivated")

    if requisite.status not in _DEACTIVATABLE:
        raise HTTPException(status_code=400, detail="Requisite cannot be deactivated")

    result = await db.execute(
        select(DolivRequest)
        .where(
            DolivRequest.requisite_id == requisite.id,
            DolivRequest.status.in_([
                DolivRequestStatus.pending,
                DolivRequestStatus.in_progress,
            ]),
        )
        .with_for_update()
    )
    for request in result.scalars().all():
        if request.status == DolivRequestStatus.completed:
            continue
        assigned_id = request.assigned_dolivshchik_id
        request.status = DolivRequestStatus.cancelled
        request.assigned_dolivshchik_id = None
        if assigned_id:
            await notify_user(
                db,
                assigned_id,
                "Заявка отменена",
                f"Заявка #{request.id} по реквизиту {requisite.name} отменена (рек отключён)",
                kind="doliv_cancelled",
                link="/doliv",
            )
        await notify_user(
            db,
            requisite.trader_id,
            "Заявка на долив отменена",
            f"Заявка #{request.id} по реквизиту {requisite.name} отменена (рек отключён)",
            kind="doliv_cancelled",
            link=f"/trader/requisites/{requisite.id}",
        )
        await notify_roles(
            db,
            [UserRole.admin],
            "Заявка отменена",
            f"{actor.full_name} отключил рек {requisite.name}, заявка #{request.id} отменена",
            kind="doliv_cancelled",
            link=f"/admin/requisites/{requisite.id}",
            exclude_user_ids={actor.id},
        )

    requisite.status = RequisiteStatus.archive
    from app.services.deal_settlement import release_on_deactivate

    await release_on_deactivate(db, requisite, actor_id=actor.id)
    await db.flush()
    return requisite


async def get_requisite_for_deactivate(
    db: AsyncSession,
    requisite_id: int,
    trader_id: int | None = None,
) -> Requisite:
    query = (
        select(Requisite)
        .options(selectinload(Requisite.zalivs))
        .where(Requisite.id == requisite_id)
        .with_for_update()
    )
    if trader_id is not None:
        query = query.where(Requisite.trader_id == trader_id)
    result = await db.execute(query)
    requisite = result.scalar_one_or_none()
    if not requisite:
        raise HTTPException(status_code=404, detail="Requisite not found")
    return requisite

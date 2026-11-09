from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User, UserRole


async def notify_user(
    db: AsyncSession,
    user_id: int | None,
    title: str,
    message: str,
    *,
    kind: str = "info",
    link: str | None = None,
) -> None:
    if not user_id:
        return
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            kind=kind,
            link=link,
        )
    )


async def notify_roles(
    db: AsyncSession,
    roles: list[UserRole],
    title: str,
    message: str,
    *,
    kind: str = "info",
    link: str | None = None,
    exclude_user_ids: set[int] | None = None,
) -> None:
    exclude_user_ids = exclude_user_ids or set()
    result = await db.execute(
        select(User).where(User.role.in_(roles), User.is_active == True)
    )
    for user in result.scalars().all():
        if user.id in exclude_user_ids:
            continue
        await notify_user(db, user.id, title, message, kind=kind, link=link)

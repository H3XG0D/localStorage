import uuid

from fastapi import HTTPException

from db import get_pool


async def get_or_create_guest_user_id(session_token: str) -> int:
    try:
        token = uuid.UUID(session_token.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guest session")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT synthetic_user_id FROM web_guest_sessions WHERE session_token = $1",
            token,
        )
        if row:
            return int(row["synthetic_user_id"])

        from synthetic_user_ids import allocate_synthetic_user_id

        synthetic = await allocate_synthetic_user_id(conn)
        await conn.execute(
            """
            INSERT INTO web_guest_sessions (session_token, synthetic_user_id)
            VALUES ($1, $2)
            """,
            token,
            synthetic,
        )
        return int(synthetic)


async def merge_guest_orders_to_telegram(guest_user_id: int, telegram_user_id: int) -> int:
    from web_attribution import merge_guest_attribution_to_user

    await merge_guest_attribution_to_user(guest_user_id, telegram_user_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE orders SET user_id = $2, updated_at = now()
            WHERE user_id = $1
            """,
            guest_user_id,
            telegram_user_id,
        )
    # result like 'UPDATE 3'
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0

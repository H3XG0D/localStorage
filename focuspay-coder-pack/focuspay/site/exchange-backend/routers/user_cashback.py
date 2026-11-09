from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_current_user, resolve_client_user_id
from user_cashback_db import set_use_cashback_on_next
from user_unified_balance import get_unified_balance_stats

router = APIRouter()


class CashbackToggleBody(BaseModel):
    use_on_next: bool


@router.get("/cashback")
async def get_cashback(current_user: dict = Depends(get_current_user)):
    client_id = resolve_client_user_id(current_user)
    return await get_unified_balance_stats(client_id)


@router.patch("/cashback")
async def patch_cashback(
    body: CashbackToggleBody,
    current_user: dict = Depends(get_current_user),
):
    client_id = resolve_client_user_id(current_user)
    await set_use_cashback_on_next(client_id, body.use_on_next)
    return await get_unified_balance_stats(client_id)

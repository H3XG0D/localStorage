from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user, resolve_client_user_id
from battle_models import BetRequest, CurrentRound, HistoryItem
from battle_service import get_battle_manager
from config import settings

router = APIRouter()


def _require_battle_enabled() -> None:
    if not settings.battle_enabled:
        raise HTTPException(status_code=503, detail="Battle is disabled")


@router.get("/battle/current", response_model=CurrentRound)
async def get_current(current_user: dict = Depends(get_current_user)):
    _require_battle_enabled()
    client_id = resolve_client_user_id(current_user)
    return await (await get_battle_manager()).get_current_for_user(client_id)


@router.post("/battle/bet", response_model=CurrentRound)
async def place_bet(
    body: BetRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_battle_enabled()
    client_id = resolve_client_user_id(current_user)
    try:
        return await (await get_battle_manager()).place_bet(
            client_id, body.side, body.amount_rub
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/battle/history", response_model=list[HistoryItem])
async def get_history(
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    _require_battle_enabled()
    return await (await get_battle_manager()).get_history(limit)


@router.get("/battle/enabled")
async def battle_enabled():
    return {"enabled": settings.battle_enabled}

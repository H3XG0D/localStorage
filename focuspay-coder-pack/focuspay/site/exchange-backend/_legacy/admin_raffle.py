"""FocusLucky admin API for /x8 panel."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_admin
import raffle_service as rs

router = APIRouter()


class TextUpdateBody(BaseModel):
    info_text: Optional[str] = None
    how_to_text: Optional[str] = None
    clear_info: bool = False
    clear_how: bool = False


class BlockBody(BaseModel):
    scope: str = Field(default="all", pattern="^(all|referral)$")


async def _require_campaign() -> dict:
    camp = await rs.get_campaign_for_admin()
    if not camp:
        raise HTTPException(status_code=404, detail="Нет кампании FocusLucky")
    return camp


@router.get("/raffle")
async def raffle_overview(_admin=Depends(get_current_admin)):
    overview = await rs.get_campaign_overview()
    if not overview:
        raise HTTPException(status_code=404, detail="Нет кампании FocusLucky")
    return overview


@router.get("/raffle/partners")
async def raffle_partners(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    q: Optional[str] = Query(None),
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    return await rs.list_raffle_partners(int(camp["id"]), page=page, limit=limit, q=q)


@router.get("/raffle/participants")
async def raffle_participants(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    return await rs.list_participants(int(camp["id"]), page=page, limit=limit, q=q)


@router.get("/raffle/participants/{user_id}")
async def raffle_participant(
    user_id: int,
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    detail = await rs.get_participant_detail(int(camp["id"]), user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Участник не найден")
    return detail


@router.patch("/raffle/text")
async def raffle_update_text(
    body: TextUpdateBody,
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    ok = await rs.update_campaign_text(
        int(camp["id"]),
        info_text=body.info_text,
        how_to_text=body.how_to_text,
        clear_info=body.clear_info,
        clear_how=body.clear_how,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Нечего обновлять")
    return await rs.get_campaign_overview()


@router.post("/raffle/close")
async def raffle_close(_admin=Depends(get_current_admin)):
    camp = await _require_campaign()
    ok = await rs.close_campaign(int(camp["id"]))
    if not ok:
        raise HTTPException(status_code=409, detail="Не удалось закрыть кампанию")
    return await rs.get_campaign_overview()


@router.post("/raffle/activate")
async def raffle_activate(_admin=Depends(get_current_admin)):
    camp = await _require_campaign()
    ok = await rs.activate_campaign(int(camp["id"]))
    if not ok:
        raise HTTPException(status_code=409, detail="Не удалось активировать")
    return await rs.get_campaign_overview()


@router.post("/raffle/start-new-without-draw")
async def raffle_start_new_without_draw(_admin=Depends(get_current_admin)):
    camp = await _require_campaign()
    try:
        await rs.start_new_campaign_without_draw(int(camp["id"]))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return await rs.get_campaign_overview()


@router.post("/raffle/draw")
async def raffle_draw(_admin=Depends(get_current_admin)):
    camp = await _require_campaign()
    cid = int(camp["id"])
    if camp.get("status") == "active":
        await rs.close_campaign(cid)
    try:
        result = await rs.run_draw(cid)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    overview = await rs.get_campaign_overview()
    return {"draw": result, "overview": overview}


@router.post("/raffle/pay-balance")
async def raffle_pay_balance(_admin=Depends(get_current_admin)):
    camp = await _require_campaign()
    paid = await rs.pay_balance_winners(int(camp["id"]))
    if not paid:
        raise HTTPException(status_code=404, detail="Нет pending balance-призов")
    return {"paid": paid, "count": len(paid)}


@router.post("/raffle/participants/{user_id}/block")
async def raffle_block_user(
    user_id: int,
    admin=Depends(get_current_admin),
    body: BlockBody = BlockBody(),
):
    camp = await _require_campaign()
    blocked_by = int(admin.get("telegram_user_id") or admin.get("id") or 0) or None
    await rs.set_accrual_blocked(
        int(camp["id"]),
        user_id,
        True,
        blocked_by=blocked_by,
        scope=body.scope,
    )
    detail = await rs.get_participant_detail(int(camp["id"]), user_id)
    if detail:
        return detail
    scope = body.scope
    return {
        "user_id": user_id,
        "accrual_blocked": scope == "all",
        "referral_accrual_blocked": scope in ("all", "referral"),
        "accrual_block_scope": scope,
    }


@router.post("/raffle/partners/{user_id}/block")
async def raffle_block_partner(
    user_id: int,
    admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    blocked_by = int(admin.get("telegram_user_id") or admin.get("id") or 0) or None
    await rs.set_accrual_blocked(
        int(camp["id"]),
        user_id,
        True,
        blocked_by=blocked_by,
        scope="referral",
    )
    partners = await rs.list_raffle_partners(int(camp["id"]), page=1, limit=100)
    item = next((p for p in partners["items"] if p["telegram_user_id"] == user_id), None)
    if item:
        return item
    return {
        "telegram_user_id": user_id,
        "referral_accrual_blocked": True,
        "accrual_block_scope": "referral",
    }


@router.delete("/raffle/partners/{user_id}/block")
async def raffle_unblock_partner(
    user_id: int,
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    await rs.set_accrual_blocked(int(camp["id"]), user_id, False)
    partners = await rs.list_raffle_partners(int(camp["id"]), page=1, limit=100)
    item = next((p for p in partners["items"] if p["telegram_user_id"] == user_id), None)
    if item:
        return item
    return {
        "telegram_user_id": user_id,
        "referral_accrual_blocked": False,
        "accrual_block_scope": None,
    }


@router.delete("/raffle/participants/{user_id}/block")
async def raffle_unblock_user(
    user_id: int,
    _admin=Depends(get_current_admin),
):
    camp = await _require_campaign()
    await rs.set_accrual_blocked(int(camp["id"]), user_id, False)
    detail = await rs.get_participant_detail(int(camp["id"]), user_id)
    if detail:
        return detail
    return {"user_id": user_id, "accrual_blocked": False}

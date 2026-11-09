"""FocusPay Battle Lab — FastAPI backend."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from battle_round import BattleRoundManager
from config import DB_PATH
from models import BetRequest, CurrentRound, HistoryItem, SeedRequest
from wallet import MockWallet

wallet = MockWallet(DB_PATH)
manager = BattleRoundManager(wallet, DB_PATH)
_scheduler_task: asyncio.Task | None = None


async def _scheduler_loop() -> None:
    while True:
        try:
            await manager.lock_if_needed()
            await manager.resolve_due_rounds()
        except Exception:
            pass
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_task
    await wallet.init()
    await manager.init()
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    yield
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="FocusPay Battle Lab", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def lab_user(x_lab_user: str | None = Header(default="alice")) -> str:
    return (x_lab_user or "alice").strip() or "alice"


@app.get("/api/battle/current", response_model=CurrentRound)
async def get_current(user_id: str = Header(alias="X-Lab-User", default="alice")):
    return await manager.get_current_for_user(lab_user(user_id))


@app.post("/api/battle/bet", response_model=CurrentRound)
async def place_bet(
    body: BetRequest,
    user_id: str = Header(alias="X-Lab-User", default="alice"),
):
    try:
        return await manager.place_bet(lab_user(user_id), body.side, body.amount_rub)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/battle/history", response_model=list[HistoryItem])
async def get_history(limit: int = 20):
    return await manager.get_history(min(limit, 100))


@app.post("/api/dev/seed")
async def dev_seed(body: SeedRequest):
    await wallet.seed(body.user_id, body.amount)
    balance = await wallet.available(body.user_id)
    return {"user_id": body.user_id, "balance_available": balance}


@app.get("/health")
async def health():
    return {"ok": True}

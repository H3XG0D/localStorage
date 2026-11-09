"""Pydantic models for battle API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["red", "blue"]
RoundStatus = Literal["open", "locked", "resolved", "cancelled"]


class MyBet(BaseModel):
    side: Side
    amount: float


class CurrentRound(BaseModel):
    round_id: int
    seconds_left: int
    red_total: float
    blue_total: float
    red_pct: float
    blue_pct: float
    bank: float
    status: RoundStatus
    my_bet: MyBet | None = None
    balance_available: float


class BetRequest(BaseModel):
    side: Side
    amount_rub: float = Field(gt=0)


class HistoryItem(BaseModel):
    round_id: int
    winner: Side | None
    red_total: float
    blue_total: float
    ended_at: str

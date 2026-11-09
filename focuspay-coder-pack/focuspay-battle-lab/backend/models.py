"""Pydantic models and SQLite schema for battle rounds."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["red", "blue"]
RoundStatus = Literal["open", "locked", "resolved", "cancelled"]


BATTLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS battle_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'open',
    red_total REAL NOT NULL DEFAULT 0,
    blue_total REAL NOT NULL DEFAULT 0,
    winner TEXT,
    ends_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS battle_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    side TEXT NOT NULL,
    amount_rub REAL NOT NULL,
    UNIQUE(round_id, user_id, side)
);
CREATE INDEX IF NOT EXISTS idx_battle_bets_round ON battle_bets(round_id);
CREATE INDEX IF NOT EXISTS idx_battle_rounds_status ON battle_rounds(status);
"""


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


class SeedRequest(BaseModel):
    user_id: str
    amount: float = Field(gt=0)


def iso_now() -> str:
    return datetime.utcnow().isoformat() + "Z"

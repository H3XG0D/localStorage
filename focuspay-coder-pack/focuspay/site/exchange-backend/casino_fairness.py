"""Player seed-pair sessions: rotation reveals the previous server seed."""
from __future__ import annotations

import re
import secrets
from typing import Mapping

from fastapi import HTTPException

from casino_cards import DEFAULT_CLIENT_SEED, pair_commit

CLIENT_SEED_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_client_seed(value: str) -> str:
    text = (value or "").strip()
    if not CLIENT_SEED_RE.fullmatch(text):
        raise HTTPException(
            status_code=400,
            detail="Client seed must be 1–64 letters, digits, dot, underscore or hyphen",
        )
    return text


def _session_public(row: Mapping[str, object], *, rotation_allowed: bool) -> dict[str, object]:
    previous_seed = row.get("previous_server_seed")
    previous_commit = row.get("previous_commit")
    return {
        "success": True,
        "commit_hash": str(row["commit_hash"]),
        "client_seed": str(row["client_seed"]),
        "nonce": int(row["nonce"]),
        "previous_server_seed": str(previous_seed) if previous_seed else None,
        "previous_commit": str(previous_commit) if previous_commit else None,
        "rotation_allowed": rotation_allowed,
    }


async def seed_rotation_allowed(conn) -> bool:
    row = await conn.fetchrow(
        "SELECT value FROM casino_settings WHERE key = 'seed_rotation_allowed'"
    )
    if row is None:
        return True
    value = row["value"]
    enabled = value.get("enabled") if isinstance(value, dict) else value
    if isinstance(enabled, bool):
        return enabled
    return True


async def get_or_create_fairness_session(conn, telegram_id: int) -> dict[str, object]:
    row = await conn.fetchrow(
        """
        SELECT telegram_id, server_seed, commit_hash, client_seed, nonce,
               previous_server_seed, previous_commit
        FROM casino_fairness_seeds
        WHERE telegram_id = $1
        FOR UPDATE
        """,
        telegram_id,
    )
    if row:
        return dict(row)
    seed = secrets.token_hex(32)
    commit = pair_commit(seed)
    await conn.execute(
        """
        INSERT INTO casino_fairness_seeds (
            telegram_id, server_seed, commit_hash, client_seed, nonce
        ) VALUES ($1, $2, $3, $4, 0)
        ON CONFLICT (telegram_id) DO NOTHING
        """,
        telegram_id, seed, commit, DEFAULT_CLIENT_SEED,
    )
    row = await conn.fetchrow(
        """
        SELECT telegram_id, server_seed, commit_hash, client_seed, nonce,
               previous_server_seed, previous_commit
        FROM casino_fairness_seeds
        WHERE telegram_id = $1
        FOR UPDATE
        """,
        telegram_id,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Fairness session could not be created")
    return dict(row)


async def increment_session_nonce(conn, telegram_id: int, expected_nonce: int) -> None:
    result = await conn.execute(
        """
        UPDATE casino_fairness_seeds
        SET nonce = nonce + 1, updated_at = now()
        WHERE telegram_id = $1 AND nonce = $2
        """,
        telegram_id, expected_nonce,
    )
    if isinstance(result, str):
        parts = result.split()
        if len(parts) >= 2 and parts[-1] == "0":
            raise HTTPException(status_code=409, detail="Fairness nonce already used")


async def public_fairness_session(conn, telegram_id: int) -> dict[str, object]:
    session = await get_or_create_fairness_session(conn, telegram_id)
    allowed = await seed_rotation_allowed(conn)
    return _session_public(session, rotation_allowed=allowed)


async def set_client_seed(conn, telegram_id: int, client_seed: str) -> dict[str, object]:
    seed = validate_client_seed(client_seed)
    await get_or_create_fairness_session(conn, telegram_id)
    await conn.execute(
        """
        UPDATE casino_fairness_seeds
        SET client_seed = $2, updated_at = now()
        WHERE telegram_id = $1
        """,
        telegram_id, seed,
    )
    return await public_fairness_session(conn, telegram_id)


async def rotate_fairness_session(conn, telegram_id: int) -> dict[str, object]:
    if not await seed_rotation_allowed(conn):
        raise HTTPException(status_code=409, detail="Seed rotation is disabled")
    session = await get_or_create_fairness_session(conn, telegram_id)
    previous_seed = str(session["server_seed"])
    previous_commit = str(session["commit_hash"])
    new_seed = secrets.token_hex(32)
    new_commit = pair_commit(new_seed)
    if new_commit == previous_commit:
        raise HTTPException(status_code=409, detail="Seed rotation did not change the pair")
    await conn.execute(
        """
        UPDATE casino_fairness_seeds
        SET server_seed = $2,
            commit_hash = $3,
            nonce = 0,
            previous_server_seed = $4,
            previous_commit = $5,
            rotated_at = now(),
            updated_at = now()
        WHERE telegram_id = $1
        """,
        telegram_id, new_seed, new_commit, previous_seed, previous_commit,
    )
    allowed = await seed_rotation_allowed(conn)
    return {
        **_session_public(
            {
                "commit_hash": new_commit,
                "client_seed": session["client_seed"],
                "nonce": 0,
                "previous_server_seed": previous_seed,
                "previous_commit": previous_commit,
            },
            rotation_allowed=allowed,
        ),
        "previous_server_seed": previous_seed,
        "previous_commit": previous_commit,
    }

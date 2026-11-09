"""Site-created 1×1 baccarat/blackjack: the HMAC shoe finishes the round.

Telegram PvP waits for hit/stand in private chat. A site creator never gets those
buttons (DM to a web user fails), so a Telegram joiner can take a card and then
hang until the 2h move timeout. Web-* duels auto-draw with the same house rules
and settle as soon as the second seat fills — or on the next room poll if an
older match is already stuck.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Mapping, Sequence

from fastapi import HTTPException

from casino_cards import CARD_GAME_TYPES, CARD_SHUFFLE_ALGORITHM, pair_commit
from casino_house_cards import compare_house_cards, deal_house_side_cards, house_card_score

logger = logging.getLogger("casino_pvp_cards")

SITE_DUEL_ID_RE = re.compile(r"^web-[0-9a-f]{12}$")
DEMO_JOIN_DETAIL = "Это демонстрационный стол, в него нельзя сесть"
REASON_UNFINISHABLE = "unfinishable_card_duel"
_SITE_CARD_COLUMNS = (
    "game_id, game_type, creator_id, opponent_id, bet_rub, creator_hold_id, "
    "opponent_hold_id, counterparty_kind, game_data, status, state_version, "
    "game_state, outcome, created_at, started_at, outcome_committed_at, finished_at, "
    "game_chat_binding_id, game_chat_id, game_chat_binding_revision, rng_commit"
)


def is_site_duel_id(game_id: object) -> bool:
    return bool(SITE_DUEL_ID_RE.fullmatch(str(game_id or "")))


def is_demo_duel_id(game_id: object) -> bool:
    return str(game_id or "").startswith("web-demo-")


def card_duel_is_unfinishable(game: Mapping[str, object]) -> bool:
    """Active 1×1 cards that cannot HMAC-settle: demo fixtures or site ids without a commit."""
    if str(game.get("game_type") or "") not in CARD_GAME_TYPES:
        return False
    if str(game.get("status") or "") != "active":
        return False
    if game.get("opponent_id") is None:
        return False
    if str(game.get("counterparty_kind") or "player") != "player":
        return False
    gid = str(game.get("game_id") or "")
    if is_demo_duel_id(gid):
        return True
    if is_site_duel_id(gid) and "rng_commit" in game and not str(game.get("rng_commit") or "").strip():
        return True
    return False


def assert_card_duel_joinable(game: Mapping[str, object]) -> None:
    """Waiting demo fixtures stay click-only. Already-stuck active demos abort on join/poll."""
    if str(game.get("game_type") or "") not in CARD_GAME_TYPES:
        return
    if not is_demo_duel_id(game.get("game_id")):
        return
    if str(game.get("status") or "") == "waiting" and game.get("opponent_id") is None:
        raise HTTPException(status_code=409, detail=DEMO_JOIN_DETAIL)


def is_site_card_duel(game: Mapping[str, object]) -> bool:
    if not is_site_duel_id(game.get("game_id")):
        return False
    if str(game.get("game_type") or "") not in CARD_GAME_TYPES:
        return False
    if str(game.get("status") or "") != "active":
        return False
    if game.get("opponent_id") is None:
        return False
    return str(game.get("counterparty_kind") or "player") == "player"


def merge_dealt_hand(stored: Sequence[str], house: Sequence[str]) -> list[str]:
    """Keep a live draw; only extend when the shoe still owes cards.

    Never shrink. A Telegram hit that already went past the house size stays.
    A site creator with two cards and no DM still receives the house third.
    """
    kept = [str(card) for card in stored if card]
    auto = [str(card) for card in house if card]
    if not kept:
        return auto
    if not auto:
        return kept
    shared = min(len(kept), len(auto))
    if kept[:shared] != auto[:shared]:
        return kept
    return kept if len(kept) >= len(auto) else auto


def pvp_card_outcome(
    game_type: str,
    creator_cards: Sequence[str],
    opponent_cards: Sequence[str],
    *,
    creator_id: int,
    opponent_id: int,
) -> dict[str, object]:
    creator = [str(card) for card in creator_cards]
    opponent = [str(card) for card in opponent_cards]
    creator_score = house_card_score(game_type, creator)
    opponent_score = house_card_score(game_type, opponent)
    result = compare_house_cards(game_type, creator, opponent)
    payload: dict[str, object] = {
        "kind": "draw" if result == "tie" else "winner",
        "reason": "site_card_auto",
        "creator_cards": creator,
        "opponent_cards": opponent,
        "creator_score": creator_score,
        "opponent_score": opponent_score,
        "decisions": {"creator": "auto", "opponent": "auto"},
    }
    if result == "player":
        payload["winner_id"] = int(creator_id)
        return payload
    if result == "house":
        payload["winner_id"] = int(opponent_id)
        return payload
    return payload


def _as_map(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _stored_side(card_rng: Mapping[str, object], side: str) -> list[str]:
    stored = card_rng.get(f"{side}_cards")
    if not isinstance(stored, list):
        return []
    return [str(card) for card in stored if isinstance(card, str) and card]


async def resolve_site_card_duel(conn, game: Mapping[str, object]) -> dict[str, object]:
    """Deal remaining house cards from the committed shoe and settle the pot."""
    if not is_site_card_duel(game):
        return dict(game)
    game_id = str(game["game_id"])
    game_type = str(game["game_type"])
    rng_row = await conn.fetchrow(
        """
        SELECT commit_hash, server_seed, status, client_seed, nonce
        FROM casino_house_rng_commits
        WHERE game_id = $1 AND game_type = $2
        FOR UPDATE
        """,
        game_id,
        game_type,
    )
    if not rng_row or not rng_row.get("server_seed"):
        raise HTTPException(status_code=409, detail="Card fairness commitment is missing")

    from casino_pvp_dice import touch_active_holds
    from routers.internal_casino import (
        CasinoGameIdRequest,
        CasinoGameOutcomeRequest,
        _rng_nonce,
        _rng_text,
        commit_game_outcome_with_conn,
        settle_committed_outcome_with_conn,
    )
    from casino_cards import DEFAULT_CLIENT_SEED

    await touch_active_holds(conn, game_id)

    seed = str(rng_row["server_seed"])
    rng_commit = str(rng_row["commit_hash"])
    client_seed = _rng_text(rng_row, "client_seed", DEFAULT_CLIENT_SEED)
    nonce = _rng_nonce(rng_row)
    data = _as_map(game.get("game_data"))
    card_rng = _as_map(data.get("card_rng"))
    creator_cards = merge_dealt_hand(
        _stored_side(card_rng, "creator"),
        deal_house_side_cards(
            game_type, seed, game_id, "creator", client_seed=client_seed, nonce=nonce
        ),
    )
    opponent_cards = merge_dealt_hand(
        _stored_side(card_rng, "opponent"),
        deal_house_side_cards(
            game_type, seed, game_id, "opponent", client_seed=client_seed, nonce=nonce
        ),
    )
    card_rng.update(
        {
            "algorithm": CARD_SHUFFLE_ALGORITHM,
            "commit": rng_commit,
            "pair_commit": pair_commit(seed),
            "client_seed": client_seed,
            "nonce": nonce,
            "creator_cards": creator_cards,
            "opponent_cards": opponent_cards,
        }
    )
    data["card_rng"] = card_rng
    state = _as_map(game.get("game_state"))
    state["cards_creator"] = creator_cards
    state["cards_opponent"] = opponent_cards
    state["decision_creator"] = state.get("decision_creator") or "auto"
    state["decision_opponent"] = state.get("decision_opponent") or "auto"
    await conn.execute(
        """
        UPDATE casino_games
        SET game_data = $2::jsonb, game_state = $3::jsonb, updated_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
        json.dumps(data, separators=(",", ":")),
        json.dumps(state, separators=(",", ":")),
    )
    if str(rng_row.get("status") or "") == "pending":
        await conn.execute(
            """
            UPDATE casino_house_rng_commits
            SET status = 'consumed', consumed_at = now()
            WHERE game_id = $1 AND status = 'pending'
            """,
            game_id,
        )
    outcome = pvp_card_outcome(
        game_type,
        creator_cards,
        opponent_cards,
        creator_id=int(game["creator_id"]),
        opponent_id=int(game["opponent_id"]),
    )
    winner_id = outcome.get("winner_id")
    if outcome["kind"] != "winner":
        winner_id = None
        outcome.pop("winner_id", None)
    await commit_game_outcome_with_conn(
        conn,
        CasinoGameOutcomeRequest(
            game_id=game_id,
            winner_id=int(winner_id) if winner_id is not None else None,
            expected_state_version=int(game.get("state_version") or 0),
            outcome=outcome,
        ),
    )
    await settle_committed_outcome_with_conn(conn, CasinoGameIdRequest(game_id=game_id))
    row = await conn.fetchrow(
        f"SELECT {_SITE_CARD_COLUMNS} FROM casino_games WHERE game_id = $1",
        game_id,
    )
    if row:
        return dict(row)
    leftover = dict(game)
    leftover["status"] = "finished"
    leftover["outcome"] = outcome
    leftover["game_data"] = data
    leftover["game_state"] = state
    return leftover


async def abort_unfinishable_card_duel(
    conn,
    game_id: str,
    *,
    actor_id: int | None = None,
    reason: str = REASON_UNFINISHABLE,
) -> dict[str, object] | None:
    """Refund every live hold and cancel a demo/no-commit card duel. No-op if finishable."""
    from casino_finance import lock_casino_game, lock_casino_users, money, release_unified_hold

    gid = str(game_id or "").strip()
    if not gid:
        return None
    await lock_casino_game(conn, gid)
    row = await conn.fetchrow(
        f"SELECT {_SITE_CARD_COLUMNS} FROM casino_games WHERE game_id = $1 FOR UPDATE",
        gid,
    )
    if not row:
        if actor_id is not None:
            raise HTTPException(status_code=404, detail="Дуэль не найдена")
        return None
    game = dict(row)
    if not card_duel_is_unfinishable(game):
        return None
    creator_id = int(game["creator_id"])
    opponent_raw = game.get("opponent_id")
    opponent_id = int(opponent_raw) if opponent_raw is not None else None
    if actor_id is not None:
        allowed = {creator_id}
        if opponent_id is not None:
            allowed.add(opponent_id)
        if int(actor_id) not in allowed:
            raise HTTPException(status_code=403, detail="Отменить может только участник")
    holds = await conn.fetch(
        """
        SELECT hold_id, telegram_id, game_id, amount_rub, ledger_order_ref, status
        FROM casino_balance_holds
        WHERE game_id = $1 AND status = 'active'
        FOR UPDATE
        """,
        gid,
    )
    user_ids = {creator_id}
    if opponent_id is not None:
        user_ids.add(opponent_id)
    for hold in holds:
        user_ids.add(int(hold["telegram_id"]))
    await lock_casino_users(conn, tuple(user_ids))
    stake = money(game["bet_rub"])
    for hold in holds:
        order_ref = str(hold.get("ledger_order_ref") or "")
        if not order_ref:
            continue
        await release_unified_hold(
            conn,
            user_id=int(hold["telegram_id"]),
            order_ref=order_ref,
            amount_rub=money(hold.get("amount_rub") or stake),
            note=f"Casino unfinishable card duel cancelled: {gid}",
        )
    await conn.execute(
        """
        UPDATE casino_balance_holds
        SET status = 'released', released_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        gid,
    )
    cancelled = await conn.fetchrow(
        """
        UPDATE casino_games
        SET status = 'cancelled', finished_at = now(), updated_at = now(),
            game_data = COALESCE(game_data, '{}'::jsonb)
                || jsonb_build_object('release_reason', $2::text)
        WHERE game_id = $1 AND status = 'active'
        RETURNING game_id, game_type, creator_id, opponent_id, bet_rub, status,
                  game_state, outcome, game_data, created_at
        """,
        gid,
        str(reason),
    )
    if not cancelled:
        return None
    return dict(cancelled)


async def abort_unfinishable_card_duels_due(conn, *, limit: int = 20) -> int:
    rows = await conn.fetch(
        """
        /* card:abort-unfinishable */
        SELECT game_id
        FROM casino_games
        WHERE status = 'active'
          AND opponent_id IS NOT NULL
          AND game_type = ANY($1::text[])
          AND COALESCE(counterparty_kind, 'player') = 'player'
          AND (
            game_id LIKE 'web-demo-%'
            OR (
              game_id ~ '^web-[0-9a-f]{12}$'
              AND COALESCE(rng_commit, '') = ''
            )
          )
        ORDER BY COALESCE(started_at, created_at)
        LIMIT $2
        """,
        list(CARD_GAME_TYPES),
        int(limit),
    )
    aborted = 0
    for row in rows:
        try:
            out = await abort_unfinishable_card_duel(conn, str(row["game_id"]))
        except HTTPException as exc:
            if int(exc.status_code) not in {403, 404, 409}:
                raise
            continue
        if out:
            aborted += 1
    return aborted


async def complete_site_card_duel_after_join(conn, game: Mapping[str, object]) -> dict[str, object]:
    if card_duel_is_unfinishable(game):
        aborted = await abort_unfinishable_card_duel(conn, str(game["game_id"]))
        return aborted or dict(game)
    if not is_site_card_duel(game):
        return dict(game)
    try:
        return await resolve_site_card_duel(conn, game)
    except HTTPException as exc:
        if int(exc.status_code) == 409 and "fairness" in str(exc.detail).lower():
            aborted = await abort_unfinishable_card_duel(conn, str(game["game_id"]))
            return aborted or dict(game)
        raise


async def complete_site_card_duel_if_due(conn, game_id: str) -> dict[str, object] | None:
    """Finish a stuck web card duel when anyone opens the room. Abort unfinishable demos."""
    gid = str(game_id or "").strip()
    if not is_site_duel_id(gid) and not is_demo_duel_id(gid):
        return None
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_SITE_CARD_COLUMNS}
                FROM casino_games
                WHERE game_id = $1
                  AND status = 'active'
                  AND game_type = ANY($2::text[])
                  AND opponent_id IS NOT NULL
                  AND COALESCE(counterparty_kind, 'player') = 'player'
                FOR UPDATE SKIP LOCKED
                """,
                gid,
                list(CARD_GAME_TYPES),
            )
            if not row:
                return None
            game = dict(row)
            if card_duel_is_unfinishable(game):
                return await abort_unfinishable_card_duel(conn, gid)
            return await resolve_site_card_duel(conn, game)
    except Exception:
        logger.exception("site card duel complete failed game_id=%s", game_id)
        return None

"""1×1 house baccarat/blackjack: HMAC shoe decides the hands, house settlement pays.

Cards are dealt from casino_cards HMAC shoes (creator = player, opponent = house).
Winner is the higher legal score, never a cub-style HMAC threshold. Money uses
calculate_house_settlement only: win × policy, loss ×0, tie ×1 (push).

Baccarat settles in one request (third card at ≤5). Blackjack deals 2+2, waits for
hit/stand, hides the dealer hole card, then the dealer draws to 17.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Mapping
from uuid import uuid4

from fastapi import HTTPException

from casino_cards import (
    CARD_GAME_TYPES,
    CARD_SHUFFLE_ALGORITHM,
    DEFAULT_CLIENT_SEED,
    MAX_CARD_HAND_SIZE,
    baccarat_hand_score,
    blackjack_hand_score,
    dealt_cards,
)
from casino_finance import (
    allocate_commission,
    calculate_house_settlement,
    casino_ledger_order_ref,
    commission_shares_for_rate,
    confirm_unified_hold,
    load_casino_settings,
    lock_casino_game,
    lock_casino_users,
    money,
    reserve_unified_funds,
)
from casino_wagering import commission_profile_for_player, commission_rate_for_player

HOUSE_CARD_GAME_TYPES = CARD_GAME_TYPES
BLACKJACK_HIT_UNTIL = 17
BACCARAT_THIRD_AT_OR_BELOW = 5
BLACKJACK_PHASE_PLAYER = "player_turn"
BLACKJACK_PHASE_FINISHED = "finished"
HouseCardResult = Literal["player", "house", "tie"]
BlackjackAction = Literal["hit", "stand"]


def is_house_card_game(game_type: str) -> bool:
    return game_type in HOUSE_CARD_GAME_TYPES


def house_card_score(game_type: str, cards: list[str]) -> int:
    if game_type == "blackjack":
        return blackjack_hand_score(cards)
    return baccarat_hand_score(cards)


def compare_house_cards(game_type: str, player_cards: list[str], house_cards: list[str]) -> HouseCardResult:
    """Same seat comparison as PvP card rooms. Both-bust blackjack is a push."""
    player = house_card_score(game_type, player_cards)
    house = house_card_score(game_type, house_cards)
    if game_type == "blackjack":
        player_ok = player <= 21
        house_ok = house <= 21
        if player_ok and house_ok:
            if player == house:
                return "tie"
            return "player" if player > house else "house"
        if player_ok:
            return "player"
        if house_ok:
            return "house"
        return "tie"
    if player == house:
        return "tie"
    return "player" if player > house else "house"


def sequential_blackjack_result(
    player_cards: list[str],
    house_cards: list[str],
    *,
    player_busted: bool,
) -> HouseCardResult:
    """Player bust loses immediately. Dealer never plays after a bust."""
    if player_busted:
        return "house"
    return compare_house_cards("blackjack", player_cards, house_cards)


def payout_multiplier_for_result(
    result: HouseCardResult,
    *,
    win_multiplier: Decimal,
) -> Decimal:
    if result == "player":
        return Decimal(str(win_multiplier))
    if result == "tie":
        return Decimal("1")
    return Decimal("0")


def deal_house_side_cards(
    game_type: str,
    seed: str,
    game_id: str,
    side: str,
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> list[str]:
    """Auto-draw from one committed shoe. Same rules as V2 bots: baccarat ≤5 → 3rd; BJ hit to 17."""
    two = dealt_cards(seed, game_id, side, 2, client_seed=client_seed, nonce=nonce)
    if game_type == "blackjack":
        size = 2
        cards = two
        while blackjack_hand_score(cards) < BLACKJACK_HIT_UNTIL and size < MAX_CARD_HAND_SIZE:
            size += 1
            cards = dealt_cards(seed, game_id, side, size, client_seed=client_seed, nonce=nonce)
        return cards
    if baccarat_hand_score(two) <= BACCARAT_THIRD_AT_OR_BELOW:
        return dealt_cards(seed, game_id, side, 3, client_seed=client_seed, nonce=nonce)
    return two


def deal_blackjack_initial(
    seed: str,
    game_id: str,
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> tuple[list[str], list[str]]:
    player = dealt_cards(seed, game_id, "creator", 2, client_seed=client_seed, nonce=nonce)
    house = dealt_cards(seed, game_id, "opponent", 2, client_seed=client_seed, nonce=nonce)
    return player, house


def hit_blackjack_hand(
    seed: str,
    game_id: str,
    side: str,
    current: list[str],
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> list[str]:
    size = len(current) + 1
    if size > MAX_CARD_HAND_SIZE:
        raise HTTPException(status_code=409, detail="Больше карт взять нельзя")
    nxt = dealt_cards(seed, game_id, side, size, client_seed=client_seed, nonce=nonce)
    if nxt[: len(current)] != current:
        raise HTTPException(status_code=409, detail="Колода раунда не совпала")
    return nxt


def public_house_cards(house_cards: list[str], *, revealed: bool) -> list[str]:
    if revealed or not house_cards:
        return _text_cards(house_cards)
    return [str(house_cards[0])]


def resolve_house_card_round(
    *,
    game_type: str,
    seed: str,
    game_id: str,
    client_seed: str,
    nonce: int,
    stake_rub: Decimal,
    win_multiplier: Decimal,
    commission_rate: Decimal,
    commission_cap_rub: Decimal = Decimal("0"),
    commission_min_rub: Decimal = Decimal("0"),
) -> dict[str, object]:
    if game_type not in HOUSE_CARD_GAME_TYPES:
        raise ValueError("not a house card game")
    player_cards = deal_house_side_cards(
        game_type, seed, game_id, "creator", client_seed=client_seed, nonce=nonce
    )
    house_cards = deal_house_side_cards(
        game_type, seed, game_id, "opponent", client_seed=client_seed, nonce=nonce
    )
    result = compare_house_cards(game_type, player_cards, house_cards)
    multiplier = payout_multiplier_for_result(result, win_multiplier=win_multiplier)
    settlement = calculate_house_settlement(
        stake_rub,
        multiplier,
        commission_rate,
        commission_cap_rub=commission_cap_rub,
        commission_min_rub=commission_min_rub,
    )
    return {
        "player_cards": player_cards,
        "house_cards": house_cards,
        "player_score": house_card_score(game_type, player_cards),
        "house_score": house_card_score(game_type, house_cards),
        "result": result,
        "payout_multiplier": multiplier,
        "settlement": settlement,
    }


def _text_cards(cards: list[str]) -> list[str]:
    return [str(card) for card in cards]


def _as_map(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _card_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(card) for card in value if isinstance(card, str) and card]


def _is_expired(expires_at: object) -> bool:
    if expires_at is None:
        return False
    if not isinstance(expires_at, datetime):
        return False
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        return expires_at.replace(tzinfo=timezone.utc) <= now
    return expires_at <= now


def _win_multiplier_from_data(game_data: Mapping[str, object]) -> Decimal:
    snapshot = _as_map(game_data.get("house_policy_snapshot"))
    return Decimal(str(snapshot.get("payout_multiplier") or "2"))


def _max_payout_from_data(game_data: Mapping[str, object], fallback: Decimal) -> Decimal:
    raw = game_data.get("max_payout_rub")
    if raw is None:
        return money(fallback)
    return money(raw)


def _shoe_fields(game_data: Mapping[str, object]) -> tuple[str, str, int]:
    card_rng = _as_map(game_data.get("card_rng"))
    seed = str(card_rng.get("server_seed") or "")
    client_seed = str(card_rng.get("client_seed") or DEFAULT_CLIENT_SEED)
    nonce = int(card_rng.get("nonce") or 0)
    if not seed:
        raise HTTPException(status_code=409, detail="Колода раунда не найдена")
    return seed, client_seed, nonce


def _blackjack_payload(
    *,
    ic,
    game_id: str,
    stake: Decimal,
    player_cards: list[str],
    house_cards: list[str],
    game_data: Mapping[str, object],
    phase: str,
    settlement=None,
    result: str | None = None,
    telegram_id: int | None = None,
    house_balance_rub: object = None,
    idempotent: bool = False,
) -> dict[str, object]:
    revealed = phase == BLACKJACK_PHASE_FINISHED
    visible_house = public_house_cards(house_cards, revealed=revealed)
    player_score = blackjack_hand_score(player_cards)
    house_score = blackjack_hand_score(house_cards if revealed else visible_house)
    card_rng = _as_map(game_data.get("card_rng"))
    rng: dict[str, object] = {
        "algorithm": str(card_rng.get("algorithm") or CARD_SHUFFLE_ALGORITHM),
        "commit": str(card_rng.get("commit") or ""),
        "nonce": int(card_rng.get("nonce") or 0),
        "client_seed": str(card_rng.get("client_seed") or DEFAULT_CLIENT_SEED),
        "player_cards": _text_cards(player_cards),
        "house_cards": visible_house,
        "player_score": player_score,
        "house_score": house_score,
    }
    if revealed:
        rng["seed"] = str(card_rng.get("server_seed") or "")
        rng["result"] = str(result or "")
        rng["house_cards"] = _text_cards(house_cards)
    actions: list[str] = []
    if phase == BLACKJACK_PHASE_PLAYER and player_score < 21:
        actions = ["hit", "stand"]
    kind = "pending"
    if revealed and result == "player":
        kind = "win"
    elif revealed and result == "tie":
        kind = "tie"
    elif revealed:
        kind = "loss"
    outcome: dict[str, object] = {
        "kind": kind,
        "player_cards": _text_cards(player_cards),
        "house_cards": visible_house if not revealed else _text_cards(house_cards),
        "player_score": player_score,
        "house_score": house_score,
    }
    if revealed:
        outcome["winner_id"] = telegram_id if result == "player" else None
    payout = settlement.payout if settlement is not None else Decimal("0")
    commission = settlement.commission if settlement is not None else Decimal("0")
    payload: dict[str, object] = {
        "success": True,
        "idempotent": bool(idempotent),
        "game_id": game_id,
        "game_type": "blackjack",
        "phase": phase,
        "actions": actions,
        "outcome": outcome,
        "stake_rub": ic._text_money(stake),
        "commission_rub": ic._text_money(commission),
        "payout_rub": ic._text_money(payout),
        "player_cards": _text_cards(player_cards),
        "house_cards": visible_house if not revealed else _text_cards(house_cards),
        "house_up": str(house_cards[0]) if house_cards else "",
        "house_hidden": 0 if revealed else 1,
        "player_score": player_score,
        "house_score": house_score,
        "rng": rng,
    }
    if house_balance_rub is not None:
        payload["house_balance_rub"] = ic._text_money(house_balance_rub)
    return payload


async def _load_open_blackjack(conn, telegram_id: int):
    return await conn.fetchrow(
        """
        SELECT id, game_id, creator_id, bet_rub, payout_rub, creator_hold_id, status,
               house_account_id, robot_profile_id, house_policy_id, rng_commit, rng_nonce,
               game_data, started_at
        FROM casino_games
        WHERE creator_id = $1 AND game_type = 'blackjack' AND status = 'active'
          AND counterparty_kind = 'house_robot'
        ORDER BY started_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        telegram_id,
    )


async def _hold_expired(conn, game_id: str) -> bool:
    hold = await conn.fetchrow(
        """
        SELECT expires_at FROM casino_balance_holds
        WHERE game_id = $1 AND role = 'player'
        ORDER BY id DESC
        LIMIT 1
        """,
        game_id,
    )
    if not hold:
        return False
    return _is_expired(hold["expires_at"])


async def play_house_cards_with_conn(
    conn,
    *,
    game_type: str,
    telegram_id: int,
    stake_rub: Decimal,
) -> dict[str, object]:
    """Web 1×1 vs house. Bankroll is the cub house_robot account, never a fake user."""
    if game_type not in HOUSE_CARD_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Эта игра не ставится против казино картами")
    from casino_wallet import assert_real_money_only

    await assert_real_money_only(conn, telegram_id)
    await lock_casino_users(conn, (telegram_id,))
    if game_type == "blackjack":
        existing = await _load_open_blackjack(conn, telegram_id)
        if existing:
            await lock_casino_game(conn, str(existing["game_id"]))
            return await _resume_blackjack_with_conn(conn, existing, telegram_id=telegram_id)
    game_id = str(uuid4())
    await lock_casino_game(conn, game_id)
    stake = money(stake_rub)

    settings_snapshot = await load_casino_settings(conn)
    commission_rate = await commission_rate_for_player(conn, telegram_id)
    commission_profile, _ = await commission_profile_for_player(conn, telegram_id)
    if not settings_snapshot.enabled_games.get(game_type, False):
        raise HTTPException(status_code=409, detail="Игра против казино выключена")

    from routers import internal_casino as ic

    policy = await conn.fetchrow(
        """
        SELECT id, payout_multiplier, win_probability, terms
        FROM casino_house_policies
        WHERE game_type = $1 AND is_active = TRUE
        FOR UPDATE
        """,
        game_type,
    )
    if not policy:
        policy = await conn.fetchrow(
            """
            SELECT id, payout_multiplier, win_probability, terms
            FROM casino_house_policies
            WHERE game_type = 'cub' AND is_active = TRUE
            FOR UPDATE
            """
        )
    profile = await conn.fetchrow(
        """
        SELECT rp.id, rp.account_id, rp.min_bet_rub, rp.max_bet_rub, rp.max_exposure_rub,
               ha.account_key, ha.balance_rub, ha.reserved_rub, ha.is_active AS account_active
        FROM casino_robot_profiles rp
        JOIN casino_house_accounts ha ON ha.id = rp.account_id
        WHERE rp.mode = 'house_robot' AND rp.is_active = TRUE
          AND ha.is_active = TRUE
          AND (rp.allowed_games ? $1 OR rp.allowed_games ? 'cub')
        ORDER BY CASE WHEN rp.allowed_games ? $1 THEN 0 ELSE 1 END, rp.id
        LIMIT 1
        FOR UPDATE OF rp, ha
        """,
        game_type,
    )
    if not policy or not profile or not bool(profile["account_active"]):
        raise HTTPException(status_code=409, detail="House robot is unavailable")
    if stake < money(profile["min_bet_rub"]) or stake > money(profile["max_bet_rub"]):
        raise HTTPException(status_code=409, detail="Stake is outside the robot limits")

    win_multiplier = Decimal(str(policy["payout_multiplier"]))
    ic._assert_stake_within_limits(
        settings_snapshot,
        game_type,
        stake,
        payout_multiplier=win_multiplier,
        bankroll_rub=money(profile["balance_rub"]),
    )
    max_settlement = calculate_house_settlement(
        stake,
        win_multiplier,
        commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    exposure_limit = money(profile["max_exposure_rub"])
    available = money(profile["balance_rub"]) - money(profile["reserved_rub"])
    if (exposure_limit > 0 and max_settlement.payout > exposure_limit) or available < max_settlement.payout:
        raise HTTPException(status_code=409, detail="House bankroll is insufficient")

    rng = await ic._load_or_create_card_commit(
        conn,
        game_id=game_id,
        game_type=game_type,
        telegram_id=telegram_id,
    )
    seed = str(rng["server_seed"])
    rng_commit = str(rng["rng_commit"])
    client_seed = str(rng.get("client_seed") or DEFAULT_CLIENT_SEED)
    nonce = int(rng["nonce"])
    if game_type == "blackjack":
        return await _deal_blackjack_with_conn(
            conn,
            ic=ic,
            game_id=game_id,
            telegram_id=telegram_id,
            stake=stake,
            seed=seed,
            rng_commit=rng_commit,
            pair_commit=str(rng.get("pair_commit") or ""),
            client_seed=client_seed,
            nonce=nonce,
            policy=policy,
            profile=profile,
            settings_snapshot=settings_snapshot,
            commission_rate=commission_rate,
            commission_profile=commission_profile,
            win_multiplier=win_multiplier,
            max_settlement=max_settlement,
        )

    resolved = resolve_house_card_round(
        game_type=game_type,
        seed=seed,
        game_id=game_id,
        client_seed=client_seed,
        nonce=nonce,
        stake_rub=stake,
        win_multiplier=win_multiplier,
        commission_rate=commission_rate,
        commission_cap_rub=settings_snapshot.commission_cap_rub,
        commission_min_rub=settings_snapshot.commission_min_rub,
    )
    settlement = resolved["settlement"]
    result = str(resolved["result"])
    player_cards = _text_cards(list(resolved["player_cards"]))
    house_cards = _text_cards(list(resolved["house_cards"]))
    player_score = int(resolved["player_score"])
    house_score = int(resolved["house_score"])

    hold_id = f"casino-{game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake)
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    game_data = {
        "house_policy_snapshot": {
            "policy_id": int(policy["id"]),
            "payout_multiplier": ic._text_money(win_multiplier),
            "source_game_type": str(game_type),
        },
        "pricing_snapshot": ic._pricing_snapshot_payload(
            commission_profile=commission_profile,
            commission_rate=commission_rate,
            creator_cut_percent=creator_cut_percent,
            referral_l1_percent=referral_l1_percent,
            referral_l2_percent=referral_l2_percent,
            commission_cap_rub=settings_snapshot.commission_cap_rub,
            commission_min_rub=settings_snapshot.commission_min_rub,
        ),
        "card_rng": {
            "algorithm": CARD_SHUFFLE_ALGORITHM,
            "commit": rng_commit,
            "pair_commit": str(rng.get("pair_commit") or ""),
            "client_seed": client_seed,
            "nonce": nonce,
            "creator_cards": player_cards,
            "opponent_cards": house_cards,
        },
        "rng_audit": {
            "algorithm": CARD_SHUFFLE_ALGORITHM,
            "commit": rng_commit,
            "seed": seed,
            "nonce": nonce,
            "client_seed": client_seed,
            "player_cards": player_cards,
            "house_cards": house_cards,
            "player_score": player_score,
            "house_score": house_score,
            "result": result,
        },
    }
    game = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_commit, rng_seed_reveal, rng_nonce,
            game_data, started_at
        ) VALUES (
            $1, $2, $3, $4, $4, $5, $6, 'active', 'house_robot', $7,
            $8, $9, $10, $11, $12, $13::jsonb, now()
        )
        RETURNING id
        """,
        game_id, game_type, telegram_id, stake, settlement.payout, hold_id,
        int(profile["account_id"]), int(profile["id"]), int(policy["id"]),
        rng_commit, seed, nonce, json.dumps(game_data, separators=(",", ":")),
    )
    if not game:
        raise HTTPException(status_code=409, detail="House card game creation conflicts")
    await _consume_card_commit(conn, game_id=game_id, telegram_id=telegram_id, game_type=game_type)
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, telegram_id, game_id, stake, order_ref,
    )
    reservation = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $2, updated_at = now()
        WHERE id = $1 AND balance_rub - reserved_rub >= $2
        RETURNING balance_rub, reserved_rub
        """,
        int(profile["account_id"]), max_settlement.payout,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="House bankroll is insufficient")
    await conn.execute(
        """
        INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
        VALUES ($1, $2, $3, $4)
        """,
        f"{game_type}-reserve-{game_id}", int(profile["account_id"]), game_id,
        max_settlement.payout,
    )
    await confirm_unified_hold(
        conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake,
        note=f"Casino {game_type} stake: {game_id}",
    )
    account = await _settle_house_card_money(
        conn,
        ic=ic,
        game_pk=int(game["id"]),
        game_id=game_id,
        game_type=game_type,
        telegram_id=telegram_id,
        stake=stake,
        settlement=settlement,
        result=result,
        player_cards=player_cards,
        house_cards=house_cards,
        player_score=player_score,
        house_score=house_score,
        game_data=game_data,
        account_id=int(profile["account_id"]),
        reserved_payout=max_settlement.payout,
        hold_id=hold_id,
        seed=seed,
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    won = result == "player"
    outcome = {
        "kind": "win" if won else ("tie" if result == "tie" else "loss"),
        "winner_id": telegram_id if won else None,
        "player_cards": player_cards,
        "house_cards": house_cards,
        "player_score": player_score,
        "house_score": house_score,
    }
    return {
        "success": True,
        "idempotent": False,
        "game_id": game_id,
        "game_type": game_type,
        "phase": BLACKJACK_PHASE_FINISHED,
        "outcome": outcome,
        "stake_rub": ic._text_money(stake),
        "commission_rub": ic._text_money(settlement.commission),
        "payout_rub": ic._text_money(settlement.payout),
        "house_balance_rub": ic._text_money(account["balance_rub"]),
        "player_cards": player_cards,
        "house_cards": house_cards,
        "player_score": player_score,
        "house_score": house_score,
        "rng": game_data["rng_audit"],
    }


async def _consume_card_commit(conn, *, game_id: str, telegram_id: int, game_type: str) -> None:
    consumed = await conn.execute(
        """
        UPDATE casino_house_rng_commits
        SET status = 'consumed', consumed_at = now()
        WHERE game_id = $1 AND telegram_id = $2 AND game_type = $3
          AND status = 'pending'
        """,
        game_id,
        telegram_id,
        game_type,
    )
    if consumed != "UPDATE 1":
        raise HTTPException(status_code=409, detail="Card fairness commitment was already consumed")


async def _deal_blackjack_with_conn(
    conn,
    *,
    ic,
    game_id: str,
    telegram_id: int,
    stake: Decimal,
    seed: str,
    rng_commit: str,
    pair_commit: str,
    client_seed: str,
    nonce: int,
    policy,
    profile,
    settings_snapshot,
    commission_rate: Decimal,
    commission_profile,
    win_multiplier: Decimal,
    max_settlement,
) -> dict[str, object]:
    player_cards, house_cards = deal_blackjack_initial(
        seed, game_id, client_seed=client_seed, nonce=nonce
    )
    player_cards = _text_cards(player_cards)
    house_cards = _text_cards(house_cards)
    hold_id = f"casino-{game_id}-player"
    order_ref = casino_ledger_order_ref(hold_id)
    await reserve_unified_funds(conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake)
    creator_cut_percent, referral_l1_percent, referral_l2_percent = commission_shares_for_rate(
        settings_snapshot,
        profile=commission_profile,
        commission_rate=commission_rate,
    )
    game_data = {
        "phase": BLACKJACK_PHASE_PLAYER,
        "max_payout_rub": ic._text_money(max_settlement.payout),
        "house_policy_snapshot": {
            "policy_id": int(policy["id"]),
            "payout_multiplier": ic._text_money(win_multiplier),
            "source_game_type": "blackjack",
        },
        "pricing_snapshot": ic._pricing_snapshot_payload(
            commission_profile=commission_profile,
            commission_rate=commission_rate,
            creator_cut_percent=creator_cut_percent,
            referral_l1_percent=referral_l1_percent,
            referral_l2_percent=referral_l2_percent,
            commission_cap_rub=settings_snapshot.commission_cap_rub,
            commission_min_rub=settings_snapshot.commission_min_rub,
        ),
        "card_rng": {
            "algorithm": CARD_SHUFFLE_ALGORITHM,
            "commit": rng_commit,
            "pair_commit": pair_commit,
            "client_seed": client_seed,
            "nonce": nonce,
            "server_seed": seed,
            "creator_cards": player_cards,
            "opponent_cards": house_cards,
        },
        "rng_audit": {
            "algorithm": CARD_SHUFFLE_ALGORITHM,
            "commit": rng_commit,
            "nonce": nonce,
            "client_seed": client_seed,
            "player_cards": player_cards,
            "house_up": house_cards[0] if house_cards else "",
            "player_score": blackjack_hand_score(player_cards),
        },
    }
    game = await conn.fetchrow(
        """
        INSERT INTO casino_games (
            game_id, game_type, creator_id, bet_rub, settlement_base_rub, payout_rub,
            creator_hold_id, status, counterparty_kind, house_account_id,
            robot_profile_id, house_policy_id, rng_commit, rng_seed_reveal, rng_nonce,
            game_data, started_at
        ) VALUES (
            $1, 'blackjack', $2, $3, $3, $4, $5, 'active', 'house_robot', $6,
            $7, $8, $9, NULL, $10, $11::jsonb, now()
        )
        RETURNING id
        """,
        game_id, telegram_id, stake, Decimal("0"), hold_id,
        int(profile["account_id"]), int(profile["id"]), int(policy["id"]),
        rng_commit, nonce, json.dumps(game_data, separators=(",", ":")),
    )
    if not game:
        raise HTTPException(status_code=409, detail="House card game creation conflicts")
    await _consume_card_commit(conn, game_id=game_id, telegram_id=telegram_id, game_type="blackjack")
    await conn.execute(
        """
        INSERT INTO casino_balance_holds (
            hold_id, telegram_id, game_id, amount_rub, role, ledger_order_ref, status, expires_at
        ) VALUES ($1, $2, $3, $4, 'player', $5, 'active', now() + interval '2 hours')
        """,
        hold_id, telegram_id, game_id, stake, order_ref,
    )
    reservation = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET reserved_rub = reserved_rub + $2, updated_at = now()
        WHERE id = $1 AND balance_rub - reserved_rub >= $2
        RETURNING balance_rub, reserved_rub
        """,
        int(profile["account_id"]), max_settlement.payout,
    )
    if not reservation:
        raise HTTPException(status_code=409, detail="House bankroll is insufficient")
    await conn.execute(
        """
        INSERT INTO casino_house_reservations (reservation_key, account_id, game_id, amount_rub)
        VALUES ($1, $2, $3, $4)
        """,
        f"blackjack-reserve-{game_id}", int(profile["account_id"]), game_id,
        max_settlement.payout,
    )
    await confirm_unified_hold(
        conn, user_id=telegram_id, order_ref=order_ref, amount_rub=stake,
        note=f"Casino blackjack stake: {game_id}",
    )
    row = {
        "id": int(game["id"]),
        "game_id": game_id,
        "creator_id": telegram_id,
        "bet_rub": stake,
        "creator_hold_id": hold_id,
        "house_account_id": int(profile["account_id"]),
        "game_data": game_data,
    }
    if blackjack_hand_score(player_cards) >= 21:
        return await _finish_blackjack_with_conn(
            conn, row, telegram_id=telegram_id, action="stand", player_busted=False
        )
    return _blackjack_payload(
        ic=ic,
        game_id=game_id,
        stake=stake,
        player_cards=player_cards,
        house_cards=house_cards,
        game_data=game_data,
        phase=BLACKJACK_PHASE_PLAYER,
        telegram_id=telegram_id,
        idempotent=False,
    )


async def _resume_blackjack_with_conn(conn, row, *, telegram_id: int) -> dict[str, object]:
    if await _hold_expired(conn, str(row["game_id"])):
        return await _finish_blackjack_with_conn(
            conn, row, telegram_id=telegram_id, action="stand", player_busted=False
        )
    from routers import internal_casino as ic

    game_data = _as_map(row.get("game_data"))
    card_rng = _as_map(game_data.get("card_rng"))
    return _blackjack_payload(
        ic=ic,
        game_id=str(row["game_id"]),
        stake=money(row["bet_rub"]),
        player_cards=_card_list(card_rng.get("creator_cards")),
        house_cards=_card_list(card_rng.get("opponent_cards")),
        game_data=game_data,
        phase=BLACKJACK_PHASE_PLAYER,
        telegram_id=telegram_id,
        idempotent=True,
    )


async def load_pending_house_blackjack_with_conn(conn, *, telegram_id: int) -> dict[str, object] | None:
    await lock_casino_users(conn, (telegram_id,))
    existing = await _load_open_blackjack(conn, telegram_id)
    if not existing:
        return None
    await lock_casino_game(conn, str(existing["game_id"]))
    return await _resume_blackjack_with_conn(conn, existing, telegram_id=telegram_id)


async def act_house_blackjack_with_conn(
    conn,
    *,
    telegram_id: int,
    game_id: str,
    action: str,
) -> dict[str, object]:
    if action not in {"hit", "stand"}:
        raise HTTPException(status_code=400, detail="Нужно добрать или оставить")
    await lock_casino_users(conn, (telegram_id,))
    await lock_casino_game(conn, game_id)
    row = await conn.fetchrow(
        """
        SELECT id, game_id, creator_id, bet_rub, payout_rub, creator_hold_id, status,
               house_account_id, robot_profile_id, house_policy_id, rng_commit, rng_nonce,
               game_data, started_at
        FROM casino_games
        WHERE game_id = $1 AND game_type = 'blackjack' AND creator_id = $2
          AND status = 'active' AND counterparty_kind = 'house_robot'
        FOR UPDATE
        """,
        game_id,
        telegram_id,
    )
    if not row:
        raise HTTPException(status_code=409, detail="Раунд блэкджека уже закрыт")
    if await _hold_expired(conn, game_id):
        return await _finish_blackjack_with_conn(
            conn, row, telegram_id=telegram_id, action="stand", player_busted=False
        )
    game_data = _as_map(row.get("game_data"))
    if str(game_data.get("phase") or "") != BLACKJACK_PHASE_PLAYER:
        raise HTTPException(status_code=409, detail="Сейчас нельзя брать карту")
    card_rng = _as_map(game_data.get("card_rng"))
    player_cards = _card_list(card_rng.get("creator_cards"))
    house_cards = _card_list(card_rng.get("opponent_cards"))
    if len(player_cards) < 2 or len(house_cards) < 2:
        raise HTTPException(status_code=409, detail="Раздача ещё не готова")
    if blackjack_hand_score(player_cards) >= 21:
        return await _finish_blackjack_with_conn(
            conn, row, telegram_id=telegram_id, action="stand", player_busted=False
        )
    if action == "stand":
        return await _finish_blackjack_with_conn(
            conn, row, telegram_id=telegram_id, action="stand", player_busted=False
        )
    seed, client_seed, nonce = _shoe_fields(game_data)
    player_cards = hit_blackjack_hand(
        seed, game_id, "creator", player_cards, client_seed=client_seed, nonce=nonce
    )
    card_rng["creator_cards"] = _text_cards(player_cards)
    game_data["card_rng"] = card_rng
    audit = _as_map(game_data.get("rng_audit"))
    audit["player_cards"] = _text_cards(player_cards)
    audit["player_score"] = blackjack_hand_score(player_cards)
    game_data["rng_audit"] = audit
    score = blackjack_hand_score(player_cards)
    if score > 21:
        return await _finish_blackjack_with_conn(
            conn, {**dict(row), "game_data": game_data},
            telegram_id=telegram_id, action="hit", player_busted=True,
        )
    await conn.execute(
        """
        UPDATE casino_games
        SET game_data = $2::jsonb, updated_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
        json.dumps(game_data, separators=(",", ":")),
    )
    if score == 21:
        return await _finish_blackjack_with_conn(
            conn, {**dict(row), "game_data": game_data},
            telegram_id=telegram_id, action="hit", player_busted=False,
        )
    from routers import internal_casino as ic

    return _blackjack_payload(
        ic=ic,
        game_id=game_id,
        stake=money(row["bet_rub"]),
        player_cards=player_cards,
        house_cards=house_cards,
        game_data=game_data,
        phase=BLACKJACK_PHASE_PLAYER,
        telegram_id=telegram_id,
        idempotent=False,
    )


async def _finish_blackjack_with_conn(
    conn,
    row,
    *,
    telegram_id: int,
    action: str,
    player_busted: bool,
) -> dict[str, object]:
    from routers import internal_casino as ic

    game_id = str(row["game_id"])
    game_data = _as_map(row.get("game_data"))
    card_rng = _as_map(game_data.get("card_rng"))
    player_cards = _card_list(card_rng.get("creator_cards"))
    house_cards = _card_list(card_rng.get("opponent_cards"))
    seed, client_seed, nonce = _shoe_fields(game_data)
    if not player_busted:
        house_cards = deal_house_side_cards(
            "blackjack", seed, game_id, "opponent", client_seed=client_seed, nonce=nonce
        )
    player_cards = _text_cards(player_cards)
    house_cards = _text_cards(house_cards)
    result = sequential_blackjack_result(player_cards, house_cards, player_busted=player_busted)
    win_multiplier = _win_multiplier_from_data(game_data)
    pricing = _as_map(game_data.get("pricing_snapshot"))
    commission_rate = Decimal(str(pricing.get("commission_rate") or "0"))
    stake = money(row["bet_rub"])
    settlement = calculate_house_settlement(
        stake,
        payout_multiplier_for_result(result, win_multiplier=win_multiplier),
        commission_rate,
        commission_cap_rub=ic._snapshot_amount(pricing, "commission_cap_rub") if pricing else Decimal("0"),
        commission_min_rub=ic._snapshot_amount(pricing, "commission_min_rub") if pricing else Decimal("0"),
    )
    player_score = blackjack_hand_score(player_cards)
    house_score = blackjack_hand_score(house_cards)
    card_rng["creator_cards"] = player_cards
    card_rng["opponent_cards"] = house_cards
    game_data["card_rng"] = card_rng
    game_data["phase"] = BLACKJACK_PHASE_FINISHED
    game_data["rng_audit"] = {
        "algorithm": CARD_SHUFFLE_ALGORITHM,
        "commit": str(card_rng.get("commit") or ""),
        "seed": seed,
        "nonce": nonce,
        "client_seed": client_seed,
        "player_cards": player_cards,
        "house_cards": house_cards,
        "player_score": player_score,
        "house_score": house_score,
        "result": result,
        "action": action,
    }
    reserved = _max_payout_from_data(game_data, settlement.payout if result == "player" else stake)
    account = await _settle_house_card_money(
        conn,
        ic=ic,
        game_pk=int(row["id"]),
        game_id=game_id,
        game_type="blackjack",
        telegram_id=telegram_id,
        stake=stake,
        settlement=settlement,
        result=result,
        player_cards=player_cards,
        house_cards=house_cards,
        player_score=player_score,
        house_score=house_score,
        game_data=game_data,
        account_id=int(row["house_account_id"]),
        reserved_payout=reserved,
        hold_id=str(row["creator_hold_id"]),
        seed=seed,
    )
    from casino_level_bonus import maybe_grant_reached_level_bonuses

    await maybe_grant_reached_level_bonuses(conn, telegram_id)
    return _blackjack_payload(
        ic=ic,
        game_id=game_id,
        stake=stake,
        player_cards=player_cards,
        house_cards=house_cards,
        game_data=game_data,
        phase=BLACKJACK_PHASE_FINISHED,
        settlement=settlement,
        result=result,
        telegram_id=telegram_id,
        house_balance_rub=account["balance_rub"],
        idempotent=False,
    )


async def _settle_house_card_money(
    conn,
    *,
    ic,
    game_pk: int,
    game_id: str,
    game_type: str,
    telegram_id: int,
    stake: Decimal,
    settlement,
    result: str,
    player_cards: list[str],
    house_cards: list[str],
    player_score: int,
    house_score: int,
    game_data: dict[str, object],
    account_id: int,
    reserved_payout: Decimal,
    hold_id: str,
    seed: str,
):
    won = result == "player"
    if settlement.payout > 0:
        await ic._credit_winner(
            conn, game_id=game_id, winner_id=telegram_id, payout_rub=settlement.payout
        )
    account = await conn.fetchrow(
        """
        UPDATE casino_house_accounts
        SET balance_rub = balance_rub + $2 - $3,
            reserved_rub = reserved_rub - $4,
            updated_at = now()
        WHERE id = $1 AND reserved_rub >= $4
        RETURNING balance_rub, reserved_rub
        """,
        account_id, stake, settlement.payout, reserved_payout,
    )
    if not account:
        raise HTTPException(status_code=409, detail="House reservation conflicts")
    if result != "tie":
        casino_creator_account = await ic._resolve_active_creator_account(conn)
        referral_l1_id, referral_l2_id = await ic._resolve_loser_referrals(conn, telegram_id)
        pricing_snapshot = _as_map(game_data.get("pricing_snapshot"))
        allocations = allocate_commission(
            stake,
            commission_rate=pricing_snapshot["commission_rate"],
            creator_percent=pricing_snapshot["creator_cut_percent"],
            referral_l1_percent=pricing_snapshot["referral_l1_percent"],
            referral_l2_percent=pricing_snapshot["referral_l2_percent"],
            has_creator=casino_creator_account is not None,
            has_referral_l1=referral_l1_id is not None,
            has_referral_l2=referral_l2_id is not None,
            commission_cap_rub=ic._snapshot_amount(pricing_snapshot, "commission_cap_rub"),
            commission_min_rub=ic._snapshot_amount(pricing_snapshot, "commission_min_rub"),
        )
        await ic._record_commissions(
            conn,
            game_pk=game_pk,
            game_id=game_id,
            casino_creator_account=casino_creator_account,
            referral_l1_id=referral_l1_id,
            referral_l2_id=referral_l2_id,
            allocations=allocations,
        )
    outcome = {
        "kind": "win" if won else ("tie" if result == "tie" else "loss"),
        "winner_id": telegram_id if won else None,
        "player_cards": player_cards,
        "house_cards": house_cards,
        "player_score": player_score,
        "house_score": house_score,
    }
    await conn.execute(
        """
        INSERT INTO casino_house_ledger (
            account_id, game_id, entry_key, entry_type, amount_rub, balance_after_rub, reason
        ) VALUES ($1, $2, $3, 'game_settlement', $4, $5, $6)
        """,
        account_id, game_id, f"{game_type}-settlement-{game_id}",
        settlement.house_delta, money(account["balance_rub"]),
        f"{game_type} {result} settlement",
    )
    await conn.execute(
        """
        UPDATE casino_house_reservations SET status = 'settled', settled_at = now()
        WHERE game_id = $1 AND status = 'active'
        """,
        game_id,
    )
    await conn.execute(
        """
        UPDATE casino_balance_holds SET status = 'confirmed', confirmed_at = now()
        WHERE hold_id = $1 AND status = 'active'
        """,
        hold_id,
    )
    await conn.execute(
        """
        UPDATE casino_games
        SET status = 'finished', winner_id = $2, outcome = $3::jsonb,
            commission_rub = $4, payout_rub = $5, rng_seed_reveal = $6,
            game_data = $7::jsonb, finished_at = now(), updated_at = now()
        WHERE game_id = $1
        """,
        game_id, telegram_id if won else None,
        json.dumps(outcome, separators=(",", ":")), settlement.commission,
        settlement.payout, seed, json.dumps(game_data, separators=(",", ":")),
    )
    return account

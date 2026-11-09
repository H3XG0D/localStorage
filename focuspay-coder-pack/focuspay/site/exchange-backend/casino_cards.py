"""Deterministic 52-card shoes for baccarat and blackjack.

The bot must not shuffle. Callers commit SHA-256(seed:game_id) before the stake,
deal from HMAC-SHA256 Fisher–Yates shoes keyed by client_seed:nonce:cursor, and
reveal the seed after the round.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Sequence

CARD_GAME_TYPES = ("baccara", "blackjack")
FAIRNESS_GAME_TYPES = (*CARD_GAME_TYPES, "holdem")
HOLDEM_SHOE_SIDE = "holdem"
CARD_SHUFFLE_ALGORITHM = "HMAC-SHA256-fisher-yates-v2"
CARD_COMMIT_TTL = "48 hours"
MAX_CARD_HAND_SIZE = 12
DEFAULT_CLIENT_SEED = "focuspay"
CARD_SUITS = ("♠", "♥", "♦", "♣")
CARD_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
STANDARD_DECK = tuple(f"{rank}{suit}" for suit in CARD_SUITS for rank in CARD_RANKS)
STANDARD_CARD_SET = frozenset(STANDARD_DECK)
LEGACY_SHOE_SIDES = ("creator", "opponent")
SEAT_SIDES = tuple(f"seat{n}" for n in range(1, 7))
TIE_BREAK_SIDES = tuple(f"seat{n}_tb{r}" for n in range(1, 7) for r in range(1, 6))
SHOE_SIDES = LEGACY_SHOE_SIDES + SEAT_SIDES
_SHOE_SIDE_RE = re.compile(r"^(creator|opponent|seat[1-6](?:_tb[1-5])?)$")


def is_valid_shoe_side(side: str) -> bool:
    return bool(_SHOE_SIDE_RE.fullmatch(side or ""))


def is_standard_card(card: str) -> bool:
    return card in STANDARD_CARD_SET


def card_rank(card: str) -> str:
    text = str(card or "").strip()
    if len(text) < 2:
        return ""
    return text[:-1]


def baccarat_card_value(card: str) -> int:
    """Baccarat pip: A=1, 2–9 face, 10/J/Q/K=0."""
    rank = card_rank(card)
    if rank in {"10", "J", "Q", "K"}:
        return 0
    if rank == "A":
        return 1
    try:
        number = int(rank)
    except ValueError:
        return 0
    return number if 2 <= number <= 9 else 0


def baccarat_hand_score(cards: Sequence[str]) -> int:
    return sum(baccarat_card_value(card) for card in cards) % 10


def blackjack_card_value(card: str) -> int:
    """List value for one card. Ace counts as 11; the hand scorer may reduce it."""
    rank = card_rank(card)
    if rank in {"10", "J", "Q", "K"}:
        return 10
    if rank == "A":
        return 11
    try:
        return int(rank)
    except ValueError:
        return 0


def blackjack_hand_score(cards: Sequence[str]) -> int:
    total = 0
    aces = 0
    for card in cards:
        rank = card_rank(card)
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"10", "J", "Q", "K"}:
            total += 10
        else:
            try:
                total += int(rank)
            except ValueError:
                continue
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def pair_commit(server_seed: str) -> str:
    """Public hash of the current seed pair: SHA-256(server_seed)."""
    return hashlib.sha256(server_seed.encode("utf-8")).hexdigest()


def game_commit(server_seed: str, game_id: str) -> str:
    """Per-round hash shown before cards: SHA-256(server_seed:game_id)."""
    return hashlib.sha256(f"{server_seed}:{game_id}".encode("utf-8")).hexdigest()


def commits_match(left: str, right: str) -> bool:
    a = (left or "").strip().lower()
    b = (right or "").strip().lower()
    if not a or not b or len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def shoe_message(*, client_seed: str, nonce: int, game_id: str, side: str) -> str:
    """HMAC message prefix. Cursor (shuffle index) is appended inside hmac_shuffle."""
    return f"{client_seed}:{int(nonce)}:{game_id}:{side}"


def hmac_shuffle(seed: str, message: str) -> list[str]:
    """Shuffle a fresh 52-card deck with HMAC-SHA256 Fisher–Yates."""
    deck = list(STANDARD_DECK)
    key = seed.encode("utf-8")
    for index in range(len(deck) - 1, 0, -1):
        digest = hmac.new(key, f"{message}:{index}".encode("utf-8"), hashlib.sha256).digest()
        swap = int.from_bytes(digest, "big") % (index + 1)
        deck[index], deck[swap] = deck[swap], deck[index]
    return deck


def dealt_cards(
    seed: str,
    game_id: str,
    side: str,
    hand_size: int,
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> list[str]:
    """Cards popped from the end of the committed shoe, in deal order."""
    if not is_valid_shoe_side(side):
        raise ValueError("invalid shoe side")
    if hand_size < 1 or hand_size > len(STANDARD_DECK):
        raise ValueError("invalid hand size")
    deck = hmac_shuffle(
        seed,
        shoe_message(client_seed=client_seed, nonce=nonce, game_id=game_id, side=side),
    )
    return [deck[-offset] for offset in range(1, hand_size + 1)]


def holdem_shoe_message(*, client_seed: str, nonce: int, hand_id: str) -> str:
    """One shared shoe for a Hold'em hand. Not a per-seat baccarat shoe."""
    return f"{client_seed}:{int(nonce)}:{hand_id}:{HOLDEM_SHOE_SIDE}"


def holdem_shuffled_deck(
    seed: str,
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
    hand_id: str,
) -> list[str]:
    """HMAC-SHA256 Fisher–Yates shoe for one Hold'em hand (holes + board + burns)."""
    return hmac_shuffle(seed, holdem_shoe_message(client_seed=client_seed, nonce=nonce, hand_id=hand_id))


def verify_holdem_round(
    *,
    server_seed: str,
    client_seed: str,
    nonce: int,
    hand_id: str,
    commit: str,
    seat_order: list[int] | None = None,
    expected_board: list[str] | None = None,
) -> dict[str, object]:
    """Reproduce the shared Hold'em shoe. Does not use per-seat baccarat shoes."""
    from casino_holdem import deal_holdem

    computed_commit = game_commit(server_seed, hand_id)
    commit_ok = commits_match(computed_commit, commit)
    deck = holdem_shuffled_deck(
        server_seed, client_seed=client_seed, nonce=nonce, hand_id=hand_id
    )
    order = [int(num) for num in (seat_order or [1, 2])]
    holes, burns, board = deal_holdem(deck, order)
    board_ok = True
    if expected_board is not None:
        board_ok = list(expected_board) == list(board)
    return {
        "matches": bool(commit_ok and board_ok),
        "commit_matches": commit_ok,
        "cards_match": board_ok,
        "computed_commit": computed_commit,
        "algorithm": CARD_SHUFFLE_ALGORITHM,
        "client_seed": client_seed,
        "nonce": int(nonce),
        "game_id": hand_id,
        "holes": {str(num): list(cards) for num, cards in holes.items()},
        "burns": list(burns),
        "board": list(board),
        "cards": {"holdem": list(board)},
    }


def verify_card_round(
    *,
    server_seed: str,
    client_seed: str,
    nonce: int,
    game_id: str,
    commit: str,
    side: str | None = None,
    hand_size: int | None = None,
    expected_cards: list[str] | None = None,
) -> dict[str, object]:
    """Reproduce a committed shoe. matches is False if the seed does not hash to commit."""
    computed_commit = game_commit(server_seed, game_id)
    commit_ok = commits_match(computed_commit, commit)
    size = hand_size if hand_size is not None else (len(expected_cards) if expected_cards else 2)
    if size < 1 or size > MAX_CARD_HAND_SIZE:
        raise ValueError("invalid hand size")
    reproduce_sides = list(SHOE_SIDES)
    if side and is_valid_shoe_side(side) and side not in reproduce_sides:
        reproduce_sides.append(side)
    reproduced: dict[str, list[str]] = {}
    for shoe_side in reproduce_sides:
        reproduced[shoe_side] = dealt_cards(
            server_seed,
            game_id,
            shoe_side,
            size,
            client_seed=client_seed,
            nonce=nonce,
        )
    cards_ok = True
    if expected_cards is not None:
        if not side or not is_valid_shoe_side(side):
            cards_ok = False
        else:
            cards_ok = list(expected_cards) == reproduced[side]
    return {
        "matches": bool(commit_ok and cards_ok),
        "commit_matches": commit_ok,
        "cards_match": cards_ok,
        "computed_commit": computed_commit,
        "algorithm": CARD_SHUFFLE_ALGORITHM,
        "client_seed": client_seed,
        "nonce": int(nonce),
        "game_id": game_id,
        "cards": reproduced,
    }

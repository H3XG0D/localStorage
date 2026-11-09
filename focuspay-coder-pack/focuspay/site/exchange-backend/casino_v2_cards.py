"""Equal-stake V2 card tables: HMAC shoe per seat, highest legal hand wins."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from casino_cards import DEFAULT_CLIENT_SEED, MAX_CARD_HAND_SIZE, baccarat_hand_score, blackjack_hand_score, dealt_cards
from casino_house_cards import BLACKJACK_HIT_UNTIL, deal_house_side_cards, hit_blackjack_hand

V2_CARD_GAME_TYPES = frozenset({"blackjack", "baccara"})
BACCARA_CARD_MS = 420
BACCARA_STREET_GAP_MS = 650
BACCARA_RESULT_BEAT_MS = 450
BLACKJACK_STREET_CARDS = 2


def seat_shoe_side(seat_no: int) -> str:
    return f"seat{int(seat_no)}"


def blackjack_rank(score: int) -> int:
    """Legal 0–21 ranks above a bust. All-bust ties at -1."""
    value = int(score)
    return value if 0 <= value <= 21 else -1


def deal_v2_card_hands(
    game_type: str,
    seed: str,
    table_id: str,
    seat_nos: Sequence[int],
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> dict[int, list[str]]:
    kind = "blackjack" if str(game_type) == "blackjack" else "baccara"
    hands: dict[int, list[str]] = {}
    for raw in seat_nos:
        seat_no = int(raw)
        side = seat_shoe_side(seat_no)
        if kind == "blackjack":
            hands[seat_no] = dealt_cards(
                seed,
                table_id,
                side,
                BLACKJACK_STREET_CARDS,
                client_seed=client_seed,
                nonce=nonce,
            )
        else:
            hands[seat_no] = deal_house_side_cards(
                kind,
                seed,
                table_id,
                side,
                client_seed=client_seed,
                nonce=nonce,
            )
    return hands


def deal_v2_blackjack_hands(
    seed: str,
    table_id: str,
    seat_nos: Sequence[int],
    *,
    client_seed: str = DEFAULT_CLIENT_SEED,
    nonce: int = 0,
) -> dict[int, list[str]]:
    return deal_v2_card_hands(
        "blackjack",
        seed,
        table_id,
        seat_nos,
        client_seed=client_seed,
        nonce=nonce,
    )


def blackjack_table_decision(hands: Mapping[int, Sequence[str]]) -> dict[str, object]:
    scores: dict[int, int] = {}
    ranks: dict[int, int] = {}
    for seat_no, cards in hands.items():
        score = blackjack_hand_score(list(cards))
        scores[int(seat_no)] = score
        ranks[int(seat_no)] = blackjack_rank(score)
    if not ranks:
        return {"kind": "tie_split", "winner_seat_nos": [], "scores": scores, "ranks": ranks}
    best = max(ranks.values())
    leaders = sorted(seat_no for seat_no, rank in ranks.items() if rank == best)
    kind = "winner" if len(leaders) == 1 else "tie_split"
    return {"kind": kind, "winner_seat_nos": leaders, "scores": scores, "ranks": ranks}


def baccarat_table_decision(hands: Mapping[int, Sequence[str]]) -> dict[str, object]:
    scores: dict[int, int] = {}
    for seat_no, cards in hands.items():
        scores[int(seat_no)] = baccarat_hand_score(list(cards))
    if not scores:
        return {"kind": "tie_split", "winner_seat_nos": [], "scores": scores}
    best = max(scores.values())
    leaders = sorted(seat_no for seat_no, score in scores.items() if score == best)
    kind = "winner" if len(leaders) == 1 else "tie_split"
    return {"kind": kind, "winner_seat_nos": leaders, "scores": scores}


def card_table_decision(game_type: str, hands: Mapping[int, Sequence[str]]) -> dict[str, object]:
    if str(game_type) == "blackjack":
        return blackjack_table_decision(hands)
    return baccarat_table_decision(hands)


def baccarat_street_steps(hands: Mapping[int, Sequence[str]]) -> list[tuple[int, int]]:
    seats = sorted(int(seat) for seat, cards in hands.items() if cards)
    if not seats:
        return []
    max_len = max(len(hands[seat]) for seat in seats)
    steps: list[tuple[int, int]] = []
    for index in range(max_len):
        for seat in seats:
            if len(hands[seat]) > index:
                steps.append((seat, index))
    return steps


def baccarat_reveal_ms(hands: Mapping[int, Sequence[str]]) -> int:
    steps = baccarat_street_steps(hands)
    total = 0
    for index, step in enumerate(steps):
        if index == 0:
            total += BACCARA_CARD_MS
        elif step[1] != steps[index - 1][1]:
            total += BACCARA_STREET_GAP_MS
        else:
            total += BACCARA_CARD_MS
    # BACCARA_RESULT_BEAT_MS stays on the client; settle when the last card is due.
    return total


def blackjack_street_hands(hands: Mapping[int, Sequence[str]]) -> dict[int, list[str]]:
    """Street animation uses only the first two cards per seat."""
    out: dict[int, list[str]] = {}
    for seat_no, cards in hands.items():
        out[int(seat_no)] = list(cards[:BLACKJACK_STREET_CARDS])
    return out


def blackjack_reveal_ms(hands: Mapping[int, Sequence[str]]) -> int:
    return baccarat_reveal_ms(blackjack_street_hands(hands))


def card_reveal_ms(game_type: str, hands: Mapping[int, Sequence[str]]) -> int:
    if str(game_type) == "blackjack":
        return blackjack_reveal_ms(hands)
    return baccarat_reveal_ms(hands)


def stood_seats_from_state(state: Mapping[str, object]) -> set[int]:
    raw = state.get("stood_seats")
    if not isinstance(raw, list):
        return set()
    out: set[int] = set()
    for item in raw:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return out


def blackjack_seat_done(cards: Sequence[str], *, stood: bool) -> bool:
    if stood:
        return True
    score = blackjack_hand_score(list(cards))
    return score >= 21 or len(cards) >= MAX_CARD_HAND_SIZE


def blackjack_all_done(hands: Mapping[int, Sequence[str]], stood_seats: set[int]) -> bool:
    if not hands:
        return False
    return all(blackjack_seat_done(hands[seat], stood=seat in stood_seats) for seat in hands)


def auto_hit_blackjack_to_seventeen(
    seed: str,
    table_id: str,
    cards: list[str],
    *,
    seat_no: int,
    nonce: int = 0,
) -> list[str]:
    hand = list(cards)
    while blackjack_hand_score(hand) < BLACKJACK_HIT_UNTIL and len(hand) < MAX_CARD_HAND_SIZE:
        hand = hit_blackjack_hand(
            seed,
            table_id,
            seat_shoe_side(seat_no),
            hand,
            nonce=nonce,
        )
    return hand


def next_card_table_action(
    game_type: str,
    hands: Mapping[int, Sequence[str]],
    *,
    now: datetime,
    dealt_at: datetime | None,
    roster_has_human: bool,
    phase: str = "",
    stood_seats: set[int] | None = None,
) -> dict[str, Any]:
    stood = stood_seats or set()
    if str(game_type) == "blackjack" and str(phase) == "hitting":
        scores = {int(seat): blackjack_hand_score(list(cards)) for seat, cards in hands.items()}
        if blackjack_all_done(hands, stood):
            decision = blackjack_table_decision(hands)
            winners = [int(seat) for seat in list(decision.get("winner_seat_nos") or [])]
            outcome_kind = str(decision.get("kind") or "tie_split")
            if outcome_kind == "winner":
                return {
                    "kind": "settle",
                    "outcome_kind": "winner",
                    "winners": winners,
                    "scores": decision.get("scores") or scores,
                }
            if not roster_has_human:
                return {
                    "kind": "settle",
                    "outcome_kind": "tie_split",
                    "winners": winners,
                    "scores": decision.get("scores") or scores,
                }
            return {"kind": "draw_choice", "winners": winners, "scores": decision.get("scores") or scores}
        return {"kind": "hitting", "scores": scores}

    decision = card_table_decision(game_type, hands)
    winners = [int(seat) for seat in list(decision.get("winner_seat_nos") or [])]
    kind = str(decision.get("kind") or "")
    if kind not in {"winner", "tie_split"} or not winners:
        kind = "tie_split"
        winners = sorted(int(seat) for seat in hands)
    delay_ms = card_reveal_ms(game_type, hands)
    reveal_until = dealt_at + timedelta(milliseconds=delay_ms) if dealt_at is not None else now
    if now < reveal_until:
        return {
            "kind": "wait_reveal",
            "reveal_until": reveal_until,
            "outcome_kind": kind,
            "winners": winners,
            "scores": decision.get("scores") or {},
        }
    if str(game_type) == "blackjack":
        scores = {int(seat): blackjack_hand_score(list(cards)) for seat, cards in hands.items()}
        return {"kind": "hitting", "scores": scores}
    if kind == "winner":
        return {"kind": "settle", "outcome_kind": "winner", "winners": winners, "scores": decision.get("scores") or {}}
    if str(game_type) != "blackjack":
        # Baccarat ties keep the pot and redeal. A 60s web "draw choice" then
        # tie_split takes 5% (100 ₽ → 95 ₽) and never redraws.
        return {"kind": "redeal", "winners": winners, "scores": decision.get("scores") or {}}
    if not roster_has_human:
        return {
            "kind": "settle",
            "outcome_kind": "tie_split",
            "winners": winners,
            "scores": decision.get("scores") or {},
        }
    return {"kind": "draw_choice", "winners": winners, "scores": decision.get("scores") or {}}


def json_hands(hands: Mapping[int, Sequence[str]]) -> dict[str, list[str]]:
    return {str(seat_no): [str(card) for card in cards] for seat_no, cards in hands.items()}


def json_scores(scores: Mapping[Any, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for seat_no, score in scores.items():
        try:
            out[str(int(seat_no))] = int(score)
        except (TypeError, ValueError):
            continue
    return out


def hands_from_state(state: Mapping[str, object]) -> dict[int, list[str]]:
    raw = state.get("hands")
    if not isinstance(raw, dict):
        return {}
    out: dict[int, list[str]] = {}
    for key, cards in raw.items():
        try:
            seat_no = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(cards, list):
            continue
        out[seat_no] = [str(card) for card in cards if card]
    return out

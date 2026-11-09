"""Pure No-Limit Texas Hold'em: 7-card ranker, shared-deck deal, betting FSM.

No I/O, no shuffle. Callers pass a committed HMAC shoe. Money uses casino_finance.money.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Iterable, Literal, Mapping, Sequence

from casino_finance import money

STREETS: tuple[str, ...] = ("preflop", "flop", "turn", "river")
BOARD_VISIBLE: dict[str, int] = {"preflop": 0, "flop": 3, "turn": 4, "river": 5, "showdown": 5, "complete": 5}
MIN_SEATS = 2
MAX_SEATS = 6
RANK_VALUE: dict[str, int] = {
    "A": 14,
    "K": 13,
    "Q": 12,
    "J": 11,
    "10": 10,
    "9": 9,
    "8": 8,
    "7": 7,
    "6": 6,
    "5": 5,
    "4": 4,
    "3": 3,
    "2": 2,
}
SUIT_VALUE: dict[str, int] = {"♠": 0, "♥": 1, "♦": 2, "♣": 3}
CATEGORY_NAME = (
    "high_card",
    "pair",
    "two_pair",
    "three_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "four_of_a_kind",
    "straight_flush",
)
ActionName = Literal["fold", "check", "call", "raise", "all_in"]


class HoldemError(ValueError):
    """Illegal action or table setup."""


def parse_card(face: str) -> tuple[int, int]:
    text = (face or "").strip()
    if text.startswith("10"):
        rank, suit = "10", text[2:]
    else:
        rank, suit = text[:1], text[1:]
    if rank not in RANK_VALUE or suit not in SUIT_VALUE:
        raise HoldemError(f"invalid card: {face}")
    return RANK_VALUE[rank], SUIT_VALUE[suit]


def _straight_high(ranks: Sequence[int]) -> int | None:
    uniq = sorted(set(ranks))
    if len(uniq) != 5:
        return None
    if uniq == [2, 3, 4, 5, 14]:
        return 5
    if uniq[-1] - uniq[0] == 4:
        return uniq[-1]
    return None


def rank_five(cards: Sequence[str]) -> tuple[int, ...]:
    """Higher tuple wins. Category is first element (0 high card … 8 straight flush)."""
    if len(cards) != 5:
        raise HoldemError("five cards required")
    parsed = [parse_card(card) for card in cards]
    ranks = sorted((item[0] for item in parsed), reverse=True)
    suits = [item[1] for item in parsed]
    flush = len(set(suits)) == 1
    counts = Counter(ranks)
    by_count = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    straight = _straight_high(ranks)
    if flush and straight:
        return (8, straight)
    if by_count[0][1] == 4:
        quad = by_count[0][0]
        kicker = next(rank for rank in ranks if rank != quad)
        return (7, quad, kicker)
    if by_count[0][1] == 3 and by_count[1][1] == 2:
        return (6, by_count[0][0], by_count[1][0])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight)
    if by_count[0][1] == 3:
        trips = by_count[0][0]
        kickers = tuple(rank for rank in ranks if rank != trips)
        return (3, trips, *kickers)
    if by_count[0][1] == 2 and by_count[1][1] == 2:
        high_pair = max(by_count[0][0], by_count[1][0])
        low_pair = min(by_count[0][0], by_count[1][0])
        kicker = next(rank for rank in ranks if rank != high_pair and rank != low_pair)
        return (2, high_pair, low_pair, kicker)
    if by_count[0][1] == 2:
        pair = by_count[0][0]
        kickers = tuple(rank for rank in ranks if rank != pair)
        return (1, pair, *kickers)
    return (0, *ranks)


def best_seven(cards: Sequence[str]) -> tuple[int, ...]:
    if len(cards) < 5:
        raise HoldemError("need at least five cards")
    if len(cards) == 5:
        return rank_five(cards)
    return max(rank_five(combo) for combo in combinations(cards, 5))


def hand_name(score: Sequence[int]) -> str:
    category = int(score[0]) if score else 0
    if 0 <= category < len(CATEGORY_NAME):
        return CATEGORY_NAME[category]
    return "high_card"


def rake_amount(pot: Decimal, percent: Decimal, cap: Decimal) -> Decimal:
    total = money(pot)
    if total <= 0:
        return money(0)
    raw = money(total * money(percent) / Decimal("100"))
    limit = money(cap)
    if limit > 0 and raw > limit:
        return limit
    return raw


@dataclass
class SeatState:
    seat_no: int
    stack: Decimal
    hole: tuple[str, str] | None = None
    street_bet: Decimal = Decimal("0.00")
    committed: Decimal = Decimal("0.00")
    folded: bool = False
    all_in: bool = False
    leaving: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "seat_no": self.seat_no,
            "stack": str(money(self.stack)),
            "hole": list(self.hole) if self.hole else None,
            "street_bet": str(money(self.street_bet)),
            "committed": str(money(self.committed)),
            "folded": self.folded,
            "all_in": self.all_in,
            "leaving": self.leaving,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "SeatState":
        hole = raw.get("hole")
        cards = tuple(str(card) for card in hole) if isinstance(hole, list) and len(hole) == 2 else None
        return cls(
            seat_no=int(raw["seat_no"]),
            stack=money(raw.get("stack") or 0),
            hole=cards,  # type: ignore[arg-type]
            street_bet=money(raw.get("street_bet") or 0),
            committed=money(raw.get("committed") or 0),
            folded=bool(raw.get("folded")),
            all_in=bool(raw.get("all_in")),
            leaving=bool(raw.get("leaving")),
        )


@dataclass
class SidePot:
    amount: Decimal
    eligible: list[int]

    def to_dict(self) -> dict[str, object]:
        return {"amount": str(money(self.amount)), "eligible": list(self.eligible)}


def cards_were_shown(raw: Mapping[str, object] | None) -> bool:
    """True only after a real showdown. Missing flag on old rows follows winner reason."""
    if not isinstance(raw, Mapping):
        return False
    if "cards_shown" in raw:
        return bool(raw.get("cards_shown"))
    if str(raw.get("street") or "") == "showdown":
        return True
    winners = raw.get("winners")
    rows = list(winners) if isinstance(winners, list) else []
    return any(isinstance(row, Mapping) and row.get("reason") == "showdown" for row in rows)


def hand_seed_public(cards_shown: bool, seed_revealed_at: object) -> bool:
    """Server seed leaves the table only after cards were shown and the row recorded it."""
    return bool(cards_shown) and seed_revealed_at is not None


@dataclass
class HandState:
    hand_id: str
    street: str
    button: int
    small_blind: Decimal
    big_blind: Decimal
    to_act: int | None = None
    current_bet: Decimal = Decimal("0.00")
    last_raise_size: Decimal = Decimal("0.00")
    last_aggressor: int | None = None
    acted: list[int] = field(default_factory=list)
    board_full: list[str] = field(default_factory=list)
    burns: list[str] = field(default_factory=list)
    seats: dict[int, SeatState] = field(default_factory=dict)
    winners: list[dict[str, object]] | None = None
    wagers: dict[int, str] = field(default_factory=dict)
    rake: Decimal = Decimal("0.00")
    version: int = 0
    cards_shown: bool = False
    board_visible: int | None = None

    @property
    def board(self) -> list[str]:
        if self.street == "complete" and not self.cards_shown:
            count = 0 if self.board_visible is None else int(self.board_visible)
            return list(self.board_full[:count])
        visible = BOARD_VISIBLE.get(self.street, 0)
        return list(self.board_full[:visible])

    def to_dict(self) -> dict[str, object]:
        return {
            "hand_id": self.hand_id,
            "street": self.street,
            "button": self.button,
            "small_blind": str(money(self.small_blind)),
            "big_blind": str(money(self.big_blind)),
            "to_act": self.to_act,
            "current_bet": str(money(self.current_bet)),
            "last_raise_size": str(money(self.last_raise_size)),
            "last_aggressor": self.last_aggressor,
            "acted": list(self.acted),
            "board_full": list(self.board_full),
            "burns": list(self.burns),
            "seats": {str(num): seat.to_dict() for num, seat in self.seats.items()},
            "winners": self.winners,
            "wagers": {str(num): amount for num, amount in self.wagers.items()},
            "rake": str(money(self.rake)),
            "version": self.version,
            "cards_shown": self.cards_shown,
            "board_visible": self.board_visible,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "HandState":
        seats_raw = raw.get("seats") or {}
        seats: dict[int, SeatState] = {}
        if isinstance(seats_raw, Mapping):
            for key, value in seats_raw.items():
                if isinstance(value, Mapping):
                    seat = SeatState.from_dict(value)
                    seats[seat.seat_no] = seat
        winners = raw.get("winners")
        wagers_raw = raw.get("wagers") or {}
        wagers = {int(k): str(v) for k, v in wagers_raw.items()} if isinstance(wagers_raw, Mapping) else {}
        return cls(
            hand_id=str(raw["hand_id"]),
            street=str(raw["street"]),
            button=int(raw["button"]),
            small_blind=money(raw.get("small_blind") or 0),
            big_blind=money(raw.get("big_blind") or 0),
            to_act=int(raw["to_act"]) if raw.get("to_act") is not None else None,
            current_bet=money(raw.get("current_bet") or 0),
            last_raise_size=money(raw.get("last_raise_size") or 0),
            last_aggressor=int(raw["last_aggressor"]) if raw.get("last_aggressor") is not None else None,
            acted=[int(item) for item in (raw.get("acted") or [])],
            board_full=[str(card) for card in (raw.get("board_full") or [])],
            burns=[str(card) for card in (raw.get("burns") or [])],
            seats=seats,
            winners=list(winners) if isinstance(winners, list) else None,
            wagers=wagers,
            rake=money(raw.get("rake") or 0),
            version=int(raw.get("version") or 0),
            cards_shown=cards_were_shown(raw),
            board_visible=int(raw["board_visible"]) if raw.get("board_visible") is not None else None,
        )


def _ordered_seats(seats: Iterable[int], start: int, *, include_start: bool = False) -> list[int]:
    ordered = sorted({int(num) for num in seats})
    if not ordered:
        return []
    if start not in ordered:
        nxt = next((num for num in ordered if num > start), ordered[0])
        idx = ordered.index(nxt)
        include_start = True
    else:
        idx = ordered.index(start)
    begin = 0 if include_start else 1
    size = len(ordered)
    return [ordered[(idx + offset) % size] for offset in range(begin, size + begin)]


def live_seats(state: HandState) -> list[int]:
    return sorted(num for num, seat in state.seats.items() if not seat.folded)


def actors(state: HandState) -> list[int]:
    return [num for num in live_seats(state) if not state.seats[num].all_in]


def next_actor(state: HandState, start: int, *, include_start: bool = False) -> int | None:
    for num in _ordered_seats(actors(state), start, include_start=include_start):
        return num
    return None


def pot_total(state: HandState) -> Decimal:
    return money(sum((seat.committed for seat in state.seats.values()), Decimal("0")))


def _put(seat: SeatState, amount: Decimal) -> Decimal:
    take = money(min(money(amount), money(seat.stack)))
    if take <= 0:
        if seat.stack <= 0:
            seat.all_in = True
        return money(0)
    seat.stack = money(seat.stack - take)
    seat.street_bet = money(seat.street_bet + take)
    seat.committed = money(seat.committed + take)
    if seat.stack <= 0:
        seat.stack = money(0)
        seat.all_in = True
    return take


def _reset_street(state: HandState) -> None:
    for seat in state.seats.values():
        seat.street_bet = money(0)
    state.current_bet = money(0)
    state.last_raise_size = money(state.big_blind)
    state.last_aggressor = None
    state.acted = []


def deal_holdem(deck: list[str], seat_order: Sequence[int]) -> tuple[dict[int, tuple[str, str]], list[str], list[str]]:
    """Pop from the end of a shuffled shoe. Returns holes, burns, 5 board cards."""
    if len(seat_order) < MIN_SEATS:
        raise HoldemError("need two players to deal")
    needed = 2 * len(seat_order) + 8
    if len(deck) < needed:
        raise HoldemError("shoe is short")
    holes: dict[int, list[str]] = {int(num): [] for num in seat_order}
    for _ in range(2):
        for num in seat_order:
            holes[int(num)].append(deck.pop())
    burns = [deck.pop()]
    flop = [deck.pop(), deck.pop(), deck.pop()]
    burns.append(deck.pop())
    turn = deck.pop()
    burns.append(deck.pop())
    river = deck.pop()
    packed = {num: (cards[0], cards[1]) for num, cards in holes.items()}
    return packed, burns, flop + [turn, river]


def start_hand(
    *,
    hand_id: str,
    stacks: Mapping[int, Decimal],
    button: int,
    small_blind: Decimal,
    big_blind: Decimal,
    deck: list[str],
) -> HandState:
    seated = sorted(int(num) for num, stack in stacks.items() if money(stack) > 0)
    if len(seated) < MIN_SEATS or len(seated) > MAX_SEATS:
        raise HoldemError("hand needs 2–6 stacks")
    if any(num < 1 or num > MAX_SEATS for num in seated):
        raise HoldemError("seat_no must be 1–6")
    sb_amt = money(small_blind)
    bb_amt = money(big_blind)
    if sb_amt <= 0 or bb_amt < sb_amt:
        raise HoldemError("blinds invalid")
    button_seat = int(button)
    if button_seat not in seated:
        button_seat = _ordered_seats(seated, button_seat, include_start=True)[0]
    if len(seated) == 2:
        sb_seat = button_seat
        bb_seat = _ordered_seats(seated, button_seat)[0]
    else:
        sb_seat = _ordered_seats(seated, button_seat)[0]
        bb_seat = _ordered_seats(seated, sb_seat)[0]
    deal_order = _ordered_seats(seated, button_seat)
    holes, burns, board = deal_holdem(deck, deal_order)
    seats = {
        num: SeatState(seat_no=num, stack=money(stacks[num]), hole=holes[num])
        for num in seated
    }
    state = HandState(
        hand_id=hand_id,
        street="preflop",
        button=button_seat,
        small_blind=sb_amt,
        big_blind=bb_amt,
        last_raise_size=bb_amt,
        board_full=board,
        burns=burns,
        seats=seats,
        version=1,
    )
    _put(seats[sb_seat], sb_amt)
    _put(seats[bb_seat], bb_amt)
    state.current_bet = max(seats[sb_seat].street_bet, seats[bb_seat].street_bet)
    first = _ordered_seats(seated, bb_seat)[0]
    state.to_act = next_actor(state, first, include_start=True)
    if state.to_act is None:
        _runout_and_showdown(state)
    return state


def legal_actions(state: HandState, seat_no: int | None = None) -> dict[str, object]:
    if state.street in {"showdown", "complete"} or state.to_act is None:
        return {"actions": [], "to_act": state.to_act, "call_rub": 0.0, "min_raise_to": 0.0, "max_raise_to": 0.0}
    acting = int(seat_no if seat_no is not None else state.to_act)
    if acting != state.to_act or acting not in state.seats:
        return {"actions": [], "to_act": state.to_act, "call_rub": 0.0, "min_raise_to": 0.0, "max_raise_to": 0.0}
    seat = state.seats[acting]
    to_call = money(max(Decimal("0"), state.current_bet - seat.street_bet))
    names: list[str] = ["fold"]
    if to_call <= 0:
        names.append("check")
    elif to_call > 0 and seat.stack > 0:
        names.append("call")
    min_raise_to = money(state.current_bet + state.last_raise_size)
    max_raise_to = money(seat.street_bet + seat.stack)
    if seat.stack > to_call:
        names.append("raise")
    if seat.stack > 0:
        names.append("all_in")
    return {
        "actions": names,
        "to_act": state.to_act,
        "call_rub": float(to_call),
        "min_raise_to": float(min_raise_to),
        "max_raise_to": float(max_raise_to),
        "current_bet_rub": float(money(state.current_bet)),
        "street_bet_rub": float(money(seat.street_bet)),
        "stack_rub": float(money(seat.stack)),
    }


def _advance_or_close(state: HandState) -> None:
    live = live_seats(state)
    if len(live) <= 1:
        _fold_win(state)
        return
    if _street_closed(state):
        _next_street_or_showdown(state)
        return
    assert state.to_act is not None
    nxt = next_actor(state, state.to_act)
    if nxt is None:
        _next_street_or_showdown(state)
        return
    state.to_act = nxt


def _street_closed(state: HandState) -> bool:
    live = live_seats(state)
    if len(live) <= 1:
        return True
    pending = actors(state)
    if not pending:
        return True
    if any(money(state.seats[num].street_bet) < state.current_bet for num in pending):
        return False
    if state.last_aggressor is None:
        return all(num in state.acted for num in pending)
    return state.last_aggressor in state.acted and all(
        money(state.seats[num].street_bet) == state.current_bet or state.seats[num].all_in
        for num in live
    )


def _next_street_or_showdown(state: HandState) -> None:
    if len(live_seats(state)) <= 1:
        _fold_win(state)
        return
    if not actors(state) or state.street == "river":
        _runout_and_showdown(state)
        return
    nxt = {"preflop": "flop", "flop": "turn", "turn": "river"}[state.street]
    state.street = nxt
    _reset_street(state)
    first = next_actor(state, state.button)
    state.to_act = first
    if first is None:
        _runout_and_showdown(state)
        return
    state.version += 1


def _runout_and_showdown(state: HandState) -> None:
    state.cards_shown = True
    state.board_visible = len(state.board_full)
    state.street = "showdown"
    state.to_act = None
    _reset_street(state)
    _showdown(state)
    state.street = "complete"
    state.version += 1


def _remember_dealt_board(state: HandState) -> None:
    if state.board_visible is None:
        state.board_visible = len(state.board)


def _fold_win(state: HandState) -> None:
    _remember_dealt_board(state)
    state.cards_shown = False
    live = live_seats(state)
    winner = live[0] if live else None
    total = pot_total(state)
    if winner is None:
        state.winners = []
        state.street = "complete"
        state.to_act = None
        state.version += 1
        return
    others_max = money(0)
    for num, seat in state.seats.items():
        if num == winner:
            continue
        if seat.committed > others_max:
            others_max = money(seat.committed)
    winner_seat = state.seats[winner]
    extra = money(max(Decimal("0"), winner_seat.committed - others_max))
    if extra > 0:
        winner_seat.committed = money(winner_seat.committed - extra)
        winner_seat.stack = money(winner_seat.stack + extra)
        total = money(total - extra)
    state.wagers = {num: str(money(seat.committed)) for num, seat in state.seats.items() if money(seat.committed) > 0}
    state.seats[winner].stack = money(state.seats[winner].stack + total)
    for seat in state.seats.values():
        seat.committed = money(0)
        seat.street_bet = money(0)
    state.winners = [{"seat_no": winner, "amount": str(total), "reason": "fold"}]
    state.street = "complete"
    state.to_act = None
    state.version += 1


def side_pots(state: HandState) -> list[SidePot]:
    contrib = {num: money(seat.committed) for num, seat in state.seats.items() if money(seat.committed) > 0}
    if not contrib:
        return []
    levels = sorted(set(contrib.values()))
    pots: list[SidePot] = []
    prev = money(0)
    for level in levels:
        step = money(level - prev)
        contributors = [num for num, amount in contrib.items() if amount >= level]
        amount = money(step * len(contributors))
        eligible = [num for num in contributors if not state.seats[num].folded]
        if amount > 0:
            pots.append(SidePot(amount=amount, eligible=eligible or contributors))
        prev = level
    return pots


def _showdown(state: HandState) -> None:
    scores: dict[int, tuple[int, ...]] = {}
    for num in live_seats(state):
        seat = state.seats[num]
        if not seat.hole:
            continue
        scores[num] = best_seven(list(seat.hole) + list(state.board_full))
    awarded: list[dict[str, object]] = []
    for pot in side_pots(state):
        eligible = [num for num in pot.eligible if num in scores]
        if not eligible:
            continue
        best = max(scores[num] for num in eligible)
        winners = [num for num in eligible if scores[num] == best]
        winners = _order_from_button(state, winners)
        share = money(pot.amount / len(winners))
        remainder = money(pot.amount - share * len(winners))
        for index, num in enumerate(winners):
            extra = money(share + (remainder if index == 0 else 0))
            state.seats[num].stack = money(state.seats[num].stack + extra)
            awarded.append(
                {
                    "seat_no": num,
                    "amount": str(extra),
                    "reason": "showdown",
                    "hand": hand_name(scores[num]),
                }
            )
    state.wagers = {num: str(money(seat.committed)) for num, seat in state.seats.items() if money(seat.committed) > 0}
    for seat in state.seats.values():
        seat.committed = money(0)
        seat.street_bet = money(0)
    state.winners = awarded


def _order_from_button(state: HandState, seats: Sequence[int]) -> list[int]:
    ordered = _ordered_seats(seats, state.button)
    return ordered or list(seats)


def apply_rake(state: HandState, percent: Decimal, cap: Decimal) -> Decimal:
    """Take rake from the collected pot after a completed hand. Call before recording stacks."""
    if state.street != "complete" or state.rake > 0:
        return money(state.rake)
    if not state.winners:
        return money(0)
    if any(row.get("reason") == "fold" for row in state.winners) and len(state.winners) == 1:
        collected = money(state.winners[0]["amount"])
    else:
        collected = money(sum((money(row["amount"]) for row in state.winners), Decimal("0")))
    taken = rake_amount(collected, percent, cap)
    if taken <= 0:
        return money(0)
    remaining = taken
    for row in reversed(state.winners):
        if remaining <= 0:
            break
        seat_no = int(row["seat_no"])
        won = money(row["amount"])
        cut = money(min(won, remaining))
        if cut <= 0:
            continue
        state.seats[seat_no].stack = money(state.seats[seat_no].stack - cut)
        row["amount"] = str(money(won - cut))
        remaining = money(remaining - cut)
    state.rake = money(taken - remaining)
    return state.rake


def apply_action(
    state: HandState,
    seat_no: int,
    action: str,
    amount: Decimal | None = None,
) -> HandState:
    if state.street in {"showdown", "complete"}:
        raise HoldemError("hand is over")
    if state.to_act is None or int(seat_no) != state.to_act:
        raise HoldemError("not your turn")
    seat = state.seats[int(seat_no)]
    if seat.folded or seat.all_in:
        raise HoldemError("seat cannot act")
    name = (action or "").strip().lower()
    legal = set(str(item) for item in legal_actions(state, seat.seat_no)["actions"])
    if name not in legal:
        raise HoldemError(f"illegal action {action}")
    to_call = money(max(Decimal("0"), state.current_bet - seat.street_bet))
    previous_bet = money(state.current_bet)
    full_raise = False
    if name == "fold":
        seat.folded = True
    elif name == "check":
        pass
    elif name == "call":
        _put(seat, to_call)
    elif name == "all_in":
        _put(seat, seat.stack)
        if money(seat.street_bet) > previous_bet:
            raise_size = money(seat.street_bet - previous_bet)
            if raise_size >= state.last_raise_size:
                full_raise = True
                state.last_raise_size = raise_size
            state.current_bet = money(seat.street_bet)
    elif name == "raise":
        raise_to = money(amount or 0)
        min_raise_to = money(state.current_bet + state.last_raise_size)
        max_raise_to = money(seat.street_bet + seat.stack)
        if raise_to < min_raise_to and raise_to < max_raise_to:
            raise HoldemError("raise too small")
        if raise_to > max_raise_to:
            raise_to = max_raise_to
        need = money(raise_to - seat.street_bet)
        _put(seat, need)
        raise_size = money(seat.street_bet - previous_bet)
        if raise_size >= state.last_raise_size:
            full_raise = True
            state.last_raise_size = raise_size
        state.current_bet = money(max(state.current_bet, seat.street_bet))
    else:
        raise HoldemError(f"unknown action {action}")
    if seat.folded:
        state.acted = [num for num in state.acted if num != seat.seat_no]
    elif full_raise:
        state.last_aggressor = seat.seat_no
        state.acted = [seat.seat_no]
    else:
        if seat.seat_no not in state.acted:
            state.acted.append(seat.seat_no)
        if state.last_aggressor is None and name in {"check"}:
            pass
        elif name in {"call", "all_in"} and state.last_aggressor is None and to_call > 0:
            pass
    state.version += 1
    _advance_or_close(state)
    return state


def apply_timeout(state: HandState) -> HandState:
    if state.to_act is None or state.street in {"showdown", "complete"}:
        return state
    seat = state.seats[state.to_act]
    to_call = money(max(Decimal("0"), state.current_bet - seat.street_bet))
    action: ActionName = "check" if to_call <= 0 else "fold"
    return apply_action(state, seat.seat_no, action)


def apply_mid_hand_fold(state: HandState, seat_no: int) -> HandState:
    """Stand up during a hand: fold if still live. Safe if already folded."""
    seat = state.seats.get(int(seat_no))
    if seat is None:
        raise HoldemError("empty seat")
    seat.leaving = True
    if seat.folded or state.street in {"showdown", "complete"}:
        return state
    if state.to_act == seat.seat_no:
        return apply_action(state, seat.seat_no, "fold")
    seat.folded = True
    state.acted = [num for num in state.acted if num != seat.seat_no]
    state.version += 1
    if state.to_act is not None:
        _advance_or_close(state)
    return state


def public_view(state: HandState, viewer_seat: int | None) -> dict[str, object]:
    seats = []
    for num in sorted(state.seats):
        seat = state.seats[num]
        show_cards = bool(
            seat.hole
            and (
                (viewer_seat is not None and num == viewer_seat)
                or (state.cards_shown and not seat.folded)
            )
        )
        seats.append(
            {
                "seat_no": num,
                "stack_rub": float(money(seat.stack)),
                "street_bet_rub": float(money(seat.street_bet)),
                "committed_rub": float(money(seat.committed)),
                "folded": seat.folded,
                "all_in": seat.all_in,
                "leaving": seat.leaving,
                "hole": list(seat.hole) if show_cards and seat.hole else None,
            }
        )
    return {
        "hand_id": state.hand_id,
        "street": state.street,
        "button": state.button,
        "to_act": state.to_act,
        "pot_rub": float(pot_total(state)),
        "current_bet_rub": float(money(state.current_bet)),
        "board": state.board,
        "seats": seats,
        "legal": legal_actions(state, viewer_seat) if viewer_seat is not None else legal_actions(state),
        "winners": state.winners,
        "rake_rub": float(money(state.rake)),
        "version": state.version,
    }


def next_button(seated: Sequence[int], current: int) -> int:
    ordered = _ordered_seats(seated, int(current))
    if not ordered:
        raise HoldemError("no seats for button")
    return ordered[0]

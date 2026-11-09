"""Длинные нарды: ходы, марс/ойн, кости HMAC.

Источники, с которыми сверены тесты (не короткие нарды, не GNU):

- Википедия, «Длинные нарды»: голова, полный ход, первый бросок 3-3/4-4/6-6,
  пример «белые 5-5, чёрные 4-4 — одна четвёрка».
  https://ru.wikipedia.org/wiki/Длинные_нарды
- Ахундов, правила ассоциации: дом белых 1–6, дом чёрных 13–18, снятие.
  https://www.aipbg.ru/rules-long-backgammon
- BKGM Narde: нет боя, прайм из шести не запирает всех.
  https://bkgm.com/variants/Narde.html
- Приказ Минспорта 30.04.2025 № 347, ст. 20 и п. 48: ойн ×1, марс ×2.
  Кокс только у коротких (п. 1.22), на этот стол не начисляется.
  Куб (ст. 23) на денежную партию не входит.

Нумерация доски как на схеме википедии: белые с пункта 24 на 1,
чёрные с пункта 12 тем же кругом до пунктов 13–18.
«Пункт 3» у Ахундова для чёрных 4-4 расходится с его же «пункт 4 занят»
и с примером википедии: вторая четвёрка чёрных встаёт на пункт 4.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from casino_finance import money

WHITE = 0
BLACK = 1
HEAD = (0, 12)
POINT_COUNT = 24


class NardyError(ValueError):
    """Нелегальный ход или сломанное состояние."""


@dataclass(frozen=True)
class Step:
    src: int
    die: int
    dst: int  # -1 = снять с доски


@dataclass(frozen=True)
class Position:
    white: tuple[int, ...]
    black: tuple[int, ...]
    white_off: int = 0
    black_off: int = 0

    def pile(self, player: int) -> tuple[int, ...]:
        return self.white if player == WHITE else self.black

    def off(self, player: int) -> int:
        return self.white_off if player == WHITE else self.black_off

    def replace(self, player: int, pile: Sequence[int], off: int) -> Position:
        frozen = tuple(int(n) for n in pile)
        if player == WHITE:
            return Position(frozen, self.black, int(off), self.black_off)
        return Position(self.white, frozen, self.white_off, int(off))


def initial_position() -> Position:
    white = [0] * POINT_COUNT
    black = [0] * POINT_COUNT
    white[HEAD[WHITE]] = 15
    black[HEAD[BLACK]] = 15
    return Position(tuple(white), tuple(black), 0, 0)


def point_number(index: int) -> int:
    """Глобальный индекс 0 — пункт 24, дальше по ходу до пункта 1."""
    if index < 0 or index >= POINT_COUNT:
        raise NardyError("index off the board")
    return 24 - index


def index_of_point(point: int) -> int:
    if point < 1 or point > 24:
        raise NardyError("point off the board")
    return 24 - point


def format_move(steps: Sequence[Step]) -> str:
    if not steps:
        return "ход сгорел"
    parts: list[str] = []
    for step in steps:
        src = point_number(step.src)
        if step.dst < 0:
            parts.append(f"снять с {src}")
        else:
            parts.append(f"{src}→{point_number(step.dst)}")
    return ", ".join(parts)


def _home_indices(player: int) -> range:
    return range(18, 24) if player == WHITE else range(6, 12)


def _rank(player: int, index: int) -> int | None:
    """6 — вход в дом, 1 — край, с которого снимают единицей."""
    if player == WHITE:
        if 18 <= index <= 23:
            return 24 - index
        return None
    if 6 <= index <= 11:
        return 12 - index
    return None


def _all_in_home(pos: Position, player: int) -> bool:
    pile = pos.pile(player)
    if player == WHITE:
        return sum(pile[:18]) == 0
    return sum(pile[:6]) + sum(pile[12:]) == 0


def _highest_home_index(pos: Position, player: int) -> int | None:
    pile = pos.pile(player)
    for index in _home_indices(player):
        if pile[index]:
            return index
    return None


def _board_destination(player: int, src: int, die: int) -> int | None:
    """Куда встанет шашка, если ход не снимает её. None — за краем дома."""
    if player == WHITE:
        nxt = src + die
        return nxt if nxt <= 23 else None
    black_index = (src - HEAD[BLACK]) % POINT_COUNT
    nxt = black_index + die
    if nxt > 23:
        return None
    return (HEAD[BLACK] + nxt) % POINT_COUNT


def _can_bear(pos: Position, player: int, src: int, die: int) -> bool:
    """Ахундов 3.2: точное поле, иначе с более дальнего, иначе с ближайшего меньшего."""
    if not _all_in_home(pos, player):
        return False
    rank = _rank(player, src)
    if rank is None or pos.pile(player)[src] <= 0:
        return False
    if rank == die:
        return True
    if rank > die:
        return False
    pile = pos.pile(player)
    for index in _home_indices(player):
        higher = _rank(player, index)
        if pile[index] and higher is not None and higher >= die:
            return False
    return src == _highest_home_index(pos, player)


def _remaining_path(player: int, index: int) -> set[int]:
    """Пункты впереди шашки, которые ей ещё надо пройти."""
    if player == WHITE:
        return set(range(index + 1, POINT_COUNT))
    black_index = (index - HEAD[BLACK]) % POINT_COUNT
    return {(HEAD[BLACK] + step) % POINT_COUNT for step in range(black_index + 1, POINT_COUNT)}


def _seals_opponent(pos: Position, player: int, start: int) -> bool:
    prime = {(start + offset) % POINT_COUNT for offset in range(6)}
    opponent = BLACK if player == WHITE else WHITE
    pile = pos.pile(opponent)
    checkers = [index for index, count in enumerate(pile) if count]
    if not checkers:
        return False
    for index in checkers:
        if prime.isdisjoint(_remaining_path(opponent, index)):
            return False
    return True


def has_illegal_prime(pos: Position, player: int) -> bool:
    """Шесть своих подряд, за которыми все 15 шашек соперника. П. 20.5, BKGM."""
    pile = pos.pile(player)
    for start in range(POINT_COUNT):
        if all(pile[(start + offset) % POINT_COUNT] > 0 for offset in range(6)):
            if _seals_opponent(pos, player, start):
                return True
    return False


def _apply_pile(pos: Position, player: int, src: int, dst: int) -> Position:
    pile = list(pos.pile(player))
    if pile[src] <= 0:
        raise NardyError("no checker")
    pile[src] -= 1
    off = pos.off(player)
    if dst < 0:
        off += 1
    else:
        if pos.pile(BLACK if player == WHITE else WHITE)[dst] > 0:
            raise NardyError("occupied")
        pile[dst] += 1
    return pos.replace(player, pile, off)


def _step_on(pos: Position, player: int, src: int, die: int, left_head: int, max_leave: int) -> tuple[Position, int, Step] | None:
    pile = pos.pile(player)
    if src < 0 or src >= POINT_COUNT or pile[src] <= 0 or die < 1 or die > 6:
        return None
    new_left = left_head
    if src == HEAD[player]:
        if left_head + 1 > max_leave:
            return None
        new_left = left_head + 1
    opponent = pos.pile(BLACK if player == WHITE else WHITE)
    board_dst = _board_destination(player, src, die)
    if board_dst is None:
        if not _can_bear(pos, player, src, die):
            return None
        dst = -1
    else:
        if opponent[board_dst] > 0:
            return None
        dst = board_dst
    nxt = _apply_pile(pos, player, src, dst)
    if has_illegal_prime(nxt, player):
        return None
    return nxt, new_left, Step(src, die, dst)


def _stopped_by_enemy_head(pos: Position, player: int, face: int) -> bool:
    """Одной шашкой с головы четыре шага упираются именно в голову соперника.

    Тогда на первом 3-3, 4-4 или 6-6 можно снять вторую. Если раньше мешает
    чужая шашка не на голове (вики: белые 5-5, чёрные 4-4), вторую не снимают.
    """
    enemy = HEAD[BLACK if player == WHITE else WHITE]
    opponent = pos.pile(BLACK if player == WHITE else WHITE)
    current = HEAD[player]
    for _ in range(4):
        nxt = _board_destination(player, current, face)
        if nxt is None:
            return False
        if opponent[nxt] > 0:
            return nxt == enemy
        current = nxt
    return False


def _max_leave(pos: Position, player: int, dice: tuple[int, int], first_roll: bool) -> int:
    if not first_roll or dice[0] != dice[1] or dice[0] not in (3, 4, 6):
        return 1
    if _stopped_by_enemy_head(pos, player, dice[0]):
        return 2
    return 1


def _expand(dice: tuple[int, int]) -> tuple[int, ...]:
    if dice[0] == dice[1]:
        return (dice[0], dice[0], dice[0], dice[0])
    return dice


def legal_moves(pos: Position, player: int, dice: tuple[int, int], *, first_roll: bool) -> list[tuple[Step, ...]]:
    """Все максимальные хода. Пустой кортеж — ходить нечем, очки сгорают."""
    if dice[0] < 1 or dice[0] > 6 or dice[1] < 1 or dice[1] > 6:
        raise NardyError("dice")
    if player not in (WHITE, BLACK):
        raise NardyError("player")
    max_leave = _max_leave(pos, player, dice, first_roll)
    remaining0 = _expand(dice)
    cache: dict[tuple[Position, tuple[int, ...], int], list[tuple[Step, ...]]] = {}

    def walk(cur: Position, remaining: tuple[int, ...], left: int) -> list[tuple[Step, ...]]:
        key = (cur, remaining, left)
        cached = cache.get(key)
        if cached is not None:
            return cached
        found: list[tuple[Step, ...]] = []
        seen_die: set[int] = set()
        for die in remaining:
            if die in seen_die:
                continue
            seen_die.add(die)
            rest_list = list(remaining)
            rest_list.remove(die)
            rest = tuple(rest_list)
            pile = cur.pile(player)
            for src, count in enumerate(pile):
                if count <= 0:
                    continue
                stepped = _step_on(cur, player, src, die, left, max_leave)
                if stepped is None:
                    continue
                nxt, new_left, step = stepped
                for tail in walk(nxt, rest, new_left):
                    found.append((step,) + tail)
        cache[key] = found or [()]
        return cache[key]

    sequences = walk(pos, remaining0, 0)
    best = max(len(seq) for seq in sequences)
    sequences = [seq for seq in sequences if len(seq) == best]
    if dice[0] != dice[1] and best == 1:
        higher = max(dice)
        preferred = [seq for seq in sequences if seq and seq[0].die == higher]
        if preferred:
            sequences = preferred
    unique: list[tuple[Step, ...]] = []
    seen: set[tuple[tuple[int, int, int], ...]] = set()
    for seq in sequences:
        key = tuple((step.src, step.die, step.dst) for step in seq)
        if key in seen:
            continue
        seen.add(key)
        unique.append(seq)
    unique.sort(key=lambda seq: tuple((step.src, step.die, step.dst) for step in seq))
    return unique


def apply_steps(pos: Position, player: int, steps: Sequence[Step]) -> Position:
    current = pos
    left = 0
    for step in steps:
        stepped = _step_on(current, player, step.src, step.die, left, max_leave=2)
        if stepped is None or stepped[2] != step:
            raise NardyError("illegal step")
        current, left, _ = stepped
    if sum(current.pile(player)) + current.off(player) != 15:
        raise NardyError("checker leak")
    return current


def result_kind(pos: Position, winner: int) -> str:
    """Ойн, если соперник снял хотя бы одну. Иначе марс. Кокса нет."""
    return "mars" if pos.off(BLACK if winner == WHITE else WHITE) == 0 else "oin"


def settlement(stake: Decimal, kind: str, rake_percent: Decimal, rake_cap: Decimal) -> dict[str, Decimal]:
    """Каждый уже списал 2 ставки (потолок марса). Ойн возвращает лишнюю, марс — нет."""
    locked = money(money(stake) * 2)
    gross = money(money(stake) * (2 if kind == "mars" else 1))
    if gross > locked:
        raise NardyError("payout above the lock")
    rake = money(gross * money(rake_percent) / Decimal(100))
    cap = money(rake_cap)
    if cap > 0 and rake > cap:
        rake = cap
    if rake > gross:
        rake = gross
    return {
        "locked": locked,
        "gross": gross,
        "rake": rake,
        "winner": money(locked + gross - rake),
        "loser": money(locked - gross),
    }


def roll_dice(server_seed: str, message: str, n: int) -> tuple[int, ...]:
    """HMAC-SHA256, без смещения остатка. n костей 1..6."""
    if n < 1 or n > 4:
        raise NardyError("roll size")
    key = server_seed.encode("utf-8")
    out: list[int] = []
    cursor = 0
    span = 6
    limit = (2**32 // span) * span
    while len(out) < n:
        digest = hmac.new(key, f"{message}:{cursor}".encode("utf-8"), hashlib.sha256).digest()
        cursor += 1
        value = int.from_bytes(digest[:4], "big")
        if value >= limit:
            continue
        out.append(value % span + 1)
        if cursor > 64:
            raise NardyError("dice entropy")
    return tuple(out)


def commit_of(server_seed: str, table_id: str) -> str:
    return hashlib.sha256(f"{server_seed}:{table_id}".encode("utf-8")).hexdigest()


def roll_message(client_seed: str, nonce: int, table_id: str) -> str:
    return f"{client_seed}:{int(nonce)}:{table_id}:nardy"


@dataclass
class Match:
    """Партия без денег: старт, ход, сдача. Кости только из сида."""

    seed: str
    table_id: str
    client_seed: str
    pos: Position
    turn: int
    first_roll: list[bool]
    dice: tuple[int, int] | None
    phase: str
    nonce: int
    log: list[dict[str, object]]
    start_white: int
    start_black: int
    result: dict[str, object] | None

    @classmethod
    def start(cls, *, seed: str, table_id: str, client_seed: str = "focuspay-nardy") -> Match:
        match = cls(
            seed=seed,
            table_id=table_id,
            client_seed=client_seed,
            pos=initial_position(),
            turn=WHITE,
            first_roll=[True, True],
            dice=None,
            phase="move",
            nonce=0,
            log=[],
            start_white=0,
            start_black=0,
            result=None,
        )
        while True:
            white_die = match._take(1)[0]
            black_die = match._take(1)[0]
            match.start_white = white_die
            match.start_black = black_die
            match.log.append({"kind": "start", "white": white_die, "black": black_die})
            if white_die != black_die:
                opener = WHITE if white_die > black_die else BLACK
                break
            if match.nonce > 40:
                opener = WHITE
                break
        match._begin_turn(opener)
        return match

    def _take(self, n: int) -> tuple[int, ...]:
        dice = roll_dice(
            self.seed,
            roll_message(self.client_seed, self.nonce, self.table_id),
            n,
        )
        self.nonce += 1
        self.log.append({"kind": "roll", "nonce": self.nonce - 1, "dice": list(dice)})
        return dice

    def moves(self) -> list[tuple[Step, ...]]:
        if self.phase != "move" or self.dice is None:
            return []
        found = legal_moves(self.pos, self.turn, self.dice, first_roll=self.first_roll[self.turn])
        return [seq for seq in found if seq]

    def _begin_turn(self, player: int) -> None:
        self.turn = player
        for _ in range(32):
            rolled = self._take(2)
            self.dice = (rolled[0], rolled[1])
            if self.moves():
                return
            self.log.append({"kind": "skip", "player": self.turn, "dice": list(self.dice)})
            self.first_roll[self.turn] = False
            self.turn = BLACK if self.turn == WHITE else WHITE
        raise NardyError("too many skipped turns")

    def play(self, index: int) -> None:
        options = self.moves()
        if index < 0 or index >= len(options):
            raise NardyError("no such move")
        self.pos = apply_steps(self.pos, self.turn, options[index])
        self.log.append(
            {
                "kind": "move",
                "player": self.turn,
                "steps": [[step.src, step.die, step.dst] for step in options[index]],
            }
        )
        if self.pos.off(self.turn) == 15:
            self.phase = "done"
            self.dice = None
            self.result = {"winner": self.turn, "kind": result_kind(self.pos, self.turn)}
            return
        self.first_roll[self.turn] = False
        self._begin_turn(BLACK if self.turn == WHITE else WHITE)

    def resign(self, player: int) -> None:
        if self.phase == "done":
            raise NardyError("already finished")
        if player not in (WHITE, BLACK):
            raise NardyError("player")
        winner = BLACK if player == WHITE else WHITE
        self.phase = "done"
        self.dice = None
        self.result = {"winner": winner, "kind": "oin", "reason": "resign"}
        self.log.append({"kind": "resign", "player": player})

    def to_dict(self) -> dict[str, object]:
        return {
            "white": list(self.pos.white),
            "black": list(self.pos.black),
            "white_off": self.pos.white_off,
            "black_off": self.pos.black_off,
            "turn": self.turn,
            "first_roll": list(self.first_roll),
            "dice": list(self.dice) if self.dice else None,
            "phase": self.phase,
            "nonce": self.nonce,
            "log": self.log,
            "start_white": self.start_white,
            "start_black": self.start_black,
            "result": self.result,
        }

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, object],
        *,
        seed: str,
        table_id: str,
        client_seed: str,
    ) -> Match:
        dice_raw = raw.get("dice")
        dice = None
        if isinstance(dice_raw, list) and len(dice_raw) == 2:
            dice = (int(dice_raw[0]), int(dice_raw[1]))
        result = raw.get("result")
        return cls(
            seed=seed,
            table_id=table_id,
            client_seed=client_seed,
            pos=Position(
                tuple(int(n) for n in raw["white"]),  # type: ignore[index]
                tuple(int(n) for n in raw["black"]),  # type: ignore[index]
                int(raw["white_off"]),  # type: ignore[arg-type]
                int(raw["black_off"]),  # type: ignore[arg-type]
            ),
            turn=int(raw["turn"]),  # type: ignore[arg-type]
            first_roll=[bool(raw["first_roll"][0]), bool(raw["first_roll"][1])],  # type: ignore[index]
            dice=dice,
            phase=str(raw["phase"]),
            nonce=int(raw["nonce"]),  # type: ignore[arg-type]
            log=list(raw["log"]),  # type: ignore[arg-type]
            start_white=int(raw["start_white"]),  # type: ignore[arg-type]
            start_black=int(raw["start_black"]),  # type: ignore[arg-type]
            result=result if isinstance(result, dict) else None,
        )


def verify_log(match: Match) -> bool:
    """Повторить кости из сида. Ходы не переигрываются."""
    nonce = 0
    for entry in match.log:
        kind = str(entry.get("kind"))
        if kind != "roll":
            continue
        logged = entry.get("dice")
        if not isinstance(logged, list):
            return False
        again = roll_dice(match.seed, roll_message(match.client_seed, nonce, match.table_id), len(logged))
        if list(again) != [int(pip) for pip in logged]:
            return False
        if int(entry.get("nonce", -1)) != nonce:
            return False
        nonce += 1
    return nonce == match.nonce


def checkers_ok(pos: Position) -> bool:
    for player in (WHITE, BLACK):
        pile = pos.pile(player)
        if any(count < 0 for count in pile):
            return False
        if sum(pile) + pos.off(player) != 15:
            return False
    return all(not (pos.white[index] and pos.black[index]) for index in range(POINT_COUNT))

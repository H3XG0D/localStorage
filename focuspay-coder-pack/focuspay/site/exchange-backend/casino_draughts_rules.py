"""Русские шашки: нотация игрока и ничьи 6.1.8.

Генератор ходов — py-draughts 1.9.1 ``RussianBoard``. Этот модуль его не копирует
и не импортирует ``draughts.engines``. ``Board.is_draw`` для денег не используется:
в 1.9.1 оно шире пункта 6.1.8.8 и не смотрит большую дорогу.
"""
from __future__ import annotations

from dataclasses import dataclass

from draughts.boards.russian import Board as RussianBoard
from draughts.models import Color

_BOARD = RussianBoard()
NAMES: tuple[str, ...] = tuple(_BOARD.SQUARE_NAMES)
INDEX: dict[str, int] = {name: i for i, name in enumerate(NAMES)}
BIG_ROAD = frozenset({"a1", "b2", "c3", "d4", "e5", "f6", "g7", "h8"})

WHITE = "white"
BLACK = "black"


class DraughtsRulesError(ValueError):
    pass


@dataclass(frozen=True)
class PlayerMove:
    notation: str
    origin: str
    path: tuple[str, ...]
    destination: str
    capture: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "notation": self.notation,
            "origin": self.origin,
            "path": list(self.path),
            "destination": self.destination,
        }


@dataclass(frozen=True)
class PieceView:
    square: str
    side: str
    kind: str

    def as_dict(self) -> dict[str, str]:
        return {"square": self.square, "side": self.side, "kind": self.kind}


@dataclass(frozen=True)
class MatchState:
    status: str
    reason: str
    turn: str
    moves: tuple[str, ...]
    legal: tuple[PlayerMove, ...]
    pieces: tuple[PieceView, ...]
    white_moves: int
    black_moves: int
    can_offer_draw: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "turn": self.turn,
            "moves": list(self.moves),
            "legal_moves": [item.as_dict() for item in self.legal],
            "pieces": [item.as_dict() for item in self.pieces],
            "white_moves": self.white_moves,
            "black_moves": self.black_moves,
            "can_offer_draw": self.can_offer_draw,
        }


def _side_name(color: Color) -> str:
    return WHITE if color == Color.WHITE else BLACK


def _fresh(start_fen: str | None) -> RussianBoard:
    if start_fen:
        return RussianBoard.from_fen(start_fen)
    return RussianBoard()


def _squares_of(bits: int) -> list[str]:
    return [NAMES[i] for i in range(32) if bits & (1 << i)]


def _men_kings(board: RussianBoard, side: str) -> tuple[int, int]:
    if side == WHITE:
        return board.white_men, board.white_kings
    return board.black_men, board.black_kings


def _piece_count(board: RussianBoard) -> int:
    return (
        board.white_men.bit_count()
        + board.white_kings.bit_count()
        + board.black_men.bit_count()
        + board.black_kings.bit_count()
    )


def _on_road(bits: int) -> bool:
    return any(name in BIG_ROAD for name in _squares_of(bits))


def _owns_big_road(kings: int) -> bool:
    return _on_road(kings)


def attacker_three_kings(board: RussianBoard) -> str | None:
    """6.1.8.3: ровно три дамки против одной, без простых, сильная сторона на большой дороге."""
    if board.white_men or board.black_men:
        return None
    white = board.white_kings.bit_count()
    black = board.black_kings.bit_count()
    if white == 3 and black == 1 and _owns_big_road(board.white_kings):
        return WHITE
    if black == 3 and white == 1 and _owns_big_road(board.black_kings):
        return BLACK
    return None


def attacker_three_plus(board: RussianBoard) -> str | None:
    """6.1.8.4: три дамки и ещё материал против одной дамки."""
    if board.white_men == 0 and board.white_kings.bit_count() == 1 and board.black_kings.bit_count() >= 3:
        extra = board.black_men.bit_count() + board.black_kings.bit_count() - 3
        if extra > 0:
            return BLACK
    if board.black_men == 0 and board.black_kings.bit_count() == 1 and board.white_kings.bit_count() >= 3:
        extra = board.white_men.bit_count() + board.white_kings.bit_count() - 3
        if extra > 0:
            return WHITE
    return None


def lone_king_on_road(board: RussianBoard) -> bool:
    """6.1.8.5: три фигуры не на большой дороге против одинокой дамки на ней."""
    sides = (WHITE, BLACK)
    for lone, trio in (sides, sides[::-1]):
        men, kings = _men_kings(board, lone)
        if men or kings.bit_count() != 1:
            continue
        if not _on_road(kings):
            continue
        other_men, other_kings = _men_kings(board, trio)
        total = other_men.bit_count() + other_kings.bit_count()
        if total != 3:
            continue
        if _on_road(other_men | other_kings):
            continue
        kinds = (other_kings.bit_count(), other_men.bit_count())
        if kinds not in {(3, 0), (2, 1), (1, 2), (0, 3)}:
            continue
        return True
    return False


def both_have_kings(board: RussianBoard) -> bool:
    return bool(board.white_kings) and bool(board.black_kings)


def _promotes(board: RussianBoard, move) -> bool:
    if move.is_promotion:
        return True
    piece = board._get(move.square_list[0])
    bit = 1 << move.square_list[-1]
    if piece == -1 and board.PROMO_WHITE & bit:
        return True
    if piece == 1 and board.PROMO_BLACK & bit:
        return True
    return False


def _is_king_piece(board: RussianBoard, move) -> bool:
    return abs(board._get(move.square_list[0])) == 2


def notation_of(move) -> str:
    path = [NAMES[square] for square in move.square_list]
    sep = ":" if move.captured_list else "-"
    return sep.join(path)


def _parse(text: str) -> tuple[str, list[int]]:
    raw = (text or "").strip().lower().replace(" ", "")
    if not raw or (":" in raw and "-" in raw):
        raise DraughtsRulesError("Ход пишется как d4:b6 или a3-b4")
    if ":" in raw:
        kind, parts = "capture", raw.split(":")
    elif "-" in raw:
        kind, parts = "quiet", raw.split("-")
    else:
        raise DraughtsRulesError("Ход пишется как d4:b6 или a3-b4")
    if len(parts) < 2 or any(not part for part in parts):
        raise DraughtsRulesError("Ход пишется как d4:b6 или a3-b4")
    if any(part.isdigit() for part in parts):
        raise DraughtsRulesError("Нужна нотация поля, не номер 1–32")
    try:
        squares = [INDEX[part] for part in parts]
    except KeyError as exc:
        raise DraughtsRulesError("Нет такого поля") from exc
    return kind, squares


def match_legal(board: RussianBoard, text: str):
    kind, squares = _parse(text)
    found = []
    for move in board.legal_moves:
        capture = bool(move.captured_list)
        if kind == "capture" and not capture:
            continue
        if kind == "quiet" and capture:
            continue
        if list(move.square_list) == squares:
            found.append(move)
    if len(found) == 1:
        return found[0]
    if not found:
        raise DraughtsRulesError("Такого хода нет")
    raise DraughtsRulesError("Укажите полный путь боя")


def _player_moves(board: RussianBoard) -> tuple[PlayerMove, ...]:
    rows = []
    for move in board.legal_moves:
        path = tuple(NAMES[square] for square in move.square_list)
        rows.append(
            PlayerMove(
                notation=notation_of(move),
                origin=path[0],
                path=path,
                destination=path[-1],
                capture=bool(move.captured_list),
            )
        )
    return tuple(rows)


def _pieces(board: RussianBoard) -> tuple[PieceView, ...]:
    rows: list[PieceView] = []
    for side, men, kings in (
        (WHITE, board.white_men, board.white_kings),
        (BLACK, board.black_men, board.black_kings),
    ):
        for square in _squares_of(kings):
            rows.append(PieceView(square, side, "king"))
        for square in _squares_of(men):
            rows.append(PieceView(square, side, "man"))
    return tuple(rows)


def _position_key(board: RussianBoard) -> tuple[int, int, int, int, int]:
    return (
        board.white_men,
        board.white_kings,
        board.black_men,
        board.black_kings,
        int(board.turn.value),
    )


def assess(moves: list[str] | tuple[str, ...], *, start_fen: str | None = None) -> MatchState:
    board = _fresh(start_fen)
    seen = {_position_key(board): 1}
    status = "ongoing"
    reason = ""
    white_moves = 0
    black_moves = 0
    king_white = king_black = 0
    stable_white = stable_black = 0
    road_moves = 0
    extra_moves = 0
    road_attacker: str | None = None
    extra_attacker: str | None = None
    five_white = five_black = 0
    five_on = False
    accepted: list[str] = []

    for text in moves:
        if status != "ongoing":
            raise DraughtsRulesError("Партия уже закончена")
        move = match_legal(board, text)
        mover = _side_name(board.turn)
        capture = bool(move.captured_list)
        king_move = _is_king_piece(board, move)
        promoted = _promotes(board, move)
        before_road = attacker_three_kings(board)
        before_extra = attacker_three_plus(board)
        before_five = lone_king_on_road(board)
        before_stable = both_have_kings(board)
        board.push(move)
        accepted.append(notation_of(move))
        if mover == WHITE:
            white_moves += 1
        else:
            black_moves += 1

        if capture or promoted or not king_move:
            king_white = king_black = 0
        elif mover == WHITE:
            king_white += 1
        else:
            king_black += 1

        stable_now = both_have_kings(board) and not capture and not promoted
        if not (before_stable and stable_now):
            stable_white = stable_black = 0
        elif mover == WHITE:
            stable_white += 1
        else:
            stable_black += 1

        after_road = attacker_three_kings(board)
        if after_road is None or after_road != before_road:
            road_moves = 0
            road_attacker = after_road
        elif mover == after_road:
            road_moves += 1
            road_attacker = after_road

        after_extra = attacker_three_plus(board)
        if after_extra is None or after_extra != before_extra:
            extra_moves = 0
            extra_attacker = after_extra
        elif mover == after_extra:
            extra_moves += 1
            extra_attacker = after_extra

        after_five = lone_king_on_road(board) and not capture
        if not (before_five and after_five):
            five_white = five_black = 0
            five_on = after_five and not capture
        elif mover == WHITE:
            five_white += 1
            five_on = True
        else:
            five_black += 1
            five_on = True

        key = _position_key(board)
        seen[key] = seen.get(key, 0) + 1
        pieces = _piece_count(board)

        if not board.legal_moves:
            status = mover
            reason = "6.1.7"
        elif seen[key] >= 3:
            status, reason = "draw", "threefold"
        elif road_attacker and road_moves >= 15:
            status, reason = "draw", "6.1.8.3"
        elif extra_attacker and extra_moves >= 15:
            status, reason = "draw", "6.1.8.4"
        elif five_on and five_white >= 5 and five_black >= 5:
            status, reason = "draw", "6.1.8.5"
        elif pieces in {4, 5} and king_white >= 15 and king_black >= 15:
            status, reason = "draw", "6.1.8.8"
        elif pieces in {6, 7} and king_white >= 25 and king_black >= 25:
            status, reason = "draw", "6.1.8.8"
        elif pieces in {2, 3} and stable_white >= 5 and stable_black >= 5:
            status, reason = "draw", "6.1.8.6"
        elif pieces in {4, 5} and stable_white >= 30 and stable_black >= 30:
            status, reason = "draw", "6.1.8.6"
        elif pieces in {6, 7} and stable_white >= 60 and stable_black >= 60:
            status, reason = "draw", "6.1.8.6"

    legal = () if status != "ongoing" else _player_moves(board)
    return MatchState(
        status=status,
        reason=reason,
        turn=_side_name(board.turn),
        moves=tuple(accepted),
        legal=legal,
        pieces=_pieces(board),
        white_moves=white_moves,
        black_moves=black_moves,
        can_offer_draw=status == "ongoing" and white_moves >= 20 and black_moves >= 20,
    )


def push_notation(moves: list[str], notation: str, *, start_fen: str | None = None) -> MatchState:
    state = assess(moves, start_fen=start_fen)
    if state.status != "ongoing":
        raise DraughtsRulesError("Партия уже закончена")
    allowed = {item.notation for item in state.legal}
    parsed = match_legal(_fresh(start_fen) if not moves else _board_after(moves, start_fen), notation)
    canonical = notation_of(parsed)
    if canonical not in allowed:
        raise DraughtsRulesError("Такого хода нет")
    return assess([*moves, canonical], start_fen=start_fen)


def _board_after(moves: list[str], start_fen: str | None) -> RussianBoard:
    board = _fresh(start_fen)
    for text in moves:
        board.push(match_legal(board, text))
    return board

"""Public round history for a casino player profile."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from fastapi import HTTPException

from casino_cards import DEFAULT_CLIENT_SEED
from casino_finance import money
from casino_holdem import cards_were_shown, hand_seed_public
from casino_player_profile import GAME_LABELS, player_exists

RESULT_LABELS = {
    "win": "Победа",
    "loss": "Проигрыш",
    "push": "Ничья",
    "refund": "Возврат",
}

HISTORY_LIMIT_DEFAULT = 30
HISTORY_LIMIT_MAX = 50
GROUPED_PER_DEFAULT = 5
GROUPED_PER_MAX = 20

HISTORY_SECTION_ORDER = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "roulette",
    "raffle",
    "jackpot",
    "holdem",
    "fixed_room",
    "clan_war",
)
HISTORY_GAME_TYPES = frozenset(HISTORY_SECTION_ORDER)
_DICE_GAME_SQL = ("pvp_dice", "pvp_emoji", "cub")
_DICE_V2_SQL = ("pvp_dice", "pvp_emoji")
_SOURCES_BY_TYPE = {
    "pvp_dice": frozenset({"games", "v2"}),
    "baccara": frozenset({"games", "v2"}),
    "blackjack": frozenset({"games", "v2"}),
    "roulette": frozenset({"games", "roulette"}),
    "jackpot": frozenset({"jackpot"}),
    "raffle": frozenset({"raffle"}),
    "holdem": frozenset({"poker"}),
    "fixed_room": frozenset({"room"}),
    "clan_war": frozenset({"war"}),
}

_TABLE_ROULETTE_SQL = """
            g.game_type = 'roulette'
            AND (
                COALESCE(g.game_data #>> '{roulette,table_round_id}', '') <> ''
                OR COALESCE(g.game_data #>> '{rng_audit,table_round_id}', '') <> ''
            )
"""


def _text_money(value: Decimal | int | float | str | None) -> str:
    return str(money(value or 0))


def _iso(value: object) -> str | None:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return stamp.isoformat()
    return None


def _as_map(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def share_percent(stake: object, pot: object) -> str | None:
    bank = money(pot)
    if bank <= 0:
        return None
    pct = money(stake) / bank * Decimal("100")
    return format(pct.quantize(Decimal("0.01")), "f")


def classify_result(
    *,
    player_id: int,
    winner_id: object = None,
    stake: object = 0,
    payout: object = 0,
    house: bool = False,
    refunded: bool = False,
) -> str:
    if refunded:
        return "refund"
    stake_m = money(stake)
    payout_m = money(payout or 0)
    if payout_m > stake_m:
        return "win"
    if stake_m > 0 and payout_m == stake_m:
        return "push"
    if winner_id is not None and int(winner_id) == int(player_id):
        return "win"
    if house:
        return "loss"
    if winner_id is None and payout_m == 0:
        return "push" if stake_m == 0 else "loss"
    return "loss"


def _pack(
    *,
    game_type: str,
    round_id: str,
    settled_at: object,
    stake: object | None,
    share: str | None,
    result: str,
    href: str,
    fairness: dict[str, object] | None,
    tickets: int | None = None,
) -> dict[str, object]:
    label = GAME_LABELS.get(game_type, game_type)
    payload: dict[str, object] = {
        "game_type": game_type,
        "label": label,
        "round_id": str(round_id),
        "settled_at": _iso(settled_at),
        "stake_rub": _text_money(stake) if stake is not None else None,
        "share_percent": share,
        "result": result,
        "result_label": RESULT_LABELS.get(result, result),
        "href": href,
        "fairness": fairness,
    }
    if tickets is not None:
        payload["tickets"] = int(tickets)
    return payload


def play_href(game_type: str, *, round_id: str = "", kind: str = "") -> str:
    mapped = "pvp_dice" if game_type in {"pvp_emoji", "cub"} else game_type
    if kind == "v2" and round_id:
        return f"/casino/tables/{round_id}"
    if kind == "duel" and round_id:
        return f"/casino/duels/{round_id}"
    if mapped == "jackpot":
        return "/casino/play/jackpot"
    if mapped == "roulette":
        return "/casino/play/roulette"
    if mapped == "raffle":
        return "/casino/play/raffle"
    if mapped == "holdem" and round_id:
        return f"/casino/poker/{round_id}"
    if mapped == "fixed_room" and round_id:
        return f"/casino/rooms/{round_id}"
    if mapped == "clan_war" and round_id:
        return f"/casino/wars/{round_id}"
    if mapped in {"pvp_dice", "baccara", "blackjack"}:
        mode = "house" if game_type == "cub" else "players"
        return f"/casino/play/{mapped}?mode={mode}"
    return f"/casino/play/{mapped}"


def _card_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(card) for card in value if card]


def card_fairness(
    *,
    game_id: str,
    game_type: str,
    game_data: Mapping[str, Any] | None,
    rng_commit: object = None,
    rng_seed: object = None,
    rng_nonce: object = None,
) -> dict[str, object] | None:
    data = _as_map(game_data)
    rng = _as_map(data.get("card_rng"))
    seed = str(rng.get("server_seed") or rng_seed or "")
    commit = str(rng.get("commit") or rng_commit or "")
    if not seed or not commit:
        return None
    client = str(rng.get("client_seed") or DEFAULT_CLIENT_SEED)
    try:
        nonce = int(rng.get("nonce") if rng.get("nonce") is not None else rng_nonce or 0)
    except (TypeError, ValueError):
        nonce = 0
    cards = _card_list(rng.get("creator_cards") or rng.get("player_cards"))
    payload: dict[str, object] = {
        "game_type": game_type,
        "game_id": game_id,
        "commit": commit,
        "server_seed": seed,
        "client_seed": client,
        "nonce": nonce,
        "side": "creator",
    }
    if cards:
        payload["expected_cards"] = " ".join(cards)
    return payload


def roulette_fairness(
    *,
    game_id: str,
    game_data: Mapping[str, Any] | None = None,
    rng_commit: object = None,
    rng_seed: object = None,
    rng_nonce: object = None,
    pocket: object = None,
    client_seed: str = DEFAULT_CLIENT_SEED,
) -> dict[str, object] | None:
    data = _as_map(game_data)
    audit = _as_map(data.get("rng_audit"))
    blob = _as_map(data.get("roulette"))
    seed = str(audit.get("seed") or rng_seed or "")
    commit = str(audit.get("commit") or rng_commit or "")
    if not seed or not commit:
        return None
    client = str(audit.get("client_seed") or client_seed or DEFAULT_CLIENT_SEED)
    try:
        nonce = int(audit.get("nonce") if audit.get("nonce") is not None else rng_nonce or 0)
    except (TypeError, ValueError):
        nonce = 0
    hmac_id = str(audit.get("table_round_id") or blob.get("table_round_id") or game_id)
    pocket_val = pocket if pocket is not None else audit.get("pocket")
    if pocket_val is None:
        pocket_val = blob.get("pocket")
    payload: dict[str, object] = {
        "game_type": "roulette",
        "game_id": hmac_id,
        "commit": commit,
        "server_seed": seed,
        "client_seed": client,
        "nonce": nonce,
    }
    if pocket_val is not None:
        payload["expected_pocket"] = int(pocket_val)
    return payload


def jackpot_fairness(
    *,
    round_id: str,
    commit: object,
    roll: object,
    total_tickets: object,
    winning_ticket: object,
) -> dict[str, object] | None:
    seed = str(roll or "")
    hashed = str(commit or "")
    if not seed or not hashed:
        return None
    try:
        tickets = int(total_tickets or 0)
    except (TypeError, ValueError):
        tickets = 0
    if tickets < 1:
        return None
    payload: dict[str, object] = {
        "game_type": "jackpot",
        "game_id": round_id,
        "commit": hashed,
        "server_seed": seed,
        "client_seed": DEFAULT_CLIENT_SEED,
        "nonce": 0,
        "total_tickets": tickets,
    }
    if winning_ticket is not None:
        payload["expected_ticket"] = int(winning_ticket)
    return payload


async def _fetch(conn, query: str, *args) -> list[Any]:
    try:
        rows = await conn.fetch(query, *args)
    except Exception as exc:
        name = type(exc).__name__
        if "UndefinedTable" in name or "UndefinedColumn" in name:
            return []
        raise
    return list(rows or [])


def _games_sql() -> str:
    return f"""
        SELECT g.game_id, g.game_type, g.creator_id, g.opponent_id, g.bet_rub, g.payout_rub,
               g.winner_id, g.finished_at, g.counterparty_kind, g.game_data,
               g.rng_commit, g.rng_seed_reveal, g.rng_nonce, g.status
        FROM casino_games g
        WHERE g.status = 'finished'
          AND g.finished_at IS NOT NULL
          AND (g.creator_id = $1 OR g.opponent_id = $1)
          AND NOT ({_TABLE_ROULETTE_SQL})
          AND ($2::timestamptz IS NULL OR g.finished_at < $2)
          AND ($4::text[] IS NULL OR g.game_type = ANY($4::text[]))
        ORDER BY g.finished_at DESC
        LIMIT $3
    """


def _from_game(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    raw_type = str(row["game_type"] or "")
    game_type = "pvp_dice" if raw_type in {"pvp_emoji", "cub"} else raw_type
    game_id = str(row["game_id"])
    house = str(row.get("counterparty_kind") or "") == "house_robot"
    opponent = row.get("opponent_id")
    players = 1 + (1 if opponent is not None else 0)
    share = None if house else share_percent(row["bet_rub"], money(row["bet_rub"]) * players)
    result = classify_result(
        player_id=player_id,
        winner_id=row.get("winner_id"),
        stake=row["bet_rub"],
        payout=row.get("payout_rub") if house or (row.get("winner_id") is not None and int(row["winner_id"]) == int(player_id)) else 0,
        house=house,
    )
    if not house and row.get("winner_id") is None:
        result = "push"
    elif not house and row.get("winner_id") is not None and int(row["winner_id"]) != int(player_id):
        result = "loss"
    elif not house and row.get("winner_id") is not None and int(row["winner_id"]) == int(player_id):
        result = "win"
    kind = "duel" if not house and opponent is not None else ""
    fairness = None
    data = _as_map(row.get("game_data"))
    if raw_type in {"baccara", "blackjack"}:
        fairness = card_fairness(
            game_id=game_id,
            game_type=raw_type,
            game_data=data,
            rng_commit=row.get("rng_commit"),
            rng_seed=row.get("rng_seed_reveal"),
            rng_nonce=row.get("rng_nonce"),
        )
    elif raw_type == "roulette":
        fairness = roulette_fairness(
            game_id=game_id,
            game_data=data,
            rng_commit=row.get("rng_commit"),
            rng_seed=row.get("rng_seed_reveal"),
            rng_nonce=row.get("rng_nonce"),
        )
    return _pack(
        game_type=game_type,
        round_id=game_id,
        settled_at=row["finished_at"],
        stake=row["bet_rub"],
        share=share,
        result=result,
        href=play_href(raw_type, round_id=game_id, kind=kind),
        fairness=fairness,
    )


def _from_jackpot(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    pot = money(row.get("pot_rub"))
    stake = money(row.get("amount_rub"))
    status = str(row.get("status") or "")
    result = classify_result(
        player_id=player_id,
        winner_id=row.get("winner_id"),
        stake=stake,
        payout=money(row.get("payout_rub")) if row.get("winner_id") is not None and int(row["winner_id"]) == int(player_id) else 0,
        refunded=status == "refunded",
    )
    tickets = int(row["ticket_to"]) - int(row["ticket_from"]) + 1 if row.get("ticket_to") is not None else 0
    total_tickets = int(row["total_tickets"] or tickets)
    fairness = None
    if status == "settled":
        fairness = jackpot_fairness(
            round_id=str(row["round_id"]),
            commit=row.get("commit_hash"),
            roll=row.get("roll"),
            total_tickets=total_tickets,
            winning_ticket=row.get("winning_ticket"),
        )
    return _pack(
        game_type="jackpot",
        round_id=str(row["round_id"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot),
        result=result,
        href=play_href("jackpot"),
        fairness=fairness,
    )


def _from_roulette_table(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    stake = money(row.get("stake_rub"))
    pot = money(row.get("pot_rub"))
    payout = money(row.get("payout_rub") or 0)
    result = classify_result(player_id=player_id, stake=stake, payout=payout, house=True)
    fairness = roulette_fairness(
        game_id=str(row["round_id"]),
        rng_commit=row.get("commit_hash"),
        rng_seed=row.get("server_seed"),
        rng_nonce=0,
        pocket=row.get("pocket"),
        client_seed=DEFAULT_CLIENT_SEED,
    )
    return _pack(
        game_type="roulette",
        round_id=str(row["round_id"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot),
        result=result,
        href=play_href("roulette"),
        fairness=fairness,
    )


def _from_v2(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    game_type = str(row["game_type"] or "pvp_dice")
    if game_type == "pvp_emoji":
        game_type = "pvp_dice"
    stake = money(row.get("stake_rub"))
    pot = money(row.get("pot_rub") or 0)
    player_count = int(row.get("player_count") or 0)
    if pot <= 0 and player_count > 0:
        pot = money(stake * player_count)
    seat_no = int(row["seat_no"])
    payload = _as_map(row.get("payload"))
    winners = []
    for raw in list(payload.get("winner_seat_nos") or []):
        try:
            winners.append(int(raw))
        except (TypeError, ValueError):
            continue
    outcome_kind = str(row.get("outcome_kind") or "")
    if seat_no in winners:
        result = "push" if outcome_kind == "tie_split" else "win"
    else:
        result = "loss"
    return _pack(
        game_type=game_type,
        round_id=str(row["table_id"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot) if pot > 0 else (share_percent(1, player_count) if player_count else None),
        result=result,
        href=play_href(game_type, round_id=str(row["table_id"]), kind="v2"),
        fairness=None,
    )


def _from_poker(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    wager = _as_map(row.get("wager_json"))
    stake = money(wager.get(str(player_id)) or 0)
    pot = money(sum((money(v) for v in wager.values()), Decimal("0")))
    state = _as_map(row.get("game_state"))
    winners_raw = state.get("winners") if isinstance(state.get("winners"), list) else []
    seat_by_user: dict[int, int] = {}
    seats = state.get("seats")
    if isinstance(seats, Mapping):
        for num, seat in seats.items():
            blob = _as_map(seat)
            uid = blob.get("user_id")
            if uid is not None:
                try:
                    seat_by_user[int(uid)] = int(num)
                except (TypeError, ValueError):
                    continue
    my_seat = seat_by_user.get(int(player_id))
    won = False
    for item in winners_raw:
        blob = _as_map(item)
        try:
            if my_seat is not None and int(blob.get("seat_no")) == int(my_seat):
                won = True
                break
        except (TypeError, ValueError):
            continue
    shown = cards_were_shown(state)
    board = _card_list(state.get("board_full") if shown else state.get("board"))
    seed = str(row.get("server_seed") or "") if hand_seed_public(shown, row.get("seed_revealed_at")) else ""
    fairness = None
    if seed and row.get("commit_hash"):
        fairness = {
            "game_type": "holdem",
            "game_id": str(row["hand_key"]),
            "commit": str(row["commit_hash"]),
            "server_seed": seed,
            "client_seed": str(row.get("client_seed") or DEFAULT_CLIENT_SEED),
            "nonce": int(row.get("nonce") or 0),
        }
        if board:
            fairness["expected_cards"] = " ".join(board)
    return _pack(
        game_type="holdem",
        round_id=str(row["hand_key"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot),
        result="win" if won else "loss",
        href=play_href("holdem", round_id=str(row["table_id"])),
        fairness=fairness,
    )


def _from_room(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    stake = money(row.get("stake_rub"))
    pot = money(row.get("pot_rub") or 0)
    status = str(row.get("status") or "")
    result = classify_result(
        player_id=player_id,
        winner_id=row.get("winner_id"),
        stake=stake,
        payout=money(row.get("payout_rub")) if row.get("winner_id") is not None and int(row["winner_id"]) == int(player_id) else 0,
        refunded=status == "refunded",
    )
    fairness = None
    seed = str(row.get("server_seed") or "") if status in {"locked", "settled"} else ""
    user_ids = [int(uid) for uid in (row.get("user_ids") or []) if uid is not None]
    if seed and row.get("commit_hash") and user_ids:
        from casino_fixed_rooms import fairness_message

        fairness = {
            "game_type": "fixed_room",
            "game_id": str(row["room_id"]),
            "commit": str(row["commit_hash"]),
            "server_seed": seed,
            "client_seed": DEFAULT_CLIENT_SEED,
            "nonce": 0,
            "hmac_message": fairness_message(str(row["room_id"]), user_ids),
            "modulus": int(row.get("seat_count") or len(user_ids)),
        }
        if row.get("winner_index") is not None:
            fairness["expected_index"] = int(row["winner_index"])
    return _pack(
        game_type="fixed_room",
        round_id=str(row["room_id"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot),
        result=result,
        href=play_href("fixed_room", round_id=str(row["room_id"])),
        fairness=fairness,
    )


def _from_war(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    stake = money(row.get("stake_rub"))
    pot = money(row.get("pot_rub") or 0)
    status = str(row.get("status") or "")
    my_clan = row.get("my_clan_id")
    winner_clan = row.get("winner_clan_id")
    result = "refund" if status == "refunded" else (
        "win" if my_clan is not None and winner_clan is not None and int(my_clan) == int(winner_clan) else "loss"
    )
    fairness = None
    seed = str(row.get("server_seed") or "") if status in {"locked", "settled"} else ""
    if seed and row.get("commit_hash") and row.get("hmac_message"):
        fairness = {
            "game_type": "clan_war",
            "game_id": str(row["war_id"]),
            "commit": str(row["commit_hash"]),
            "server_seed": seed,
            "client_seed": DEFAULT_CLIENT_SEED,
            "nonce": 0,
            "hmac_message": str(row["hmac_message"]),
            "modulus": 2,
        }
        if row.get("winner_index") is not None:
            fairness["expected_index"] = int(row["winner_index"])
    return _pack(
        game_type="clan_war",
        round_id=str(row["war_id"]),
        settled_at=row["settled_at"],
        stake=stake,
        share=share_percent(stake, pot),
        result=result,
        href=play_href("clan_war", round_id=str(row["war_id"])),
        fairness=fairness,
    )


def _from_raffle(row: Mapping[str, Any], player_id: int) -> dict[str, object]:
    tickets = int(row.get("tickets_total") or 0)
    total = int(row.get("total_tickets_issued") or 0)
    place = row.get("place")
    result = "win" if place is not None else "loss"
    fairness = None
    seed = str(row.get("draw_seed") or "")
    commit = str(row.get("draw_commit") or "")
    if seed and commit:
        nonce = int(place or 1)
        eligible = int(row["eligible_tickets"] or total or 0) if row.get("eligible_tickets") is not None else total
        fairness = {
            "game_type": "raffle",
            "game_id": f"flucky-{int(row['campaign_id'])}",
            "commit": commit,
            "server_seed": seed,
            "client_seed": DEFAULT_CLIENT_SEED,
            "nonce": nonce,
            "total_tickets": eligible if eligible > 0 else max(total, 1),
        }
        if row.get("hmac_index") is not None:
            fairness["expected_ticket"] = int(row["hmac_index"])
    return _pack(
        game_type="raffle",
        round_id=f"flucky-{int(row['campaign_id'])}",
        settled_at=row.get("draw_at") or row.get("settled_at"),
        stake=None,
        share=share_percent(tickets, total) if total > 0 else None,
        result=result,
        href=play_href("raffle"),
        fairness=fairness,
        tickets=tickets,
    )


async def _jackpot_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT r.round_id, r.status, r.commit_hash, r.roll, r.winning_ticket, r.winner_id,
               r.pot_rub, r.payout_rub, r.settled_at, r.wager_json,
               b.amount_rub, b.ticket_from, b.ticket_to,
               COALESCE((
                   SELECT SUM((b2.ticket_to - b2.ticket_from) + 1)
                   FROM casino_jackpot_bets b2 WHERE b2.round_pk = r.id
               ), 0)::bigint AS total_tickets
        FROM casino_jackpot_bets b
        JOIN casino_jackpot_rounds r ON r.id = b.round_pk
        WHERE b.user_id = $1
          AND r.status IN ('settled', 'refunded')
          AND r.settled_at IS NOT NULL
          AND ($2::timestamptz IS NULL OR r.settled_at < $2)
        ORDER BY r.settled_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
    )
    return [_from_jackpot(dict(row), player_id) for row in rows]


async def _roulette_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT r.round_id, r.settled_at, r.commit_hash, r.server_seed, r.pocket,
               player.stake_rub, pot.pot_rub, COALESCE(paid.payout_rub, 0)::numeric AS payout_rub
        FROM casino_roulette_rounds r
        JOIN (
            SELECT round_pk, SUM(stake_rub)::numeric AS stake_rub
            FROM casino_roulette_bets
            WHERE user_id = $1
            GROUP BY round_pk
        ) player ON player.round_pk = r.id
        JOIN (
            SELECT round_pk, SUM(stake_rub)::numeric AS pot_rub
            FROM casino_roulette_bets
            GROUP BY round_pk
        ) pot ON pot.round_pk = r.id
        LEFT JOIN (
            SELECT b.round_pk, SUM(COALESCE(g.payout_rub, 0))::numeric AS payout_rub
            FROM casino_roulette_bets b
            LEFT JOIN casino_games g ON g.game_id = b.game_id
            WHERE b.user_id = $1
            GROUP BY b.round_pk
        ) paid ON paid.round_pk = r.id
        WHERE r.status = 'settled'
          AND r.settled_at IS NOT NULL
          AND ($2::timestamptz IS NULL OR r.settled_at < $2)
        ORDER BY r.settled_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
    )
    return [_from_roulette_table(dict(row), player_id) for row in rows]


async def _v2_rows(
    conn,
    player_id: int,
    before: datetime | None,
    limit: int,
    types: list[str] | None = None,
) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT t.table_id, t.game_type, t.settled_at, t.stake_rub, s.seat_no,
               st.outcome_kind, st.pot_rub, st.payload,
               (
                   SELECT COUNT(*) FROM casino_v2_table_seats x
                   WHERE x.table_id = t.id AND x.participant_kind = 'player'
               )::int AS player_count
        FROM casino_v2_tables t
        JOIN casino_v2_table_seats s ON s.table_id = t.id
        LEFT JOIN casino_v2_settlements st ON st.table_id = t.id
        WHERE t.status = 'finished'
          AND t.settled_at IS NOT NULL
          AND s.telegram_id = $1
          AND s.participant_kind = 'player'
          AND ($2::timestamptz IS NULL OR t.settled_at < $2)
          AND ($4::text[] IS NULL OR t.game_type = ANY($4::text[]))
        ORDER BY t.settled_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
        types,
    )
    return [_from_v2(dict(row), player_id) for row in rows]


async def _poker_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT h.hand_key, h.settled_at, h.wager_json, h.game_state, h.commit_hash,
               h.server_seed, h.client_seed, h.nonce, h.seed_revealed_at, h.status,
               t.table_id
        FROM casino_poker_hands h
        JOIN casino_poker_tables t ON t.id = h.table_pk
        WHERE h.settled_at IS NOT NULL
          AND h.wager_json ? $1::text
          AND ($2::timestamptz IS NULL OR h.settled_at < $2)
        ORDER BY h.settled_at DESC
        LIMIT $3
        """,
        str(player_id),
        before,
        limit,
    )
    return [_from_poker(dict(row), player_id) for row in rows]


async def _room_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT r.room_id, r.status, r.stake_rub, r.pot_rub, r.payout_rub, r.winner_id,
               r.winner_index, r.seat_count, r.commit_hash, r.server_seed, r.settled_at,
               ARRAY(
                   SELECT s.user_id FROM casino_fixed_room_seats s
                   WHERE s.room_pk = r.id ORDER BY s.seat_no
               ) AS user_ids
        FROM casino_fixed_room_seats mine
        JOIN casino_fixed_room_rounds r ON r.id = mine.room_pk
        WHERE mine.user_id = $1
          AND r.status IN ('settled', 'refunded')
          AND r.settled_at IS NOT NULL
          AND ($2::timestamptz IS NULL OR r.settled_at < $2)
        ORDER BY r.settled_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
    )
    return [_from_room(dict(row), player_id) for row in rows]


async def _war_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT w.war_id, w.status, w.stake_rub, w.pot_rub, w.winner_clan_id, w.winner_index,
               w.commit_hash, w.server_seed, w.settled_at, w.challenger_clan_id, w.opponent_clan_id,
               f.clan_id AS my_clan_id
        FROM casino_clan_war_fighters f
        JOIN casino_clan_wars w ON w.id = f.war_pk
        WHERE f.user_id = $1
          AND w.status IN ('settled', 'refunded')
          AND w.settled_at IS NOT NULL
          AND ($2::timestamptz IS NULL OR w.settled_at < $2)
        ORDER BY w.settled_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
    )
    packed = []
    for raw in rows:
        row = dict(raw)
        message = None
        if row.get("opponent_clan_id") and row.get("server_seed"):
            fighters = await _fetch(
                conn,
                """
                SELECT clan_id, user_id FROM casino_clan_war_fighters
                WHERE war_pk = (SELECT id FROM casino_clan_wars WHERE war_id = $1)
                """,
                str(row["war_id"]),
            )
            from casino_clan_wars import war_message

            chall = [int(item["user_id"]) for item in fighters if int(item["clan_id"]) == int(row["challenger_clan_id"])]
            opp = [int(item["user_id"]) for item in fighters if int(item["clan_id"]) == int(row["opponent_clan_id"])]
            if chall and opp:
                message = war_message(
                    str(row["war_id"]),
                    int(row["challenger_clan_id"]),
                    int(row["opponent_clan_id"]),
                    chall,
                    opp,
                )
        row["hmac_message"] = message
        packed.append(_from_war(row, player_id))
    return packed


async def _raffle_rows(conn, player_id: int, before: datetime | None, limit: int) -> list[dict[str, object]]:
    rows = await _fetch(
        conn,
        """
        SELECT c.id AS campaign_id, c.status, c.draw_at, c.draw_commit, c.draw_seed,
               c.total_tickets_issued, p.tickets_total, w.place, w.hmac_index, w.eligible_tickets
        FROM raffle_participants p
        JOIN raffle_campaigns c ON c.id = p.campaign_id
        LEFT JOIN LATERAL (
            SELECT place, hmac_index, eligible_tickets
            FROM raffle_winners
            WHERE campaign_id = c.id AND user_id = p.user_id
            ORDER BY place
            LIMIT 1
        ) w ON TRUE
        WHERE p.user_id = $1
          AND c.status = 'drawn'
          AND p.tickets_total > 0
          AND c.draw_at IS NOT NULL
          AND ($2::timestamptz IS NULL OR c.draw_at < $2)
        ORDER BY c.draw_at DESC
        LIMIT $3
        """,
        player_id,
        before,
        limit,
    )
    return [_from_raffle(dict(row), player_id) for row in rows]


async def _game_rows(
    conn,
    player_id: int,
    before: datetime | None,
    limit: int,
    types: list[str] | None = None,
) -> list[dict[str, object]]:
    rows = await _fetch(conn, _games_sql(), player_id, before, limit, types)
    return [_from_game(dict(row), player_id) for row in rows]


def parse_before(raw: str | None) -> datetime | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Некорректный курсор before") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def clamp_limit(raw: int | None) -> int:
    try:
        value = int(raw if raw is not None else HISTORY_LIMIT_DEFAULT)
    except (TypeError, ValueError):
        value = HISTORY_LIMIT_DEFAULT
    return max(1, min(value, HISTORY_LIMIT_MAX))


def clamp_grouped_per(raw: int | None) -> int:
    try:
        value = int(raw if raw is not None else GROUPED_PER_DEFAULT)
    except (TypeError, ValueError):
        value = GROUPED_PER_DEFAULT
    return max(1, min(value, GROUPED_PER_MAX))


def normalize_history_game_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in {"cub", "pvp_emoji"}:
        return "pvp_dice"
    if text not in HISTORY_GAME_TYPES:
        raise HTTPException(status_code=400, detail="Неизвестная игра")
    return text


def _sql_types(canonical: str | None) -> tuple[list[str] | None, list[str] | None]:
    if canonical is None:
        return None, None
    if canonical == "pvp_dice":
        return list(_DICE_GAME_SQL), list(_DICE_V2_SQL)
    if canonical in {"baccara", "blackjack"}:
        return [canonical], [canonical]
    if canonical == "roulette":
        return ["roulette"], None
    return None, None


def _sort_key(item: Mapping[str, object]) -> tuple:
    stamp = str(item.get("settled_at") or "")
    return (stamp, str(item.get("game_type") or ""), str(item.get("round_id") or ""))


async def _collect_history_rows(
    conn,
    player_id: int,
    *,
    cursor: datetime | None,
    fetch_n: int,
    game_type: str | None,
) -> list[dict[str, object]]:
    sources = _SOURCES_BY_TYPE.get(game_type) if game_type else None
    game_sql, v2_sql = _sql_types(game_type)
    chunks: list[dict[str, object]] = []
    if sources is None or "games" in sources:
        chunks.extend(await _game_rows(conn, player_id, cursor, fetch_n, game_sql))
    if sources is None or "jackpot" in sources:
        chunks.extend(await _jackpot_rows(conn, player_id, cursor, fetch_n))
    if sources is None or "roulette" in sources:
        chunks.extend(await _roulette_rows(conn, player_id, cursor, fetch_n))
    if sources is None or "v2" in sources:
        chunks.extend(await _v2_rows(conn, player_id, cursor, fetch_n, v2_sql))
    if sources is None or "poker" in sources:
        chunks.extend(await _poker_rows(conn, player_id, cursor, fetch_n))
    if sources is None or "room" in sources:
        chunks.extend(await _room_rows(conn, player_id, cursor, fetch_n))
    if sources is None or "war" in sources:
        chunks.extend(await _war_rows(conn, player_id, cursor, fetch_n))
    if sources is None or "raffle" in sources:
        chunks.extend(await _raffle_rows(conn, player_id, cursor, fetch_n))
    chunks.sort(key=_sort_key, reverse=True)
    return chunks


async def load_player_history(
    conn,
    player_id: int,
    *,
    viewer_id: int,
    limit: int | None = None,
    before: str | None = None,
    game_type: str | None = None,
    skip_exists: bool = False,
) -> dict[str, object]:
    player_id = int(player_id)
    canonical = normalize_history_game_type(game_type)
    if not skip_exists and int(viewer_id) != player_id and not await player_exists(conn, player_id):
        raise HTTPException(status_code=404, detail="Игрок не найден")
    size = clamp_limit(limit)
    cursor = parse_before(before)
    chunks = await _collect_history_rows(conn, player_id, cursor=cursor, fetch_n=size + 1, game_type=canonical)
    items = chunks[:size]
    next_before = None
    if len(chunks) > size:
        next_before = items[-1].get("settled_at")
    return {"success": True, "items": items, "next_before": next_before}


async def load_player_history_grouped(
    conn,
    player_id: int,
    *,
    viewer_id: int,
    per: int | None = None,
) -> dict[str, object]:
    player_id = int(player_id)
    if int(viewer_id) != player_id and not await player_exists(conn, player_id):
        raise HTTPException(status_code=404, detail="Игрок не найден")
    size = clamp_grouped_per(per)
    sections: list[dict[str, object]] = []
    for game_type in HISTORY_SECTION_ORDER:
        part = await load_player_history(
            conn,
            player_id,
            viewer_id=viewer_id,
            limit=size,
            game_type=game_type,
            skip_exists=True,
        )
        if not part["items"]:
            continue
        sections.append(
            {
                "game_type": game_type,
                "label": GAME_LABELS.get(game_type, game_type),
                "items": part["items"],
                "next_before": part["next_before"],
            }
        )
    return {"success": True, "sections": sections}

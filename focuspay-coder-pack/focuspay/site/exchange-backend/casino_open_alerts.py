"""Opt-in Telegram DMs when a blackjack player table opens. Never posts to the group chat."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Sequence

from casino_finance import money

OPEN_ALERT_GAME_TYPES = frozenset({"blackjack"})
OPEN_ALERT_EVENT = "open_table"
OPEN_ALERT_LIMIT = 80
GROUP_INVITE_SKIP = frozenset({"blackjack"})


def publishes_web_group_invitation(game_type: str) -> bool:
    return str(game_type or "") not in GROUP_INVITE_SKIP


def open_table_alert_text(*, game_type: str, stake_rub: Decimal | str | int | float, seats: int) -> str:
    stake = money(stake_rub)
    label = "Блэкджек" if game_type == "blackjack" else game_type
    places = max(2, int(seats or 2))
    return (
        f"🂡 <b>{label}</b> · стол на {stake} ₽ · {places} мест\n"
        "Зайти можно в казино на сайте. Это личное уведомление — его включают в настройках."
    )


async def enqueue_open_table_alerts(
    conn,
    *,
    game_id: str,
    game_type: str,
    creator_id: int,
    stake_rub: Decimal | str | int | float,
    seats: int = 2,
    href: str = "",
) -> int:
    if str(game_type or "") not in OPEN_ALERT_GAME_TYPES:
        return 0
    gid = str(game_id or "").strip()
    if not gid:
        return 0
    creator = int(creator_id)
    rows = await conn.fetch(
        """
        SELECT user_id
        FROM casino_player_cosmetics
        WHERE notify_open_tables IS TRUE
          AND user_id > 0
          AND user_id <> $1
        ORDER BY updated_at DESC
        LIMIT $2
        """,
        creator,
        OPEN_ALERT_LIMIT,
    )
    if not rows:
        return 0
    text = open_table_alert_text(game_type=str(game_type), stake_rub=stake_rub, seats=seats)
    inserted = 0
    for row in rows:
        recipient_id = int(row["user_id"])
        payload = {
            "chat_id": recipient_id,
            "text": text,
            "game_id": gid,
            "game_type": str(game_type),
            "href": href,
            "parse_mode": "HTML",
        }
        result = await conn.execute(
            """
            INSERT INTO casino_notification_outbox (event_key, event_type, game_id, recipient_id, payload)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (game_id, event_type, recipient_id) DO NOTHING
            """,
            f"casino:{gid}:{OPEN_ALERT_EVENT}:{recipient_id}",
            OPEN_ALERT_EVENT,
            gid,
            recipient_id,
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        )
        if str(result or "").startswith("INSERT") and not str(result).endswith("0"):
            inserted += 1
    return inserted


def recipient_ids_from_rows(rows: Sequence[object]) -> list[int]:
    out: list[int] = []
    for row in rows:
        try:
            out.append(int(row["user_id"]))  # type: ignore[index]
        except (TypeError, ValueError, KeyError):
            continue
    return out

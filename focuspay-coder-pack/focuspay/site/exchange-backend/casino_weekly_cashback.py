"""Недельный кешбек казино по ступенчатой политике."""
import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

from casino_cashback_tiers import cashback_amount, cashback_percent_for_wager, money
from casino_tier_config import load_tier_config, resolve_cashback_percent
from db import get_pool


CASHBACK_GAME_TYPES = (
    "pvp_dice",
    "baccara",
    "blackjack",
    "cub",
    "holdem",
)
PVP_ROBOT_CASHBACK_GAME_TYPES = ("pvp_dice",)
CASINO_TIMEZONE = ZoneInfo("Europe/Moscow")

logger = logging.getLogger(__name__)


def _sql_game_types(game_types: tuple[str, ...] = CASHBACK_GAME_TYPES) -> str:
    return ", ".join(f"'{game_type}'" for game_type in game_types)


async def accrue_weekly_casino_cashback() -> dict:
    """Начислить кешбек за прошлую полную неделю (понедельник—воскресенье)."""
    pool = await get_pool()

    today = datetime.now(CASINO_TIMEZONE).date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    week_start = datetime.combine(last_monday, time.min, tzinfo=CASINO_TIMEZONE)
    week_end = week_start + timedelta(days=7)
    last_sunday = week_end.date() - timedelta(days=1)
    game_types = _sql_game_types()
    pvp_robot_game_types = _sql_game_types(PVP_ROBOT_CASHBACK_GAME_TYPES)

    logger.info("Processing casino weekly cashback for %s — %s", last_monday, last_sunday)

    processed = 0
    accrued = 0
    total_cashback = Decimal("0.00")

    async with pool.acquire() as conn:
        async with conn.transaction():
            tier_config = await load_tier_config(conn)
            # Каждая ветка соответствует завершённому расчёту конкретного канонического
            # типа игры. Неизвестные типы и raffle намеренно не попадают в выборку.
            players = await conn.fetch(
                f"""
                WITH wagers AS (
                    SELECT creator_id AS telegram_id, bet_rub::numeric AS wager_rub
                    FROM casino_games
                    WHERE finished_at >= $1
                      AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND creator_id IS NOT NULL
                    UNION ALL
                    SELECT opponent_id AS telegram_id, bet_rub::numeric AS wager_rub
                    FROM casino_games
                    WHERE finished_at >= $1
                      AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND counterparty_kind = 'player'
                      AND opponent_id IS NOT NULL
                    UNION ALL
                    SELECT (item.key)::bigint AS telegram_id, (item.value)::numeric AS wager_rub
                    FROM casino_poker_hands h,
                         jsonb_each_text(h.wager_json) AS item
                    WHERE h.settled_at >= $1
                      AND h.settled_at < $2
                      AND item.key ~ '^-?[0-9]+$'
                ), losses AS (
                    SELECT creator_id AS telegram_id, bet_rub::numeric AS loss_rub,
                           0::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND counterparty_kind = 'player'
                      AND opponent_id IS NOT NULL
                      AND winner_id = opponent_id
                    UNION ALL
                    SELECT opponent_id AS telegram_id, bet_rub::numeric AS loss_rub,
                           0::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND counterparty_kind = 'player'
                      AND opponent_id IS NOT NULL
                      AND winner_id = creator_id
                    UNION ALL
                    SELECT creator_id AS telegram_id, bet_rub::numeric AS loss_rub,
                           0::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({pvp_robot_game_types})
                      AND counterparty_kind = 'pvp_robot'
                      AND opponent_id IS NULL
                      AND winner_id IS NULL
                      AND outcome->>'kind' = 'house_win'
                    UNION ALL
                    SELECT creator_id AS telegram_id, bet_rub::numeric AS loss_rub,
                           0::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type = 'cub'
                      AND counterparty_kind = 'house_robot'
                      AND opponent_id IS NULL
                      AND winner_id IS NULL
                      AND outcome->>'kind' = 'loss'
                ), wins AS (
                    SELECT creator_id AS telegram_id, COALESCE(payout_rub, 0)::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND counterparty_kind = 'player'
                      AND opponent_id IS NOT NULL
                      AND winner_id = creator_id
                    UNION ALL
                    SELECT opponent_id AS telegram_id, COALESCE(payout_rub, 0)::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({game_types})
                      AND counterparty_kind = 'player'
                      AND opponent_id IS NOT NULL
                      AND winner_id = opponent_id
                    UNION ALL
                    SELECT creator_id AS telegram_id, COALESCE(payout_rub, 0)::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type IN ({pvp_robot_game_types})
                      AND counterparty_kind = 'pvp_robot'
                      AND winner_id = creator_id
                      AND outcome->>'kind' = 'winner'
                    UNION ALL
                    SELECT creator_id AS telegram_id, COALESCE(payout_rub, 0)::numeric AS won_rub
                    FROM casino_games
                    WHERE finished_at >= $1 AND finished_at < $2
                      AND status = 'finished'
                      AND game_type = 'cub'
                      AND counterparty_kind = 'house_robot'
                      AND winner_id = creator_id
                      AND outcome->>'kind' = 'win'
                ), wager_totals AS (
                    SELECT telegram_id, SUM(wager_rub)::numeric AS total_bet
                    FROM wagers
                    GROUP BY telegram_id
                ), loss_totals AS (
                    SELECT telegram_id, SUM(loss_rub)::numeric AS eligible_loss,
                           SUM(won_rub)::numeric AS total_won
                    FROM losses
                    GROUP BY telegram_id
                ), win_totals AS (
                    SELECT telegram_id, SUM(won_rub)::numeric AS total_won
                    FROM wins
                    GROUP BY telegram_id
                )
                SELECT wager_totals.telegram_id, wager_totals.total_bet,
                       COALESCE(win_totals.total_won, 0)::numeric AS total_won,
                       COALESCE(loss_totals.eligible_loss, 0)::numeric AS eligible_loss
                FROM wager_totals
                JOIN loss_totals USING (telegram_id)
                LEFT JOIN win_totals USING (telegram_id)
                WHERE loss_totals.eligible_loss > 0
                """,
                week_start,
                week_end,
            )

            for player_row in players:
                telegram_id = player_row["telegram_id"]
                if not telegram_id:
                    continue

                total_bet = money(player_row["total_bet"] or 0)
                total_won = money(player_row["total_won"] or 0)
                eligible_loss = money(player_row["eligible_loss"] or 0)
                net_loss = money(total_bet - total_won)
                cashback_percent = resolve_cashback_percent(tier_config.cashback_volume_tiers, total_bet)
                cashback_rub = cashback_amount(total_bet, eligible_loss, tier_config.cashback_volume_tiers)

                # The audit record claims this player/week and the stable ledger order_id
                # makes the financial credit independently idempotent.
                claimed = await conn.fetchval(
                    """
                    INSERT INTO casino_player_cashback (
                        telegram_id, week_start, total_bet_rub, total_won_rub,
                        net_loss_rub, eligible_loss_rub, cashback_rub, cashback_percent, status, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', now())
                    ON CONFLICT (telegram_id, week_start) DO NOTHING
                    RETURNING telegram_id
                    """,
                    telegram_id,
                    last_monday,
                    total_bet,
                    total_won,
                    net_loss,
                    eligible_loss,
                    cashback_rub,
                    cashback_percent,
                )
                if claimed is None:
                    logger.debug("Cashback already exists for %s week %s", telegram_id, last_monday)
                    continue

                ledger_order_id = f"casino-weekly-cashback:{telegram_id}:{last_monday.isoformat()}"
                await conn.execute(
                    """
                    INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
                    VALUES ($1, 'accrual', $2, $3, $4)
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    telegram_id,
                    cashback_rub,
                    ledger_order_id,
                    (
                        f"Казино: недельный кешбек {cashback_percent}% "
                        f"({last_monday} — {last_sunday})"
                    ),
                )
                await conn.execute(
                    """
                    UPDATE casino_player_cashback
                    SET status = 'accrued', accrued_at = now(), updated_at = now()
                    WHERE telegram_id = $1 AND week_start = $2 AND status = 'pending'
                    """,
                    telegram_id,
                    last_monday,
                )

                processed += 1
                accrued += 1
                total_cashback += cashback_rub
                logger.info(
                    "Accrued %.2f ₽ casino cashback to %s (eligible loss: %.2f ₽, tier: %s%%)",
                    cashback_rub,
                    telegram_id,
                    eligible_loss,
                    cashback_percent,
                )

    logger.info(
        "Casino weekly cashback complete: %s players processed, %s accrued, %.2f ₽ total",
        processed,
        accrued,
        total_cashback,
    )
    return {
        "processed": processed,
        "accrued": accrued,
        "total_cashback_rub": float(money(total_cashback)),
    }

"""Staging-only roulette smoke: real Postgres, real money path, no forged auth.

Runs inside the staging backend container:
  docker compose ... exec -T backend python /runtime/staging-roulette-smoke.py

Plays rounds through `play_roulette_with_conn` — the same function the authed
`POST /user/casino/play` route calls — and checks the arithmetic against the
player ledger and the house account. Staging only; never point it at production.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "/app/backend")

PLAYER_ID = int(os.environ.get("SMOKE_PLAYER_ID", "940002"))
STAKE = Decimal(os.environ.get("SMOKE_STAKE_RUB", "10"))
ROUNDS = int(os.environ.get("SMOKE_ROUNDS", "60"))
BETS = tuple((os.environ.get("SMOKE_BETS") or "red,black,zero").split(","))
#: Stop early once these bets have been seen winning at least once.
NEED_WIN = tuple(item for item in (os.environ.get("SMOKE_NEED_WIN") or "").split(",") if item)


async def main() -> int:
    import asyncpg

    from casino_roulette import (
        ROULETTE_BETS,
        pocket_color,
        play_roulette_with_conn,
        wheel_position,
    )

    pool = await asyncpg.create_pool(os.environ["DATABASE_DSN"], min_size=1, max_size=2)
    failures: list[str] = []
    pockets: Counter[int] = Counter()
    colors: Counter[str] = Counter()
    wins = 0
    staked = Decimal("0")
    paid = Decimal("0")
    commission = Decimal("0")

    async with pool.acquire() as conn:
        settings = await conn.fetchval("SELECT value FROM casino_settings WHERE key = 'enabled_games'")
        print(f"enabled_games: {settings}")
        start_balance = await conn.fetchval(
            "SELECT COALESCE(sum(amount_rub), 0) FROM user_cashback_ledger WHERE user_id = $1", PLAYER_ID
        )
        house_start = await conn.fetchval("SELECT balance_rub FROM casino_house_accounts WHERE id = 1")
        print(f"player {PLAYER_ID} ledger start: {start_balance}, house start: {house_start}")

        played: list[str] = []
        won_bets: set[str] = set()
        rounds_played = 0
        for index in range(ROUNDS):
            bet = BETS[index % len(BETS)]
            spec = ROULETTE_BETS[bet]
            rounds_played += 1
            async with conn.transaction():
                payload = await play_roulette_with_conn(
                    conn, telegram_id=PLAYER_ID, stake_rub=STAKE, bet=bet
                )
            game_id = str(payload["game_id"])
            played.append(game_id)
            pocket = int(payload["pocket"])
            color = str(payload["color"])
            won = bool(payload["won"])
            payout = Decimal(str(payload["payout_rub"]))
            fee = Decimal(str(payload["commission_rub"]))
            pockets[pocket] += 1
            colors[color] += 1
            staked += STAKE
            paid += payout
            commission += fee
            wins += 1 if won else 0

            if color != pocket_color(pocket):
                failures.append(f"{game_id}: colour {color} != {pocket_color(pocket)} for pocket {pocket}")
            if int(payload["wheel_index"]) != wheel_position(pocket):
                failures.append(f"{game_id}: wheel_index {payload['wheel_index']} != {wheel_position(pocket)}")
            if won != (pocket in spec.pockets):
                failures.append(f"{game_id}: bet {bet} won={won} but pocket {pocket} says otherwise")
            if not won and payout != 0:
                failures.append(f"{game_id}: loss paid {payout}")
            if won:
                won_bets.add(bet)
                gross = STAKE * spec.payout_multiplier
                expected = gross - fee
                if payout != expected:
                    failures.append(f"{game_id}: payout {payout} != gross {gross} - fee {fee}")
                if fee <= 0:
                    failures.append(f"{game_id}: win took no commission")
                print(f"  win {bet} pocket {pocket} {color} ×{spec.payout_multiplier} → {payout} (fee {fee})")
            stored = await conn.fetchrow(
                "SELECT status, outcome, payout_rub, commission_rub, rng_commit, rng_seed_reveal"
                " FROM casino_games WHERE game_id = $1",
                game_id,
            )
            if not stored or stored["status"] != "finished":
                failures.append(f"{game_id}: not stored as finished")
            elif Decimal(str(stored["payout_rub"])) != payout:
                failures.append(f"{game_id}: stored payout {stored['payout_rub']} != {payout}")
            elif not stored["rng_commit"] or not stored["rng_seed_reveal"]:
                failures.append(f"{game_id}: commit/seed missing in history")
            if NEED_WIN and won_bets.issuperset(NEED_WIN):
                break

        end_balance = await conn.fetchval(
            "SELECT COALESCE(sum(amount_rub), 0) FROM user_cashback_ledger WHERE user_id = $1", PLAYER_ID
        )
        house_end = await conn.fetchval("SELECT balance_rub FROM casino_house_accounts WHERE id = 1")
        reserved = await conn.fetchval("SELECT reserved_rub FROM casino_house_accounts WHERE id = 1")
        stuck_holds = await conn.fetchval(
            "SELECT count(*) FROM casino_balance_holds WHERE game_id = ANY($1::text[]) AND status <> 'confirmed'",
            played,
        )
        open_reserves = await conn.fetchval(
            "SELECT count(*) FROM casino_house_reservations WHERE game_id = ANY($1::text[]) AND status <> 'settled'",
            played,
        )

    player_delta = Decimal(str(end_balance)) - Decimal(str(start_balance))
    expected_player = paid - staked
    house_delta = Decimal(str(house_end)) - Decimal(str(house_start))

    if player_delta != expected_player:
        failures.append(f"player ledger moved {player_delta}, expected {expected_player}")
    if house_delta != staked - paid:
        failures.append(f"house moved {house_delta}, expected {staked - paid}")
    if stuck_holds:
        failures.append(f"{stuck_holds} smoke holds left unconfirmed")
    if open_reserves:
        failures.append(f"{open_reserves} smoke reservations left active")
    missing_wins = [item for item in NEED_WIN if item not in won_bets]
    if missing_wins:
        failures.append(f"no winning round observed for: {', '.join(missing_wins)}")

    print(f"rounds={rounds_played} stake={STAKE} bets={','.join(BETS)} wins={wins} staked={staked} paid={paid} commission={commission}")
    print(f"player delta={player_delta} (expected {expected_player}) house delta={house_delta} reserved_now={reserved}")
    print(f"distinct pockets={len(pockets)} colors={dict(colors)}")
    print("pockets: " + " ".join(f"{p}×{c}" for p, c in sorted(pockets.items())))
    if failures:
        print(f"FAIL ({len(failures)}):")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("OK: colours, wheel index, payouts, ledger, house account and holds all agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

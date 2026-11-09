"""60 synthetic players against real isolated API/PG, NOT Telegram/browser E2E.

No fabricated outcomes: backend timeout workers must deal, score and settle.
Each player creates one table and joins the next (60 tables, 120 seats).
"""
import asyncio
import json
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
import httpx

from tests.e2e.test_staging_v2_multiplayer import _validate_environment
from focuspay_client import FocusPayClient


def _http_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} {exc.request.url.path}"
    return type(exc).__name__


async def _advance_ready_countdown(db, tables: list[str]) -> None:
    """Let the closer promote ready→running without waiting the wall-clock 10s."""
    past = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    await db.execute(
        """UPDATE casino_v2_tables
           SET game_state = jsonb_set(COALESCE(game_state, '{}'::jsonb), '{starts_at}', $2::jsonb)
           WHERE table_id=ANY($1::text[]) AND status='ready'""",
        tables,
        json.dumps(past),
    )


class Staging60PlayersTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_opponent_after_60_seconds_keeps_one_player_hold(self):
        url, dsn, token = _validate_environment()
        run = uuid.uuid4().hex[:12]
        user = 2000000000 + int(run[:8], 16) * 100
        table = f'qa-auto-{run}'
        db = await asyncpg.connect(dsn)
        client = FocusPayClient(base_url=url, internal_token=token)
        try:
            await db.execute("INSERT INTO bot_users(user_id,first_name) VALUES($1,'Synthetic auto opponent')", user)
            await db.execute("INSERT INTO user_cashback_ledger(user_id,type,amount_rub,order_id) VALUES($1,'accrual',100,$2)", user, f'qa-fund-{run}')
            await client.create_v2_table(table_id=table, creator_id=user, game_type='pvp_dice', stake_rub='10.00', max_players=2, bot_count=0, draw_policy='tie_split', expected_state_version=0, idempotency_key=f'create-{table}')
            await asyncio.sleep(2)
            self.assertEqual(await db.fetchval('SELECT status FROM casino_v2_tables WHERE table_id=$1', table), 'open')
            # Advance only this synthetic table's waiting age; workers stay real.
            await db.execute("UPDATE casino_v2_tables SET created_at=now()-interval '61 seconds' WHERE table_id=$1", table)
            for _ in range(15):
                status = await db.fetchval('SELECT status FROM casino_v2_tables WHERE table_id=$1', table)
                if status != 'open':
                    break
                await asyncio.sleep(1)
            self.assertIn(status, ('ready', 'running', 'finished'))
            seats = await db.fetch("SELECT participant_kind,count(*) n FROM casino_v2_table_seats WHERE table_id=(SELECT id FROM casino_v2_tables WHERE table_id=$1) GROUP BY participant_kind", table)
            self.assertEqual({r['participant_kind']:r['n'] for r in seats}, {'player':1, 'bot':1})
            balance = await db.fetchval('SELECT sum(amount_rub) FROM user_cashback_ledger WHERE user_id=$1', user)
            self.assertEqual(balance, Decimal('90.00'))
            await asyncio.sleep(2)
            count = await db.fetchval("SELECT count(*) FROM user_cashback_ledger WHERE user_id=$1 AND type='hold'", user)
            self.assertEqual(count, 1)
        finally:
            await client.close()
            await db.close()

    async def test_60_players_autoplay_and_conservation(self):
        url, dsn, token = _validate_environment()
        run = uuid.uuid4().hex[:12]
        # Independent users for every run; never operate on existing accounts.
        base = 2000000000 + int(run[:8], 16) * 100
        users = [base + i for i in range(60)]
        tables = [f"qa60-{run}-{i}" for i in range(60)]
        db = await asyncpg.connect(dsn)
        client = FocusPayClient(base_url=url, internal_token=token)
        started = time.monotonic()
        try:
            async with db.transaction():
                await db.executemany("INSERT INTO bot_users(user_id,first_name) VALUES($1,'Synthetic QA')", [(u,) for u in users])
                await db.executemany("INSERT INTO user_cashback_ledger(user_id,type,amount_rub,order_id) VALUES($1,'accrual',100,$2)", [(u,f'qa60-fund-{run}-{i}') for i,u in enumerate(users)])
            games = ('pvp_dice', 'blackjack', 'baccara')
            created = await asyncio.gather(*[
                client.create_v2_table(table_id=tid, creator_id=users[i], game_type=games[i%3],
                    stake_rub='10.00', max_players=2, bot_count=0, draw_policy='tie_split',
                    expected_state_version=0, idempotency_key=f'create-{tid}')
                for i,tid in enumerate(tables)
            ], return_exceptions=True)
            errors = [_http_error(r) for r in created if isinstance(r, Exception)]
            self.assertEqual(errors, [], f'create errors: {errors}')
            joined = await asyncio.gather(*[
                client.v2_table_operation(tid,'seats',telegram_id=users[(i+1)%60],
                    expected_state_version=int(created[i]['table']['state_version']),idempotency_key=f'join-{tid}')
                for i,tid in enumerate(tables)
            ], return_exceptions=True)
            errors = [_http_error(r) for r in joined if isinstance(r, Exception)]
            self.assertEqual(errors, [], f'join errors: {errors}')
            await _advance_ready_countdown(db, tables)
            for _ in range(90):
                rows = await db.fetch('SELECT status,count(*) n FROM casino_v2_tables WHERE table_id=ANY($1::text[]) GROUP BY status', tables)
                counts = {r['status']:r['n'] for r in rows}
                if counts == {'finished': 60}:
                    break
                await asyncio.sleep(2)
            print('QA60', json.dumps({'elapsed_s':round(time.monotonic()-started,2),'statuses':counts}), flush=True)
            self.assertEqual(counts, {'finished':60})
            ledger = await db.fetchrow('''SELECT sum(amount_rub) total,
                count(*) FILTER(WHERE type='hold') holds,
                count(*) FILTER(WHERE type='spend') spends
                FROM user_cashback_ledger WHERE user_id=ANY($1::bigint[])''', users)
            self.assertEqual(ledger['holds'],0)
            self.assertEqual(ledger['spends'],120)
            self.assertEqual(ledger['total'],Decimal('5940.00'))
            settled = await db.fetchval('SELECT count(*) FROM casino_v2_settlements s JOIN casino_v2_tables t ON t.id=s.table_id WHERE t.table_id=ANY($1::text[])',tables)
            outbox = await db.fetchval('SELECT count(*) FROM casino_v2_notification_outbox o JOIN casino_v2_tables t ON t.id=o.table_id WHERE t.table_id=ANY($1::text[])',tables)
            self.assertEqual(settled,60)
            self.assertEqual(outbox,120)
            print('QA60 ledger conserved; 120 spends, 0 holds, 60 settlements, 120 outbox records', flush=True)
        finally:
            await client.close()
            await db.close()

-- Telegram origin chat for shared-table chips, and outbox rows that are not
-- casino_games (roulette rounds live in casino_roulette_rounds).
-- Apply after add_casino_roulette_table_chips.sql. Repeat is a no-op.
BEGIN;

ALTER TABLE casino_roulette_bets
    ADD COLUMN IF NOT EXISTS notify_chat_id BIGINT;

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    FOR constraint_name IN
        SELECT pg_constraint.conname
        FROM pg_constraint
        WHERE pg_constraint.conrelid = 'public.casino_notification_outbox'::regclass
          AND pg_constraint.contype = 'f'
          AND pg_get_constraintdef(pg_constraint.oid) LIKE '%game_id%'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.casino_notification_outbox DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END $$;

COMMENT ON COLUMN casino_roulette_bets.notify_chat_id IS
    'Telegram chat to notify when this round settles; NULL for site-only chips.';

COMMIT;

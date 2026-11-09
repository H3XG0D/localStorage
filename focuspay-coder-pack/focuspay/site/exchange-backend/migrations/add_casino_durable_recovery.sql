-- P0 casino recovery: durable lifecycle state and at-least-once notification outbox.
-- Additive and fail-closed. Apply after add_casino_tables.sql and fix_casino_backend_integrity.sql.
BEGIN;

-- Do not silently apply this migration to an unexpected or partially restored schema.
DO $$
DECLARE
    required_column TEXT;
BEGIN
    IF to_regclass('public.casino_games') IS NULL
       OR to_regclass('public.casino_balance_holds') IS NULL
       OR to_regclass('public.casino_settings') IS NULL THEN
        RAISE EXCEPTION 'casino durable recovery requires casino_games, casino_balance_holds, and casino_settings';
    END IF;

    FOREACH required_column IN ARRAY ARRAY[
        'game_id', 'game_type', 'creator_id', 'opponent_id', 'bet_rub',
        'creator_hold_id', 'opponent_hold_id', 'status', 'game_data', 'created_at'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'casino_games'
              AND column_name = required_column
        ) THEN
            RAISE EXCEPTION 'casino_games.% is required before durable recovery migration', required_column;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM casino_games WHERE game_id IS NULL OR btrim(game_id) = ''
    ) OR EXISTS (
        SELECT 1 FROM casino_games GROUP BY game_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'casino_games has invalid or duplicate game_id values';
    END IF;

    IF EXISTS (
        SELECT 1 FROM casino_games
        WHERE creator_hold_id IS NOT NULL
        GROUP BY creator_hold_id HAVING count(*) > 1
    ) OR EXISTS (
        SELECT 1 FROM casino_games
        WHERE opponent_hold_id IS NOT NULL
        GROUP BY opponent_hold_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'casino_games has duplicate hold references';
    END IF;
END $$;

ALTER TABLE casino_games
    ADD COLUMN IF NOT EXISTS state_version INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS game_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS outcome JSONB,
    ADD COLUMN IF NOT EXISTS outcome_committed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS recovery_claim_token VARCHAR(128),
    ADD COLUMN IF NOT EXISTS recovery_claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recovery_completed_at TIMESTAMPTZ;

-- `raffle` had no durable, auditable draw lifecycle. Keep its old rows readable,
-- but prevent it from being created by the new game flow, including on partially
-- configured installations where the setting row has not been seeded yet.
INSERT INTO casino_settings (key, value, description)
VALUES ('enabled_games', '{"raffle": false}'::jsonb, 'Casino games enabled flags')
ON CONFLICT (key) DO UPDATE
SET value = jsonb_set(COALESCE(casino_settings.value, '{}'::jsonb), '{raffle}', 'false'::jsonb, true),
    updated_at = now();

ALTER TABLE casino_games DROP CONSTRAINT IF EXISTS casino_games_status_check;
ALTER TABLE casino_games
    ADD CONSTRAINT casino_games_status_check CHECK (
        status IN ('waiting', 'active', 'outcome_committed', 'finished', 'cancelled', 'expired', 'manual_review')
    ) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_status_check;

ALTER TABLE casino_games DROP CONSTRAINT IF EXISTS casino_games_state_version_nonnegative;
ALTER TABLE casino_games
    ADD CONSTRAINT casino_games_state_version_nonnegative CHECK (state_version >= 0) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_state_version_nonnegative;

CREATE INDEX IF NOT EXISTS idx_casino_games_recovery
    ON casino_games (status, recovery_completed_at, recovery_claimed_at, updated_at)
    WHERE status IN ('waiting', 'active', 'outcome_committed');

CREATE TABLE IF NOT EXISTS casino_notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    game_id VARCHAR(64) NOT NULL REFERENCES casino_games(game_id) ON DELETE RESTRICT,
    recipient_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_token VARCHAR(128),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (game_id, event_type, recipient_id)
);

-- Earlier deployments may already have an outbox without a recipient. There is
-- no safe way to reconstruct recipient-specific deliveries from those rows: do
-- not guess, overwrite, or silently discard them. An operator must reconcile
-- them before applying this migration.
ALTER TABLE casino_notification_outbox
    ADD COLUMN IF NOT EXISTS recipient_id BIGINT;

DO $$
DECLARE
    required_column TEXT;
BEGIN
    FOREACH required_column IN ARRAY ARRAY[
        'id', 'event_key', 'event_type', 'game_id', 'recipient_id', 'payload',
        'status', 'attempts', 'available_at', 'claim_token', 'claimed_at',
        'completed_at', 'last_error', 'created_at', 'updated_at'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'casino_notification_outbox'
              AND column_name = required_column
        ) THEN
            RAISE EXCEPTION 'casino_notification_outbox.% is required before durable recovery migration', required_column;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1 FROM casino_notification_outbox
        WHERE recipient_id IS NULL OR recipient_id <= 0
    ) THEN
        RAISE EXCEPTION
            'casino_notification_outbox has rows without a valid recipient_id; reconcile them before durable recovery migration';
    END IF;

    IF EXISTS (
        SELECT 1 FROM casino_notification_outbox
        GROUP BY game_id, event_type, recipient_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'casino_notification_outbox has duplicate (game_id, event_type, recipient_id) rows; reconcile them before durable recovery migration';
    END IF;
END $$;

ALTER TABLE casino_notification_outbox
    ALTER COLUMN recipient_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint constraint_def
        WHERE constraint_def.conrelid = 'casino_notification_outbox'::regclass
          AND constraint_def.contype IN ('p', 'u')
          AND ARRAY(
              SELECT attribute_def.attname::text
              FROM unnest(constraint_def.conkey) WITH ORDINALITY AS key_column(attnum, position)
              JOIN pg_attribute attribute_def
                ON attribute_def.attrelid = constraint_def.conrelid
               AND attribute_def.attnum = key_column.attnum
              ORDER BY key_column.position
          ) = ARRAY['game_id', 'event_type', 'recipient_id']::text[]
    ) THEN
        ALTER TABLE casino_notification_outbox
            ADD CONSTRAINT casino_notification_outbox_game_event_recipient_key
            UNIQUE (game_id, event_type, recipient_id);
    END IF;
END $$;

ALTER TABLE casino_notification_outbox
    DROP CONSTRAINT IF EXISTS casino_notification_outbox_recipient_id_positive;
ALTER TABLE casino_notification_outbox
    ADD CONSTRAINT casino_notification_outbox_recipient_id_positive
    CHECK (recipient_id > 0) NOT VALID;
ALTER TABLE casino_notification_outbox
    VALIDATE CONSTRAINT casino_notification_outbox_recipient_id_positive;

CREATE INDEX IF NOT EXISTS idx_casino_notification_outbox_claim
    ON casino_notification_outbox (status, available_at, claimed_at, id)
    WHERE status IN ('pending', 'processing');

COMMIT;

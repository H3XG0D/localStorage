-- House bankroll, auditable robot policies, and private casino game support.
-- Apply after add_casino_tables.sql, fix_casino_backend_integrity.sql, and add_casino_durable_recovery.sql.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_games') IS NULL
       OR to_regclass('public.casino_balance_holds') IS NULL
       OR to_regclass('public.casino_settings') IS NULL THEN
        RAISE EXCEPTION 'casino house bankroll requires the existing casino schema';
    END IF;
END $$;

-- The house account is never a Telegram player. A row is created only by an
-- explicit finance-owner funding operation; zero balance denies new games.
CREATE TABLE IF NOT EXISTS casino_house_accounts (
    id BIGSERIAL PRIMARY KEY,
    account_key VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL,
    balance_rub NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (balance_rub >= 0),
    reserved_rub NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (reserved_rub >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reserved_rub <= balance_rub)
);

CREATE TABLE IF NOT EXISTS casino_house_ledger (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    game_id VARCHAR(64) REFERENCES casino_games(game_id) ON DELETE RESTRICT,
    entry_key VARCHAR(128) NOT NULL UNIQUE,
    entry_type VARCHAR(24) NOT NULL CHECK (entry_type IN ('funding', 'adjustment', 'game_settlement', 'reservation_release')),
    amount_rub NUMERIC(14, 2) NOT NULL,
    balance_after_rub NUMERIC(14, 2) NOT NULL CHECK (balance_after_rub >= 0),
    reason TEXT NOT NULL,
    created_by VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, game_id, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_casino_house_ledger_account_created
    ON casino_house_ledger (account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_house_ledger_game
    ON casino_house_ledger (game_id) WHERE game_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS casino_house_reservations (
    id BIGSERIAL PRIMARY KEY,
    reservation_key VARCHAR(128) NOT NULL UNIQUE,
    account_id BIGINT NOT NULL REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    game_id VARCHAR(64) NOT NULL UNIQUE REFERENCES casino_games(game_id) ON DELETE RESTRICT,
    amount_rub NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'settled', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ,
    CHECK (
        (status = 'active' AND settled_at IS NULL AND released_at IS NULL)
        OR (status = 'settled' AND settled_at IS NOT NULL AND released_at IS NULL)
        OR (status = 'released' AND released_at IS NOT NULL AND settled_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_casino_house_reservations_active
    ON casino_house_reservations (account_id, status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS casino_robot_profiles (
    id BIGSERIAL PRIMARY KEY,
    profile_key VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL,
    mode VARCHAR(16) NOT NULL CHECK (mode IN ('house_robot', 'pvp_robot')),
    account_id BIGINT NOT NULL REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_games JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(allowed_games) = 'array'),
    min_bet_rub NUMERIC(12, 2) NOT NULL CHECK (min_bet_rub > 0),
    max_bet_rub NUMERIC(12, 2) NOT NULL CHECK (max_bet_rub >= min_bet_rub),
    max_concurrent_games INTEGER NOT NULL DEFAULT 1 CHECK (max_concurrent_games > 0),
    max_exposure_rub NUMERIC(14, 2) NOT NULL CHECK (max_exposure_rub >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_house_policies (
    id BIGSERIAL PRIMARY KEY,
    policy_key VARCHAR(64) NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    game_type VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    payout_multiplier NUMERIC(12, 6) NOT NULL CHECK (payout_multiplier >= 0),
    win_probability NUMERIC(12, 8) NOT NULL CHECK (win_probability > 0 AND win_probability < 1),
    terms JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_key, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_house_policies_active_game
    ON casino_house_policies (game_type) WHERE is_active;

ALTER TABLE casino_games
    ADD COLUMN IF NOT EXISTS counterparty_kind VARCHAR(16) NOT NULL DEFAULT 'player',
    ADD COLUMN IF NOT EXISTS house_account_id BIGINT REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS robot_profile_id BIGINT REFERENCES casino_robot_profiles(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS house_policy_id BIGINT REFERENCES casino_house_policies(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS rng_commit VARCHAR(128),
    ADD COLUMN IF NOT EXISTS rng_seed_reveal VARCHAR(128),
    ADD COLUMN IF NOT EXISTS rng_nonce BIGINT;

ALTER TABLE casino_games DROP CONSTRAINT IF EXISTS casino_games_counterparty_kind_check;
ALTER TABLE casino_games ADD CONSTRAINT casino_games_counterparty_kind_check
    CHECK (counterparty_kind IN ('player', 'house_robot', 'pvp_robot')) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_counterparty_kind_check;

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'casino_games'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%pvp_dice%'
      AND pg_get_constraintdef(oid) LIKE '%game_type%'
    LIMIT 1;
    IF constraint_name IS NULL THEN
        RAISE EXCEPTION 'original casino_games game_type constraint not found';
    END IF;
    EXECUTE format('ALTER TABLE casino_games DROP CONSTRAINT %I', constraint_name);
END $$;
ALTER TABLE casino_games ADD CONSTRAINT casino_games_game_type_check
    CHECK (game_type IN ('pvp_dice', 'pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball', 'baccara', 'blackjack', 'raffle', 'cub')) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_game_type_check;

INSERT INTO casino_house_accounts (account_key, display_name)
VALUES ('main', 'Основной банк казино')
ON CONFLICT (account_key) DO NOTHING;

INSERT INTO casino_robot_profiles (
    profile_key, display_name, mode, account_id, is_active, allowed_games,
    min_bet_rub, max_bet_rub, max_concurrent_games, max_exposure_rub
)
SELECT 'focuscasino-house', 'FocusCasino', 'house_robot', id, FALSE, '["cub"]'::jsonb,
       10, 100000, 1, 0
FROM casino_house_accounts WHERE account_key = 'main'
ON CONFLICT (profile_key) DO NOTHING;

INSERT INTO casino_house_policies (
    policy_key, version, game_type, is_active, payout_multiplier, win_probability, terms
) VALUES (
    'cub-standard', 1, 'cub', FALSE, 2.000000, 0.50000000,
    '{"rng":"sha256-hmac","outcome":"binary","rtp_percent":"100.00"}'::jsonb
) ON CONFLICT (policy_key, version) DO NOTHING;

INSERT INTO casino_settings (key, value, description)
VALUES ('enabled_games', '{"cub": false}'::jsonb, 'Casino games enabled flags')
ON CONFLICT (key) DO UPDATE
SET value = COALESCE(casino_settings.value, '{}'::jsonb) || jsonb_build_object(
    'cub', COALESCE(casino_settings.value->'cub', 'false'::jsonb)
), updated_at = now();

CREATE TABLE IF NOT EXISTS casino_house_rng_commits (
    game_id VARCHAR(64) NOT NULL UNIQUE,
    commit_hash VARCHAR(128) PRIMARY KEY,
    game_type VARCHAR(32) NOT NULL,
    telegram_id BIGINT NOT NULL,
    server_seed VARCHAR(128) NOT NULL,
    nonce BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'consumed', 'expired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '10 minutes'
);
CREATE INDEX IF NOT EXISTS idx_casino_house_rng_commits_pending
    ON casino_house_rng_commits (telegram_id, game_type, expires_at)
    WHERE status = 'pending';

COMMIT;

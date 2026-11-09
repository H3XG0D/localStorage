-- Long nardy tables. One match, mars lock, no cube.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_nardy_tables (
    id BIGSERIAL PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL UNIQUE,
    creator_id BIGINT NOT NULL CHECK (creator_id <> 0),
    white_user_id BIGINT,
    black_user_id BIGINT,
    stake_rub NUMERIC(14,2) NOT NULL CHECK (stake_rub > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'running', 'done', 'closed')),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    escrow_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (escrow_rub >= 0),
    house_rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (house_rake_rub >= 0),
    server_seed VARCHAR(128) NOT NULL,
    client_seed VARCHAR(64) NOT NULL,
    commit_hash VARCHAR(64) NOT NULL,
    game_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_deadline_at TIMESTAMPTZ,
    seed_revealed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (white_user_id IS NULL OR white_user_id <> 0),
    CHECK (black_user_id IS NULL OR black_user_id <> 0),
    CHECK (white_user_id IS NULL OR black_user_id IS NULL OR white_user_id <> black_user_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_nardy_tables_open
    ON casino_nardy_tables (status, created_at DESC);

COMMIT;

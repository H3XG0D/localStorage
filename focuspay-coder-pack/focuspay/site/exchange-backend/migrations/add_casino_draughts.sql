-- Russian draughts tables. One stake from each wallet, holdem rake on a win.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_draughts_tables (
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
    rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rake_rub >= 0),
    moves JSONB NOT NULL DEFAULT '[]'::jsonb,
    draw_offer_user_id BIGINT,
    result VARCHAR(16),
    result_reason VARCHAR(32) NOT NULL DEFAULT '',
    action_deadline_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (white_user_id IS NULL OR white_user_id <> 0),
    CHECK (black_user_id IS NULL OR black_user_id <> 0),
    CHECK (white_user_id IS NULL OR black_user_id IS NULL OR white_user_id <> black_user_id),
    CHECK (result IS NULL OR result IN ('white', 'black', 'draw'))
);

CREATE INDEX IF NOT EXISTS idx_casino_draughts_tables_open
    ON casino_draughts_tables (status, created_at DESC);

INSERT INTO casino_settings (key, value, description) VALUES
    ('draughts_move_timeout_seconds', '{"value": 30}'::jsonb, 'Russian draughts move timeout (seconds)')
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"russian_draughts": false}'::jsonb
WHERE key = 'enabled_games';

COMMIT;

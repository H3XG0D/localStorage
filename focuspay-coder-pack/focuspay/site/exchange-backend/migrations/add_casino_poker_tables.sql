-- Hold'em cash tables (web PvP). Additive: v2 dice tables and legacy duels stay untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_poker_tables (
    id BIGSERIAL PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL UNIQUE,
    creator_id BIGINT NOT NULL CHECK (creator_id <> 0),
    max_seats SMALLINT NOT NULL CHECK (max_seats BETWEEN 2 AND 6),
    small_blind_rub NUMERIC(14,2) NOT NULL CHECK (small_blind_rub > 0),
    big_blind_rub NUMERIC(14,2) NOT NULL CHECK (big_blind_rub >= small_blind_rub),
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'running', 'closed')),
    button_seat SMALLINT CHECK (button_seat IS NULL OR button_seat BETWEEN 1 AND 6),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    escrow_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (escrow_rub >= 0),
    house_rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (house_rake_rub >= 0),
    current_hand_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_poker_seats (
    id BIGSERIAL PRIMARY KEY,
    table_pk BIGINT NOT NULL REFERENCES casino_poker_tables(id) ON DELETE RESTRICT,
    seat_no SMALLINT NOT NULL CHECK (seat_no BETWEEN 1 AND 6),
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    stack_rub NUMERIC(14,2) NOT NULL CHECK (stack_rub >= 0),
    buy_in_rub NUMERIC(14,2) NOT NULL CHECK (buy_in_rub > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'sitting' CHECK (status IN ('sitting', 'leaving')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (table_pk, seat_no),
    UNIQUE (table_pk, user_id)
);

CREATE TABLE IF NOT EXISTS casino_poker_hands (
    id BIGSERIAL PRIMARY KEY,
    table_pk BIGINT NOT NULL REFERENCES casino_poker_tables(id) ON DELETE RESTRICT,
    hand_key VARCHAR(80) NOT NULL UNIQUE,
    hand_no INTEGER NOT NULL CHECK (hand_no > 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('running', 'complete')),
    commit_hash VARCHAR(64) NOT NULL,
    server_seed VARCHAR(128) NOT NULL,
    client_seed VARCHAR(64) NOT NULL,
    nonce INTEGER NOT NULL DEFAULT 0,
    seed_revealed_at TIMESTAMPTZ,
    game_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_deadline_at TIMESTAMPTZ,
    rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rake_rub >= 0),
    wager_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at TIMESTAMPTZ,
    UNIQUE (table_pk, hand_no)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_casino_poker_tables_current_hand'
    ) THEN
        ALTER TABLE casino_poker_tables
            ADD CONSTRAINT fk_casino_poker_tables_current_hand
            FOREIGN KEY (current_hand_id) REFERENCES casino_poker_hands(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_casino_poker_tables_status ON casino_poker_tables(status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_poker_seats_user ON casino_poker_seats(user_id) WHERE status = 'sitting';
CREATE INDEX IF NOT EXISTS idx_casino_poker_hands_table ON casino_poker_hands(table_pk, hand_no DESC);

INSERT INTO casino_settings (key, value, description) VALUES
    ('holdem_small_blind_rub', '{"amount": 10.0}'::jsonb, 'Hold''em small blind (₽)'),
    ('holdem_big_blind_rub', '{"amount": 20.0}'::jsonb, 'Hold''em big blind (₽)'),
    ('holdem_rake_percent', '{"percent": 5.0}'::jsonb, 'Hold''em rake percent of pot'),
    ('holdem_rake_cap_rub', '{"amount": 50.0}'::jsonb, 'Hold''em rake cap (₽); 0 = no cap'),
    ('holdem_action_timeout_seconds', '{"value": 30}'::jsonb, 'Hold''em action timeout (seconds)'),
    ('holdem_min_buyin_bb', '{"value": 20}'::jsonb, 'Hold''em min buy-in in big blinds'),
    ('holdem_max_buyin_bb', '{"value": 100}'::jsonb, 'Hold''em max buy-in in big blinds')
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"holdem": true}'::jsonb
WHERE key = 'enabled_games';

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"holdem": true}'::jsonb
WHERE key = 'provably_fair_enabled';

COMMENT ON TABLE casino_poker_tables IS 'Web NLHE cash tables; escrow_rub = seated stacks + current pot.';
COMMIT;

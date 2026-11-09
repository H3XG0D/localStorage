-- Shared European roulette table: one live round, one HMAC pocket, house pays each seat.
-- Apply after add_casino_roulette.sql. Settings keep existing values on repeat (DO NOTHING).
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_games') IS NULL
       OR to_regclass('public.casino_settings') IS NULL
       OR to_regclass('public.casino_house_accounts') IS NULL THEN
        RAISE EXCEPTION 'casino roulette table requires the existing casino schema';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS casino_roulette_rounds (
    id BIGSERIAL PRIMARY KEY,
    round_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'locked', 'spinning', 'settled')),
    commit_hash VARCHAR(64) NOT NULL,
    server_seed TEXT NOT NULL,
    closes_at TIMESTAMPTZ,
    pocket SMALLINT CHECK (pocket IS NULL OR (pocket >= 0 AND pocket <= 36)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS casino_roulette_bets (
    id BIGSERIAL PRIMARY KEY,
    round_pk BIGINT NOT NULL REFERENCES casino_roulette_rounds(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    bet VARCHAR(120) NOT NULL,
    stake_rub NUMERIC(14,2) NOT NULL CHECK (stake_rub > 0),
    hold_order_ref VARCHAR(80) NOT NULL,
    house_reserve_rub NUMERIC(14,2) NOT NULL CHECK (house_reserve_rub >= 0),
    display_name VARCHAR(80) NOT NULL DEFAULT '',
    game_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_pk, user_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_roulette_rounds_status ON casino_roulette_rounds (status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_roulette_bets_user ON casino_roulette_bets (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_roulette_live
    ON casino_roulette_rounds ((TRUE)) WHERE status IN ('open', 'locked', 'spinning');

INSERT INTO casino_settings (key, value, description) VALUES
    ('roulette_table_collect_seconds', '{"value": 25}'::jsonb, 'Roulette table betting window (seconds)'),
    ('roulette_table_max_players', '{"value": 24}'::jsonb, 'Roulette table max unique players before the wheel locks')
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE casino_roulette_rounds IS 'One live European roulette round; pocket from HMAC(round_id), house pays each seat.';
COMMIT;

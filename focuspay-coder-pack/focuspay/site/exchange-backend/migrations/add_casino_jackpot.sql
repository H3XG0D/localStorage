-- CSGETGO-style jackpot rounds. Additive: raffle/FocusLucky untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_jackpot_rounds (
    id BIGSERIAL PRIMARY KEY,
    round_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'locked', 'settled', 'refunded')),
    commit_hash VARCHAR(64) NOT NULL,
    roll TEXT,
    closes_at TIMESTAMPTZ,
    winning_ticket BIGINT,
    winner_id BIGINT,
    pot_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (pot_rub >= 0),
    rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rake_rub >= 0),
    payout_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (payout_rub >= 0),
    wager_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS casino_jackpot_bets (
    id BIGSERIAL PRIMARY KEY,
    round_pk BIGINT NOT NULL REFERENCES casino_jackpot_rounds(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    amount_rub NUMERIC(14,2) NOT NULL CHECK (amount_rub > 0),
    ticket_from BIGINT NOT NULL DEFAULT 0 CHECK (ticket_from >= 0),
    ticket_to BIGINT NOT NULL DEFAULT 0 CHECK (ticket_to >= ticket_from),
    hold_order_ref VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_pk, user_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_jackpot_rounds_status ON casino_jackpot_rounds (status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_jackpot_bets_user ON casino_jackpot_bets (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_jackpot_live
    ON casino_jackpot_rounds ((TRUE)) WHERE status IN ('open', 'locked');

INSERT INTO casino_settings (key, value, description) VALUES
    ('jackpot_collect_seconds', '{"value": 300}'::jsonb, 'Jackpot collection window (seconds)'),
    ('jackpot_max_players', '{"value": 30}'::jsonb, 'Jackpot max unique players before early spin'),
    ('jackpot_rake_percent', '{"percent": 5.0}'::jsonb, 'Jackpot house rake of the pot')
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"jackpot": true}'::jsonb
WHERE key = 'enabled_games';

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"jackpot": true}'::jsonb
WHERE key = 'provably_fair_enabled';

COMMENT ON TABLE casino_jackpot_rounds IS 'One live jackpot round; roll committed at open, revealed at lock.';
COMMIT;

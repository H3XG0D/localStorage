-- Fixed-stake rooms 2–N: equal bet, N seats, HMAC commit-reveal winner.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_fixed_room_rounds (
    id BIGSERIAL PRIMARY KEY,
    room_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'locked', 'settled', 'refunded')),
    creator_id BIGINT NOT NULL CHECK (creator_id <> 0),
    stake_rub NUMERIC(14,2) NOT NULL CHECK (stake_rub > 0),
    seat_count INT NOT NULL CHECK (seat_count >= 2 AND seat_count <= 20),
    commit_hash VARCHAR(64) NOT NULL,
    server_seed TEXT NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,
    winner_id BIGINT,
    winner_index INT,
    pot_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (pot_rub >= 0),
    rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rake_rub >= 0),
    payout_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (payout_rub >= 0),
    wager_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS casino_fixed_room_seats (
    id BIGSERIAL PRIMARY KEY,
    room_pk BIGINT NOT NULL REFERENCES casino_fixed_room_rounds(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    seat_no INT NOT NULL CHECK (seat_no >= 0),
    hold_order_ref VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (room_pk, user_id),
    UNIQUE (room_pk, seat_no)
);

CREATE INDEX IF NOT EXISTS idx_casino_fixed_room_rounds_status
    ON casino_fixed_room_rounds (status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_fixed_room_seats_user
    ON casino_fixed_room_seats (user_id);

INSERT INTO casino_settings (key, value, description) VALUES
    ('fixed_room_rake_percent', '{"percent": 5.0}'::jsonb, 'Fixed-stake room house rake of the pot'),
    ('fixed_room_max_seats', '{"value": 10}'::jsonb, 'Max seats in a fixed-stake room (2–N)'),
    ('fixed_room_collect_seconds', '{"value": 600}'::jsonb, 'Fixed-stake room fill window (seconds)')
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"fixed_room": true}'::jsonb
WHERE key = 'enabled_games';

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"fixed_room": true}'::jsonb
WHERE key = 'provably_fair_enabled';

COMMENT ON TABLE casino_fixed_room_rounds IS
    'Equal-stake rooms: N seats, HMAC commit-reveal winner. Not CSGETGO jackpot.';
COMMIT;

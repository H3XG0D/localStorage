-- Isolated synthetic/staging casino multiplayer v2. Additive: legacy casino tables are untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_v2_tables (
    id BIGSERIAL PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL UNIQUE,
    game_type VARCHAR(32) NOT NULL CHECK (game_type IN (
        'pvp_emoji', 'pvp_dice', 'pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball', 'blackjack', 'baccara'
    )),
    creator_id BIGINT NOT NULL CHECK (creator_id > 0),
    stake_rub NUMERIC(14,2) NOT NULL CHECK (stake_rub > 0),
    max_seats SMALLINT NOT NULL CHECK (max_seats BETWEEN 2 AND 6),
    status VARCHAR(24) NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft', 'open', 'ready', 'running', 'tie_break_running', 'outcome_committed',
        'settling', 'finished', 'cancelled', 'expired', 'manual_review'
    )),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    game_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome JSONB,
    outcome_committed_at TIMESTAMPTZ,
    settlement_payload JSONB,
    recovery_claim_token VARCHAR(128),
    recovery_claimed_at TIMESTAMPTZ,
    recovery_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_v2_table_seats (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    seat_no SMALLINT NOT NULL CHECK (seat_no BETWEEN 1 AND 6),
    participant_kind VARCHAR(12) NOT NULL CHECK (participant_kind IN ('player', 'bot')),
    telegram_id BIGINT CHECK (telegram_id IS NULL OR telegram_id > 0),
    robot_profile_id BIGINT REFERENCES casino_robot_profiles(id) ON DELETE RESTRICT,
    hold_order_ref VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'seated' CHECK (status IN ('seated', 'settled', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (table_id, seat_no),
    CHECK ((participant_kind = 'player' AND telegram_id IS NOT NULL AND robot_profile_id IS NULL AND hold_order_ref IS NOT NULL)
        OR (participant_kind = 'bot' AND telegram_id IS NULL AND robot_profile_id IS NOT NULL AND hold_order_ref IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_casino_v2_seats_player
    ON casino_v2_table_seats (table_id, telegram_id) WHERE telegram_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS casino_v2_house_reservations (
    id BIGSERIAL PRIMARY KEY,
    reservation_key VARCHAR(128) NOT NULL UNIQUE,
    table_id BIGINT NOT NULL UNIQUE REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    amount_rub NUMERIC(14,2) NOT NULL CHECK (amount_rub > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'settled', 'released')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ
);

-- The outcome is immutable: a table can have exactly one committed outcome.
CREATE TABLE IF NOT EXISTS casino_v2_settlements (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL UNIQUE REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    outcome_kind VARCHAR(16) NOT NULL CHECK (outcome_kind IN ('winner', 'tie_split')),
    commission_rub NUMERIC(14,2) NOT NULL CHECK (commission_rub >= 0),
    pot_rub NUMERIC(14,2) NOT NULL CHECK (pot_rub > 0),
    payout_rub NUMERIC(14,2) NOT NULL CHECK (payout_rub >= 0),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_v2_lifecycle_idempotency (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    table_key VARCHAR(64) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (table_key, operation, idempotency_key)
);

CREATE TABLE IF NOT EXISTS casino_v2_notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    table_id BIGINT NOT NULL REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    recipient_id BIGINT NOT NULL CHECK (recipient_id > 0),
    event_type VARCHAR(32) NOT NULL,
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
    UNIQUE (table_id, event_type, recipient_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_v2_tables_status ON casino_v2_tables(status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_v2_tables_recovery ON casino_v2_tables(status, recovery_completed_at, recovery_claimed_at, updated_at)
    WHERE status IN ('draft', 'open', 'ready', 'running', 'tie_break_running', 'outcome_committed', 'settling');
CREATE INDEX IF NOT EXISTS idx_casino_v2_seats_table ON casino_v2_table_seats(table_id, seat_no);
CREATE INDEX IF NOT EXISTS idx_casino_v2_outbox_claim ON casino_v2_notification_outbox(status, available_at, claimed_at, id)
    WHERE status IN ('pending', 'processing');

COMMENT ON TABLE casino_v2_tables IS 'Isolated synthetic/staging multiplayer casino v2 tables; legacy casino tables are untouched.';
COMMENT ON TABLE casino_v2_settlements IS 'Immutable v2 settlement audit; commission is exactly 5% of full pot.';
COMMIT;

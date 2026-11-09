-- House-multi dice: 2–6 humans vs casino, each with own stake. Not a V2 equal-stake pot.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_house_tables (
    id BIGSERIAL PRIMARY KEY,
    table_id VARCHAR(64) NOT NULL UNIQUE,
    game_type VARCHAR(32) NOT NULL DEFAULT 'pvp_dice',
    creator_id BIGINT NOT NULL CHECK (creator_id <> 0),
    max_seats SMALLINT NOT NULL CHECK (max_seats BETWEEN 2 AND 6),
    house_bot_count SMALLINT NOT NULL DEFAULT 1 CHECK (house_bot_count BETWEEN 0 AND 6),
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'running', 'closed')),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    rng_seed VARCHAR(128),
    game_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_house_table_seats (
    id BIGSERIAL PRIMARY KEY,
    table_pk BIGINT NOT NULL REFERENCES casino_house_tables(id) ON DELETE RESTRICT,
    seat_no SMALLINT NOT NULL CHECK (seat_no BETWEEN 1 AND 20),
    kind VARCHAR(16) NOT NULL CHECK (kind IN ('player', 'house_robot')),
    telegram_id BIGINT,
    profile_id BIGINT REFERENCES casino_robot_profiles(id) ON DELETE RESTRICT,
    profile_key VARCHAR(64),
    display_name VARCHAR(128),
    stake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (stake_rub >= 0),
    payout_rub NUMERIC(14,2),
    commission_rub NUMERIC(14,2),
    won BOOLEAN,
    player_pips SMALLINT CHECK (player_pips IS NULL OR (player_pips BETWEEN 1 AND 6)),
    house_pips SMALLINT CHECK (house_pips IS NULL OR (house_pips BETWEEN 1 AND 6)),
    cub_game_id VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'seated' CHECK (status IN ('seated', 'settled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (table_pk, seat_no),
    CONSTRAINT casino_house_seat_kind_ok CHECK (
        (kind = 'player' AND telegram_id IS NOT NULL AND telegram_id <> 0 AND stake_rub > 0)
        OR (kind = 'house_robot' AND telegram_id IS NULL AND stake_rub = 0)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_casino_house_seats_player
    ON casino_house_table_seats (table_pk, telegram_id)
    WHERE telegram_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_casino_house_tables_status
    ON casino_house_tables (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_house_seats_table
    ON casino_house_table_seats (table_pk, seat_no);

COMMENT ON TABLE casino_house_tables IS
    'Web cub vs house, 2-6 humans; each seat settles with calculate_house_settlement. Not V2 pot.';
COMMENT ON TABLE casino_house_table_seats IS
    'Human seats hold their own stake. house_robot seats are visual; they do not debit user wallets.';

COMMIT;

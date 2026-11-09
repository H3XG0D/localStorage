-- Clan vs clan: player-wallet stakes, no clan bank. HMAC picks the winning clan.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_clan_wars (
    id BIGSERIAL PRIMARY KEY,
    war_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'accepted', 'locked', 'settled', 'refunded')),
    creator_id BIGINT NOT NULL CHECK (creator_id <> 0),
    challenger_clan_id BIGINT NOT NULL REFERENCES casino_clans(id) ON DELETE RESTRICT,
    opponent_clan_id BIGINT REFERENCES casino_clans(id) ON DELETE RESTRICT,
    stake_rub NUMERIC(14,2) NOT NULL CHECK (stake_rub > 0),
    fighters_needed INT NOT NULL CHECK (fighters_needed >= 1 AND fighters_needed <= 20),
    commit_hash VARCHAR(64) NOT NULL,
    server_seed TEXT NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,
    winner_clan_id BIGINT,
    winner_index INT,
    pot_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (pot_rub >= 0),
    rake_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rake_rub >= 0),
    payout_per_winner_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (payout_per_winner_rub >= 0),
    wager_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at TIMESTAMPTZ,
    locked_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ,
    CHECK (opponent_clan_id IS NULL OR opponent_clan_id <> challenger_clan_id)
);

CREATE TABLE IF NOT EXISTS casino_clan_war_fighters (
    id BIGSERIAL PRIMARY KEY,
    war_pk BIGINT NOT NULL REFERENCES casino_clan_wars(id) ON DELETE RESTRICT,
    clan_id BIGINT NOT NULL REFERENCES casino_clans(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    hold_order_ref VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (war_pk, user_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_clan_wars_status
    ON casino_clan_wars (status, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_clan_war_fighters_user
    ON casino_clan_war_fighters (user_id);
CREATE INDEX IF NOT EXISTS idx_casino_clan_war_fighters_clan
    ON casino_clan_war_fighters (war_pk, clan_id);

INSERT INTO casino_settings (key, value, description) VALUES
    ('clan_war_rake_percent', '{"percent": 5.0}'::jsonb, 'Clan war house rake of the combined pot'),
    ('clan_war_max_fighters', '{"value": 5}'::jsonb, 'Fighters needed per clan in a war'),
    ('clan_war_collect_seconds', '{"value": 1800}'::jsonb, 'Clan war fill window (seconds)')
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"clan_war": true}'::jsonb
WHERE key = 'enabled_games';

UPDATE casino_settings
SET value = COALESCE(value, '{}'::jsonb) || '{"clan_war": true}'::jsonb
WHERE key = 'provably_fair_enabled';

COMMENT ON TABLE casino_clan_wars IS
    'Clan vs clan match. Stakes from player wallets; clans have no balance.';
COMMENT ON TABLE casino_clan_war_fighters IS
    'Opt-in fighters. Each row is a player hold, not a clan treasury debit.';
COMMIT;

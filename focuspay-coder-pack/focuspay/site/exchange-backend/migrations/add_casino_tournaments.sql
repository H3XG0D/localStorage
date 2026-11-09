-- Multi-tournament system for FocusBet: flexible entry (free/promo/paid),
-- custom starting chips, optional rebuys, fixed/dynamic prize pools, live leaderboard.

CREATE TABLE IF NOT EXISTS casino_tournaments (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(140) NOT NULL DEFAULT 'Турнир FocusBet',
    subtitle VARCHAR(280) NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL DEFAULT 'draft',
    starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ends_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '1 hour'),
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    entry_mode VARCHAR(24) NOT NULL DEFAULT 'promo',
    promo_code VARCHAR(64),
    entry_fee_rub NUMERIC(18, 2) NOT NULL DEFAULT 0,
    starting_chips NUMERIC(18, 2) NOT NULL DEFAULT 1000,
    min_bet_chips NUMERIC(18, 2) NOT NULL DEFAULT 10,
    max_bet_chips NUMERIC(18, 2) NOT NULL DEFAULT 1000,
    rebuy_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rebuy_fee_rub NUMERIC(18, 2) NOT NULL DEFAULT 0,
    rebuy_chips NUMERIC(18, 2) NOT NULL DEFAULT 1000,
    max_rebuys_per_user INTEGER NOT NULL DEFAULT 0,
    rebuy_max_balance_chips NUMERIC(18, 2) NOT NULL DEFAULT 0,
    prize_mode VARCHAR(24) NOT NULL DEFAULT 'fixed',
    guaranteed_pool_rub NUMERIC(18, 2) NOT NULL DEFAULT 2000,
    entry_pool_share_pct NUMERIC(5, 2) NOT NULL DEFAULT 100,
    prize_places JSONB NOT NULL DEFAULT '[{"place":1,"prize_rub":1000,"share_pct":50},{"place":2,"prize_rub":500,"share_pct":25},{"place":3,"prize_rub":500,"share_pct":25}]'::jsonb,
    require_exchange_history BOOLEAN NOT NULL DEFAULT TRUE,
    min_exchange_count INTEGER NOT NULL DEFAULT 1,
    min_exchange_volume_rub NUMERIC(18, 2) NOT NULL DEFAULT 0,
    min_rounds_for_prize INTEGER NOT NULL DEFAULT 1,
    max_participants INTEGER NOT NULL DEFAULT 500,
    min_participants INTEGER NOT NULL DEFAULT 2,
    max_bots_per_table INTEGER NOT NULL DEFAULT 1,
    allowed_games JSONB NOT NULL DEFAULT '["pvp_dice","baccara","blackjack","roulette","fixed_room","jackpot"]'::jsonb,
    settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournaments_status_chk
        CHECK (status IN ('draft', 'registration', 'active', 'finished', 'cancelled')),
    CONSTRAINT casino_tournaments_entry_mode_chk
        CHECK (entry_mode IN ('free', 'promo', 'paid', 'promo_or_paid')),
    CONSTRAINT casino_tournaments_prize_mode_chk
        CHECK (prize_mode IN ('fixed', 'dynamic')),
    CONSTRAINT casino_tournaments_duration_chk
        CHECK (duration_minutes >= 5 AND duration_minutes <= 43200),
    CONSTRAINT casino_tournaments_chips_chk
        CHECK (starting_chips > 0 AND min_bet_chips > 0 AND max_bet_chips >= min_bet_chips),
    CONSTRAINT casino_tournaments_rebuy_chk
        CHECK (rebuy_fee_rub >= 0 AND rebuy_chips > 0 AND max_rebuys_per_user >= 0 AND max_rebuys_per_user <= 100 AND rebuy_max_balance_chips >= 0),
    CONSTRAINT casino_tournaments_pool_chk
        CHECK (entry_fee_rub >= 0 AND guaranteed_pool_rub >= 0 AND entry_pool_share_pct >= 0 AND entry_pool_share_pct <= 100),
    CONSTRAINT casino_tournaments_bots_chk
        CHECK (max_bots_per_table >= 0 AND max_bots_per_table <= 1)
);

CREATE INDEX IF NOT EXISTS idx_casino_tournaments_status_starts
    ON casino_tournaments (status, starts_at DESC, id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_casino_tournaments_promo_upper
    ON casino_tournaments (UPPER(promo_code))
    WHERE promo_code IS NOT NULL AND promo_code <> '' AND status IN ('draft', 'registration', 'active');

CREATE TABLE IF NOT EXISTS casino_tournament_entries (
    id BIGSERIAL PRIMARY KEY,
    tournament_id BIGINT NOT NULL REFERENCES casino_tournaments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    chips_balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
    starting_chips_granted NUMERIC(18, 2) NOT NULL DEFAULT 0,
    rebuys_count INTEGER NOT NULL DEFAULT 0,
    paid_rub_total NUMERIC(18, 2) NOT NULL DEFAULT 0,
    rounds_played INTEGER NOT NULL DEFAULT 0,
    wins_count INTEGER NOT NULL DEFAULT 0,
    total_wagered_chips NUMERIC(18, 2) NOT NULL DEFAULT 0,
    entered_via VARCHAR(24) NOT NULL DEFAULT 'free',
    promo_code_used VARCHAR(64),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    final_rank INTEGER,
    prize_rub NUMERIC(18, 2),
    prize_order_id VARCHAR(64),
    prize_credited_at TIMESTAMPTZ,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournament_entries_uniq UNIQUE (tournament_id, user_id),
    CONSTRAINT casino_tournament_entries_chips_chk CHECK (chips_balance >= 0),
    CONSTRAINT casino_tournament_entries_rebuys_chk CHECK (rebuys_count >= 0),
    CONSTRAINT casino_tournament_entries_paid_chk CHECK (paid_rub_total >= 0),
    CONSTRAINT casino_tournament_entries_rounds_chk CHECK (rounds_played >= 0)
);

CREATE INDEX IF NOT EXISTS idx_casino_tournament_entries_leaderboard
    ON casino_tournament_entries (tournament_id, blocked, chips_balance DESC, rounds_played DESC, joined_at ASC);

CREATE INDEX IF NOT EXISTS idx_casino_tournament_entries_user
    ON casino_tournament_entries (user_id, tournament_id DESC);

CREATE TABLE IF NOT EXISTS casino_tournament_user_state (
    user_id BIGINT PRIMARY KEY,
    active_tournament_id BIGINT REFERENCES casino_tournaments(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS casino_tournament_holds (
    order_ref VARCHAR(64) PRIMARY KEY,
    tournament_id BIGINT NOT NULL REFERENCES casino_tournaments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    amount_chips NUMERIC(18, 2) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'hold',
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournament_holds_amount_chk CHECK (amount_chips >= 0),
    CONSTRAINT casino_tournament_holds_status_chk CHECK (status IN ('hold', 'spend', 'released'))
);

CREATE INDEX IF NOT EXISTS idx_casino_tournament_holds_user
    ON casino_tournament_holds (tournament_id, user_id, status);

CREATE TABLE IF NOT EXISTS casino_tournament_payouts (
    order_id VARCHAR(64) PRIMARY KEY,
    tournament_id BIGINT NOT NULL REFERENCES casino_tournaments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    amount_chips NUMERIC(18, 2) NOT NULL,
    game_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournament_payouts_amount_chk CHECK (amount_chips >= 0)
);

DO $$
BEGIN
    -- Optional tagging columns: skipped when the migration runs as a non-owner role.
    BEGIN
        IF to_regclass('public.casino_v2_tables') IS NOT NULL THEN
            ALTER TABLE casino_v2_tables
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT REFERENCES casino_tournaments(id) ON DELETE SET NULL;
        END IF;
        IF to_regclass('public.casino_fixed_room_rounds') IS NOT NULL THEN
            ALTER TABLE casino_fixed_room_rounds
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT REFERENCES casino_tournaments(id) ON DELETE SET NULL;
        END IF;
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'tournament_id columns skipped: not table owner';
    END;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT ALL PRIVILEGES ON TABLE casino_tournaments TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_entries TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_user_state TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_holds TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_payouts TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE casino_tournaments_id_seq TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE casino_tournament_entries_id_seq TO exchange_bot;
    END IF;
END $$;

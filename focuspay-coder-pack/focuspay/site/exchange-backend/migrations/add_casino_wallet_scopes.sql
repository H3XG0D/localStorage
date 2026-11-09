-- Wallet scopes for FocusBet: real RUB, bonus chips and one scope per tournament.
-- A scope is stamped on the player and on every table/round, so chips never meet money.

CREATE TABLE IF NOT EXISTS casino_bonus_wallets (
    user_id BIGINT PRIMARY KEY,
    chips_balance NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_wagered_chips NUMERIC(18, 2) NOT NULL DEFAULT 0,
    granted_total NUMERIC(18, 2) NOT NULL DEFAULT 0,
    wins_count INTEGER NOT NULL DEFAULT 0,
    rounds_played INTEGER NOT NULL DEFAULT 0,
    last_grant_at TIMESTAMPTZ,
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_bonus_wallets_balance_chk CHECK (chips_balance >= 0)
);

CREATE TABLE IF NOT EXISTS casino_bonus_holds (
    order_ref VARCHAR(80) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount_chips NUMERIC(18, 2) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'hold',
    note VARCHAR(300) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_bonus_holds_status_chk CHECK (status IN ('hold', 'spend', 'released')),
    CONSTRAINT casino_bonus_holds_amount_chk CHECK (amount_chips >= 0)
);

CREATE INDEX IF NOT EXISTS idx_casino_bonus_holds_user_status
    ON casino_bonus_holds (user_id, status);

CREATE TABLE IF NOT EXISTS casino_bonus_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL,
    amount_chips NUMERIC(18, 2) NOT NULL,
    order_id VARCHAR(80) NOT NULL UNIQUE,
    game_id VARCHAR(128) NOT NULL DEFAULT '',
    note VARCHAR(300) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_bonus_ledger_kind_chk CHECK (kind IN ('grant', 'bet', 'win', 'adjust'))
);

CREATE INDEX IF NOT EXISTS idx_casino_bonus_ledger_user
    ON casino_bonus_ledger (user_id, id DESC);

DO $$
BEGIN
    -- The player's active scope lives next to the tournament pointer that already exists.
    IF to_regclass('public.casino_tournament_user_state') IS NOT NULL THEN
        BEGIN
            ALTER TABLE casino_tournament_user_state
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_tournament_user_state
                DROP CONSTRAINT IF EXISTS casino_tournament_user_state_wallet_kind_chk;
            ALTER TABLE casino_tournament_user_state
                ADD CONSTRAINT casino_tournament_user_state_wallet_kind_chk
                CHECK (wallet_kind IN ('rub', 'bonus', 'tournament'));
            UPDATE casino_tournament_user_state
            SET wallet_kind = 'tournament'
            WHERE active_tournament_id IS NOT NULL AND wallet_kind = 'rub';
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'wallet_kind on casino_tournament_user_state skipped: not table owner';
        END;
    END IF;

    -- Scope stamp on every surface a player can sit at.
    BEGIN
        IF to_regclass('public.casino_v2_tables') IS NOT NULL THEN
            ALTER TABLE casino_v2_tables
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_v2_tables
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT;
            CREATE INDEX IF NOT EXISTS idx_casino_v2_tables_scope_lobby
                ON casino_v2_tables (game_type, status, wallet_kind, tournament_id);
        END IF;
        IF to_regclass('public.casino_games') IS NOT NULL THEN
            ALTER TABLE casino_games
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_games
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT;
            CREATE INDEX IF NOT EXISTS idx_casino_games_scope_lobby
                ON casino_games (game_type, status, wallet_kind, tournament_id);
        END IF;
        IF to_regclass('public.casino_fixed_room_rounds') IS NOT NULL THEN
            ALTER TABLE casino_fixed_room_rounds
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_fixed_room_rounds
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT;
            CREATE INDEX IF NOT EXISTS idx_casino_fixed_rooms_scope
                ON casino_fixed_room_rounds (status, wallet_kind, tournament_id);
        END IF;
        IF to_regclass('public.casino_jackpot_rounds') IS NOT NULL THEN
            ALTER TABLE casino_jackpot_rounds
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_jackpot_rounds
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT;
            CREATE INDEX IF NOT EXISTS idx_casino_jackpot_rounds_scope
                ON casino_jackpot_rounds (status, wallet_kind, tournament_id, id DESC);
        END IF;
        IF to_regclass('public.casino_roulette_rounds') IS NOT NULL THEN
            ALTER TABLE casino_roulette_rounds
                ADD COLUMN IF NOT EXISTS wallet_kind VARCHAR(16) NOT NULL DEFAULT 'rub';
            ALTER TABLE casino_roulette_rounds
                ADD COLUMN IF NOT EXISTS tournament_id BIGINT;
            CREATE INDEX IF NOT EXISTS idx_casino_roulette_rounds_scope
                ON casino_roulette_rounds (status, wallet_kind, tournament_id, id DESC);
        END IF;
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'wallet scope columns skipped: not table owner';
    END;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT ALL PRIVILEGES ON TABLE casino_bonus_wallets TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_bonus_holds TO exchange_bot;
        GRANT ALL PRIVILEGES ON TABLE casino_bonus_ledger TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE casino_bonus_ledger_id_seq TO exchange_bot;
    END IF;
END
$$;

-- Registry-shaped defaults (see casino_settings_registry.to_storage).
INSERT INTO casino_settings (key, value, description)
VALUES
    ('bonus_wallet_enabled', '{"enabled": true}'::jsonb, 'Бонусные фишки: отдельный кошелёк и отдельные столы'),
    ('bonus_wallet_grant_chips', '{"amount": 1000.0}'::jsonb, 'Номинал пополнения бонусного кошелька'),
    ('bonus_wallet_grant_cooldown_hours', '{"value": 24}'::jsonb, 'Пауза между пополнениями бонусного кошелька')
ON CONFLICT (key) DO NOTHING;

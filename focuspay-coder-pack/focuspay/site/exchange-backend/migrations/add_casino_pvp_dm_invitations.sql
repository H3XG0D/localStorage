-- Durable DM-created PVP games: pin the approved group binding and invitation delivery.
-- Apply after add_casino_durable_recovery.sql and add_casino_game_chat_bindings.sql.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_games') IS NULL
       OR to_regclass('public.casino_game_chat_bindings') IS NULL THEN
        RAISE EXCEPTION 'casino PVP DM invitations require casino_games and casino_game_chat_bindings';
    END IF;
END $$;

ALTER TABLE casino_games
    ADD COLUMN IF NOT EXISTS game_chat_binding_id BIGINT,
    ADD COLUMN IF NOT EXISTS game_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS game_chat_binding_revision BIGINT;

ALTER TABLE casino_games
    DROP CONSTRAINT IF EXISTS casino_games_game_chat_binding_id_fkey;
ALTER TABLE casino_games
    ADD CONSTRAINT casino_games_game_chat_binding_id_fkey
    FOREIGN KEY (game_chat_binding_id) REFERENCES casino_game_chat_bindings(id) ON DELETE RESTRICT;

ALTER TABLE casino_games
    DROP CONSTRAINT IF EXISTS casino_games_pinned_game_chat_check;
ALTER TABLE casino_games
    ADD CONSTRAINT casino_games_pinned_game_chat_check CHECK (
        (game_chat_binding_id IS NULL AND game_chat_id IS NULL AND game_chat_binding_revision IS NULL)
        OR (game_chat_binding_id IS NOT NULL AND game_chat_id < 0 AND game_chat_binding_revision IS NOT NULL)
    ) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_pinned_game_chat_check;

CREATE INDEX IF NOT EXISTS idx_casino_games_pinned_game_chat
    ON casino_games (game_chat_id, status)
    WHERE game_chat_id IS NOT NULL AND status IN ('waiting', 'active', 'outcome_committed');

CREATE TABLE IF NOT EXISTS casino_pvp_invitation_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    game_id VARCHAR(64) NOT NULL UNIQUE REFERENCES casino_games(game_id) ON DELETE RESTRICT,
    chat_id BIGINT NOT NULL CHECK (chat_id < 0),
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_token VARCHAR(128),
    claimed_at TIMESTAMPTZ,
    telegram_message_id BIGINT CHECK (telegram_message_id > 0),
    completed_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_casino_pvp_invitation_outbox_claim
    ON casino_pvp_invitation_outbox (status, available_at, claimed_at, id)
    WHERE status IN ('pending', 'processing');

COMMENT ON TABLE casino_pvp_invitation_outbox IS
    'At-least-once invitation publication intents for PVP games created from casino bot DMs';

COMMIT;

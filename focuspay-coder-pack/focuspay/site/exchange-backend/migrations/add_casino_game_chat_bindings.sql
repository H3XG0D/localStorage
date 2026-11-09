-- Approved game-chat binding for PVP casino handlers.
-- Run after add_casino_tables.sql.

CREATE TABLE IF NOT EXISTS casino_game_chat_bindings (
    id                        BIGSERIAL PRIMARY KEY,
    chat_id                   BIGINT NOT NULL UNIQUE CHECK (chat_id < 0),
    chat_type                 VARCHAR(16) NOT NULL CHECK (chat_type IN ('group', 'supergroup')),
    chat_title                VARCHAR(255),
    status                    VARCHAR(16) NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending', 'active', 'disabled')),
    requested_by_telegram_id  BIGINT NOT NULL CHECK (requested_by_telegram_id > 0),
    confirmed_by_admin_id     BIGINT,
    disabled_by_admin_id      BIGINT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at              TIMESTAMPTZ,
    disabled_at               TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_game_chat_bindings_one_active
    ON casino_game_chat_bindings ((status))
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_casino_game_chat_bindings_status
    ON casino_game_chat_bindings (status, updated_at DESC);

COMMENT ON TABLE casino_game_chat_bindings IS
    'Запрошенная ботом и подтверждённая администратором группа для PVP-игр казино';

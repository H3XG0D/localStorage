-- Website bell: join/session notices with a link into the live room.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_web_inbox (
    id BIGSERIAL PRIMARY KEY,
    recipient_id BIGINT NOT NULL CHECK (recipient_id <> 0),
    event_type VARCHAR(64) NOT NULL,
    game_id VARCHAR(80) NOT NULL,
    href TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recipient_id, event_type, game_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_web_inbox_recipient
    ON casino_web_inbox (recipient_id, created_at DESC);

COMMENT ON TABLE casino_web_inbox IS
    'In-app casino notices (Telegram join → site bell + go-to-game).';

COMMIT;

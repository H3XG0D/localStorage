-- Focus Agent: short redacted notes from the operator chat. Idempotent.

CREATE TABLE IF NOT EXISTS focus_agent_chats (
    chat_id       BIGINT PRIMARY KEY,
    title         TEXT,
    last_daily_at TIMESTAMPTZ,
    muted_until   TIMESTAMPTZ,
    last_chime_at TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE focus_agent_chats
    ADD COLUMN IF NOT EXISTS muted_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_chime_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS focus_agent_notes (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('line', 'summary')),
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_focus_agent_notes_chat
    ON focus_agent_notes (chat_id, id DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON focus_agent_chats TO exchange_bot;
        GRANT SELECT, INSERT, UPDATE, DELETE ON focus_agent_notes TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE focus_agent_notes_id_seq TO exchange_bot;
    END IF;
END $$;

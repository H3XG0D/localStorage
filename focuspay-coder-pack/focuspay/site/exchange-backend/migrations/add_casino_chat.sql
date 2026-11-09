-- Casino live chat: one lobby, pairwise DMs, presence. Additive.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_chat_rooms (
    id BIGSERIAL PRIMARY KEY,
    kind VARCHAR(8) NOT NULL CHECK (kind IN ('lobby', 'dm')),
    user_lo BIGINT,
    user_hi BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (kind = 'lobby' AND user_lo IS NULL AND user_hi IS NULL)
        OR (kind = 'dm' AND user_lo IS NOT NULL AND user_hi IS NOT NULL AND user_lo < user_hi)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_chat_lobby
    ON casino_chat_rooms (kind) WHERE kind = 'lobby';
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_chat_dm
    ON casino_chat_rooms (user_lo, user_hi) WHERE kind = 'dm';

CREATE TABLE IF NOT EXISTS casino_chat_messages (
    id BIGSERIAL PRIMARY KEY,
    room_id BIGINT NOT NULL REFERENCES casino_chat_rooms(id) ON DELETE RESTRICT,
    author_id BIGINT NOT NULL CHECK (author_id <> 0),
    kind VARCHAR(16) NOT NULL DEFAULT 'text' CHECK (kind IN ('text', 'challenge', 'system')),
    body TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_casino_chat_messages_room
    ON casino_chat_messages (room_id, id DESC);

CREATE TABLE IF NOT EXISTS casino_chat_presence (
    user_id BIGINT PRIMARY KEY CHECK (user_id <> 0),
    display_name TEXT NOT NULL DEFAULT '',
    last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO casino_chat_rooms (kind)
VALUES ('lobby')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE casino_chat_rooms IS 'Casino lobby (one row) and 1:1 DM rooms.';
COMMENT ON TABLE casino_chat_messages IS 'Lobby and DM messages; challenge cards live in payload.';
COMMENT ON TABLE casino_chat_presence IS 'Last-seen heartbeat for online list.';

COMMIT;

-- Кого @focuscleear_bot уже видел в чате: для /spam.
CREATE TABLE IF NOT EXISTS chat_call_members (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    username TEXT,
    first_name TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_call_scans (
    chat_id BIGINT PRIMARY KEY,
    scanned_at TIMESTAMPTZ NOT NULL,
    found INTEGER NOT NULL,
    chat_size INTEGER NOT NULL
);

GRANT ALL PRIVILEGES ON TABLE chat_call_members TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE chat_call_scans TO exchange_bot;

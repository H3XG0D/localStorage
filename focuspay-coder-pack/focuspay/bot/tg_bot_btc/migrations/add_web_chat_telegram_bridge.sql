-- Мост лички @focus_operator (Telegram Business) ↔ веб-чат /ops/chat

CREATE TABLE IF NOT EXISTS telegram_business_connections (
    id              SERIAL PRIMARY KEY,
    connection_id   TEXT NOT NULL UNIQUE,
    user_id         BIGINT NOT NULL,
    user_chat_id    BIGINT,
    is_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_telegram_business_connections_user
    ON telegram_business_connections (user_id);

ALTER TABLE web_chat_threads
    ADD COLUMN IF NOT EXISTS telegram_dm_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS business_connection_id TEXT,
    ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'web';

ALTER TABLE web_chat_threads
    DROP CONSTRAINT IF EXISTS web_chat_threads_source_check;

-- Если в таблице накопились устаревшие значения source (например, exchanger),
-- приводим их к допустимому формату, чтобы миграция проходила идемпотентно.
UPDATE web_chat_threads
SET source = 'web'
WHERE COALESCE(TRIM(source), '') NOT IN ('web', 'telegram', 'both');

ALTER TABLE web_chat_threads
    ADD CONSTRAINT web_chat_threads_source_check
    CHECK (source IN ('web', 'telegram', 'both'));

ALTER TABLE web_chat_messages
    ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_web_chat_messages_tg_msg
    ON web_chat_messages (telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_web_chat_threads_tg_dm
    ON web_chat_threads (telegram_dm_chat_id)
    WHERE telegram_dm_chat_id IS NOT NULL;

-- NOTIFY для SSE при новом сообщении от покупателя
CREATE OR REPLACE FUNCTION notify_web_chat_new_message() RETURNS trigger AS $$
BEGIN
    IF NEW.sender_role = 'buyer' THEN
        PERFORM pg_notify(
            'web_chat_new',
            json_build_object(
                'thread_id', NEW.thread_id,
                'message_id', NEW.id,
                'preview', left(NEW.body, 120)
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_web_chat_messages_notify ON web_chat_messages;

CREATE TRIGGER trg_web_chat_messages_notify
    AFTER INSERT ON web_chat_messages
    FOR EACH ROW
    EXECUTE PROCEDURE notify_web_chat_new_message();

GRANT ALL PRIVILEGES ON TABLE telegram_business_connections TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE telegram_business_connections_id_seq TO exchange_bot;

COMMENT ON TABLE telegram_business_connections IS 'Telegram Business: бот ↔ @focus_operator';
COMMENT ON COLUMN web_chat_threads.source IS 'web | telegram | both';
COMMENT ON COLUMN web_chat_threads.telegram_dm_chat_id IS 'Chat ID клиента в TG для ответов через Business API';

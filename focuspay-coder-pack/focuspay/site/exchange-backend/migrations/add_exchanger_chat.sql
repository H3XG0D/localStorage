-- Чат внештатник ↔ оператор (один диалог на партнёра).

ALTER TABLE web_chat_threads
    ADD COLUMN IF NOT EXISTS external_exchanger_id INT REFERENCES external_exchangers(id);

ALTER TABLE web_chat_threads
    DROP CONSTRAINT IF EXISTS web_chat_threads_source_check;

ALTER TABLE web_chat_threads
    ADD CONSTRAINT web_chat_threads_source_check
    CHECK (source IN ('web', 'telegram', 'both', 'exchanger'));

ALTER TABLE web_chat_messages
    DROP CONSTRAINT IF EXISTS web_chat_messages_sender_role_check;

ALTER TABLE web_chat_messages
    ADD CONSTRAINT web_chat_messages_sender_role_check
    CHECK (sender_role IN ('buyer', 'admin', 'exchanger'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_web_chat_threads_exchanger
    ON web_chat_threads (external_exchanger_id)
    WHERE external_exchanger_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_web_chat_threads_source_exchanger
    ON web_chat_threads (source, external_exchanger_id)
    WHERE source = 'exchanger';

CREATE OR REPLACE FUNCTION notify_web_chat_new_message() RETURNS trigger AS $$
BEGIN
    IF NEW.sender_role IN ('buyer', 'exchanger') THEN
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

COMMENT ON COLUMN web_chat_threads.external_exchanger_id IS 'Внештатник: один диалог на партнёра';

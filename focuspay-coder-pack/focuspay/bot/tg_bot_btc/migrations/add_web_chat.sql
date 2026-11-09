-- Чат поддержки на сайте (покупатель ↔ админ).
CREATE TABLE IF NOT EXISTS web_chat_threads (
    id                 BIGSERIAL PRIMARY KEY,
    session_token      UUID UNIQUE,
    telegram_user_id   BIGINT,
    order_id           VARCHAR(32),
    admin_unread       INT NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_chat_threads_telegram
    ON web_chat_threads (telegram_user_id)
    WHERE telegram_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_web_chat_threads_last_msg
    ON web_chat_threads (last_message_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS web_chat_messages (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       BIGINT NOT NULL REFERENCES web_chat_threads(id) ON DELETE CASCADE,
    sender_role     VARCHAR(10) NOT NULL CHECK (sender_role IN ('buyer', 'admin')),
    body            TEXT NOT NULL,
    admin_user_id   INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_by_admin   BOOLEAN NOT NULL DEFAULT FALSE,
    read_by_buyer   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_web_chat_messages_thread
    ON web_chat_messages (thread_id, id);

COMMENT ON TABLE web_chat_threads IS 'Диалоги чата с сайта';
COMMENT ON TABLE web_chat_messages IS 'Сообщения чата';

GRANT ALL PRIVILEGES ON TABLE web_chat_threads TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE web_chat_messages TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_chat_threads_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_chat_messages_id_seq TO exchange_bot;

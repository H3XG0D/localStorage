-- Комиссии со свапов из рабочего Telegram-чата (ручной ввод операторами).
CREATE TABLE IF NOT EXISTS swap_commission_entries (
    id                SERIAL PRIMARY KEY,
    chat_id           BIGINT NOT NULL,
    message_id        BIGINT NOT NULL,
    topic_id          BIGINT,
    telegram_user_id  BIGINT,
    raw_text          TEXT NOT NULL,
    crypto            VARCHAR(16) NOT NULL,
    crypto_amount     NUMERIC(20, 8) NOT NULL,
    rate_rub          NUMERIC(14, 2),
    amount_rub        NUMERIC(14, 2) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_swap_commission_created
    ON swap_commission_entries (created_at DESC);

COMMENT ON TABLE swap_commission_entries IS
    'Комиссии со свапов: сообщения из рабочего чата, сумма+валюта → ₽ по курсу на момент записи';

GRANT SELECT, INSERT, DELETE ON swap_commission_entries TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE swap_commission_entries_id_seq TO exchange_bot;

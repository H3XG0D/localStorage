CREATE TABLE IF NOT EXISTS site_reviews (
    id SERIAL PRIMARY KEY,
    telegram_message_id BIGINT NOT NULL,
    channel_username VARCHAR(64) NOT NULL DEFAULT 'focuspayr',
    text TEXT NOT NULL,
    author_name VARCHAR(255),
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel_username, telegram_message_id)
);

CREATE INDEX IF NOT EXISTS idx_site_reviews_published
    ON site_reviews (published_at DESC NULLS LAST);

COMMENT ON TABLE site_reviews IS 'Отзывы из Telegram-канала для отображения на сайте';

GRANT ALL PRIVILEGES ON TABLE site_reviews TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE site_reviews_id_seq TO exchange_bot;

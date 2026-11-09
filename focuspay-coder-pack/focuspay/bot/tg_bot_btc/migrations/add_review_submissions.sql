-- Очередь отзывов на модерацию (ops-группа) перед публикацией в канал.

CREATE TABLE IF NOT EXISTS review_submissions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    order_id VARCHAR(64),
    tier VARCHAR(16) NOT NULL DEFAULT 'text',
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    review_text TEXT NOT NULL,
    author_display VARCHAR(255),
    source_text_chat_id BIGINT NOT NULL,
    source_text_message_id BIGINT NOT NULL,
    source_photo_chat_id BIGINT,
    source_photo_message_id BIGINT,
    channel_text_message_id BIGINT,
    channel_photo_message_id BIGINT,
    bonus_rub NUMERIC(12, 2),
    bonus_credited BOOLEAN NOT NULL DEFAULT false,
    moderation_chat_id BIGINT,
    moderation_message_id BIGINT,
    moderated_by BIGINT,
    moderated_at TIMESTAMPTZ,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT review_submissions_tier_chk CHECK (tier IN ('text', 'photo')),
    CONSTRAINT review_submissions_status_chk CHECK (status IN ('pending', 'published', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_submissions_one_pending
    ON review_submissions (user_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_review_submissions_status_created
    ON review_submissions (status, created_at DESC);

COMMENT ON TABLE review_submissions IS 'Отзывы клиентов до модерации и публикации';

ALTER TABLE site_reviews
    ADD COLUMN IF NOT EXISTS submission_id INTEGER REFERENCES review_submissions(id),
    ADD COLUMN IF NOT EXISTS channel_photo_message_id BIGINT;

GRANT ALL PRIVILEGES ON TABLE review_submissions TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE review_submissions_id_seq TO exchange_bot;

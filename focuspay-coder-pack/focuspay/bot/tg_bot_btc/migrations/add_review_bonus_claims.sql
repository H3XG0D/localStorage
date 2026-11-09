CREATE TABLE IF NOT EXISTS review_bonus_claims (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount_rub NUMERIC(12, 2) NOT NULL,
    order_id VARCHAR(64),
    channel_message_id BIGINT,
    review_text TEXT NOT NULL,
    author_display VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_bonus_user_created
    ON review_bonus_claims (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_bonus_user_day
    ON review_bonus_claims (user_id, ((created_at AT TIME ZONE 'UTC')::date));

COMMENT ON TABLE review_bonus_claims IS 'Бонус за отзыв (не чаще 1 раза в календарные сутки на user_id)';

GRANT ALL PRIVILEGES ON TABLE review_bonus_claims TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE review_bonus_claims_id_seq TO exchange_bot;

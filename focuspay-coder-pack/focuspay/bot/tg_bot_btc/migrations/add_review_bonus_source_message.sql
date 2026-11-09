ALTER TABLE review_bonus_claims
    ADD COLUMN IF NOT EXISTS source_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS source_message_id BIGINT;

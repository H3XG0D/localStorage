-- Фразы антиспама, которые операторы задают в /ops.
CREATE TABLE IF NOT EXISTS group_spam_phrases (
    id SERIAL PRIMARY KEY,
    phrase TEXT NOT NULL,
    normalized TEXT NOT NULL,
    created_by_operator_id INT NULL REFERENCES operator_accounts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT group_spam_phrases_normalized_key UNIQUE (normalized)
);

CREATE INDEX IF NOT EXISTS idx_group_spam_phrases_created_at
    ON group_spam_phrases (created_at DESC);

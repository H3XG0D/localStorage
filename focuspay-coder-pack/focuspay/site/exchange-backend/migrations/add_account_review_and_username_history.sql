-- Mirror of tg_bot_btc/migrations/add_account_review_and_username_history.sql
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS previous_username TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS username_changed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_review_status TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS account_review_reason TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_reviewed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_reviewed_by BIGINT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_bot_users_account_review_pending
    ON bot_users(account_review_status)
    WHERE account_review_status = 'pending';

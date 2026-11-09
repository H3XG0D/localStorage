-- История username + ручная проверка подозрительных аккаунтов до выдачи реквизитов.
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS previous_username TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS username_changed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_review_status TEXT NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS account_review_reason TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_reviewed_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS account_reviewed_by BIGINT DEFAULT NULL;

COMMENT ON COLUMN bot_users.previous_username IS 'Предыдущий Telegram username (для детекта смены ника)';
COMMENT ON COLUMN bot_users.username_changed_at IS 'Когда username сменился относительно previous_username';
COMMENT ON COLUMN bot_users.account_review_status IS 'none|pending|approved|rejected — ручная проверка до payin';

CREATE INDEX IF NOT EXISTS idx_bot_users_account_review_pending
    ON bot_users(account_review_status)
    WHERE account_review_status = 'pending';

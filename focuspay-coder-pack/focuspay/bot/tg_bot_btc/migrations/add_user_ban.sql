-- Бан клиентов оператором: заблокированный клиент не может создавать новые заявки.
-- ban_type: 'hard' — показывает «аккаунт заблокирован»,
--           'soft' — показывает «нет реквизитов» (тихий блок, без раскрытия причины).
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS is_banned       BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ban_type        TEXT        NOT NULL DEFAULT 'hard',
    ADD COLUMN IF NOT EXISTS ban_reason      TEXT        DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS banned_at       TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS banned_by_op_id BIGINT      DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_bot_users_is_banned ON bot_users(is_banned) WHERE is_banned = TRUE;

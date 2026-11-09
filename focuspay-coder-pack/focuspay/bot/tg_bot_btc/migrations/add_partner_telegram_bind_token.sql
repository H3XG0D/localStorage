-- Одноразовый токен привязки Telegram к партнёрскому аккаунту (без пароля в чате)
ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS telegram_bind_token VARCHAR(64);

ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS telegram_bind_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_partner_accounts_bind_token
    ON partner_accounts (telegram_bind_token)
    WHERE telegram_bind_token IS NOT NULL;

COMMENT ON COLUMN partner_accounts.telegram_bind_token IS 'Одноразовый код для /partner_bind в боте';
COMMENT ON COLUMN partner_accounts.telegram_bind_expires_at IS 'Срок действия bind-токена';

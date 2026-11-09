-- Регистрация на сайте по username+паролю + 2FA операторов
CREATE SEQUENCE IF NOT EXISTS web_client_user_id_seq;

ALTER TABLE web_users
    ADD COLUMN IF NOT EXISTS client_user_id BIGINT UNIQUE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_web_users_client_user_id
    ON web_users (client_user_id)
    WHERE client_user_id IS NOT NULL;

COMMENT ON COLUMN web_users.client_user_id IS
    'Synthetic negative user_id для password-аккаунтов без Telegram';

ALTER TABLE operator_accounts
    ADD COLUMN IF NOT EXISTS totp_secret TEXT,
    ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN operator_accounts.totp_secret IS 'TOTP secret for operator 2FA';
COMMENT ON COLUMN operator_accounts.totp_enabled IS 'Whether operator 2FA is active';

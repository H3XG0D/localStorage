-- Login by username (no email) for admins and partner cabinet
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_login_username.sql

-- web_users (admin panel)
ALTER TABLE web_users ADD COLUMN IF NOT EXISTS username VARCHAR(64);

UPDATE web_users
SET username = LOWER(SPLIT_PART(email, '@', 1))
WHERE username IS NULL AND email IS NOT NULL AND email LIKE '%@%';

UPDATE web_users
SET username = LOWER(email)
WHERE username IS NULL AND email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_web_users_username_lower
    ON web_users (LOWER(username)) WHERE username IS NOT NULL;

COMMENT ON COLUMN web_users.username IS 'Логин для админ-панели (без @)';

-- partner_accounts: username instead of email
ALTER TABLE partner_accounts ADD COLUMN IF NOT EXISTS username VARCHAR(64);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'partner_accounts' AND column_name = 'email'
    ) THEN
        UPDATE partner_accounts
        SET username = LOWER(REGEXP_REPLACE(email, '@.*$', ''))
        WHERE username IS NULL AND email IS NOT NULL;

        ALTER TABLE partner_accounts DROP CONSTRAINT IF EXISTS partner_accounts_email_key;
        ALTER TABLE partner_accounts DROP COLUMN email;
    END IF;
END $$;

UPDATE partner_accounts
SET username = 'partner_' || id::text
WHERE username IS NULL;

ALTER TABLE partner_accounts ALTER COLUMN username SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_accounts_username_lower
    ON partner_accounts (LOWER(username));

COMMENT ON COLUMN partner_accounts.username IS 'Логин кабинета партнёра (как Telegram @username)';

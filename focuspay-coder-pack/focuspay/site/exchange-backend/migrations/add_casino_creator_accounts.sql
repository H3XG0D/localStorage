-- Replace the singleton Telegram-based casino creator with auditable web accounts.
-- Safe to run after migrations/add_casino_tables.sql and migrations/add_web_users.sql.
-- This migration is intentionally not applied automatically.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_creator_accounts (
    id            BIGSERIAL PRIMARY KEY,
    web_user_id   INTEGER NOT NULL REFERENCES web_users(id) ON DELETE RESTRICT,
    ref_token     VARCHAR(32) NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    assigned_by   INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_by    INTEGER REFERENCES web_users(id) ON DELETE SET NULL,
    revoked_at    TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_accounts_active_web_user
    ON casino_creator_accounts (web_user_id)
    WHERE is_active;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_accounts_one_active
    ON casino_creator_accounts ((is_active))
    WHERE is_active;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_accounts_ref_token
    ON casino_creator_accounts (ref_token);
CREATE INDEX IF NOT EXISTS idx_casino_creator_accounts_active
    ON casino_creator_accounts (is_active, assigned_at DESC);

ALTER TABLE casino_commission_ledger
    ADD COLUMN IF NOT EXISTS creator_account_id BIGINT
    REFERENCES casino_creator_accounts(id) ON DELETE RESTRICT;
ALTER TABLE casino_creator_balance
    ADD COLUMN IF NOT EXISTS creator_account_id BIGINT
    REFERENCES casino_creator_accounts(id) ON DELETE RESTRICT;
ALTER TABLE casino_creator_withdrawals
    ADD COLUMN IF NOT EXISTS creator_account_id BIGINT
    REFERENCES casino_creator_accounts(id) ON DELETE RESTRICT;

-- New creator accounts may belong to password-only web users. Preserve legacy
-- Telegram rows, but make their former key optional for account-based rows.
ALTER TABLE casino_creator_balance
    DROP CONSTRAINT IF EXISTS casino_creator_balance_pkey;
ALTER TABLE casino_creator_balance
    ALTER COLUMN telegram_id DROP NOT NULL;
ALTER TABLE casino_creator_withdrawals
    ALTER COLUMN telegram_id DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_balance_telegram
    ON casino_creator_balance (telegram_id)
    WHERE telegram_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_balance_account
    ON casino_creator_balance (creator_account_id)
    WHERE creator_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_casino_commission_creator_account
    ON casino_commission_ledger (creator_account_id, status, created_at DESC)
    WHERE creator_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_casino_creator_withdrawals_account
    ON casino_creator_withdrawals (creator_account_id, created_at DESC)
    WHERE creator_account_id IS NOT NULL;

-- Best effort only: a legacy setting may point to a Telegram user without a
-- corresponding web_users record. Leave it untouched when no web account is linked.
WITH legacy_creator AS (
    SELECT (value ->> 'telegram_id')::BIGINT AS telegram_user_id
    FROM casino_settings
    WHERE key = 'creator_telegram_id'
      AND value ? 'telegram_id'
      AND (value ->> 'telegram_id') ~ '^[1-9][0-9]*$'
), linked_web_user AS (
    SELECT wu.id AS web_user_id, legacy_creator.telegram_user_id
    FROM legacy_creator
    JOIN web_users wu ON wu.telegram_user_id = legacy_creator.telegram_user_id
), created_account AS (
    INSERT INTO casino_creator_accounts (web_user_id, ref_token)
    SELECT web_user_id,
           lower(substring(md5(random()::text || web_user_id::text || clock_timestamp()::text) FROM 1 FOR 18))
    FROM linked_web_user
    ON CONFLICT (web_user_id) WHERE is_active DO NOTHING
    RETURNING id, web_user_id
), active_account AS (
    SELECT id, web_user_id FROM created_account
    UNION ALL
    SELECT cca.id, cca.web_user_id
    FROM casino_creator_accounts cca
    JOIN linked_web_user lwu ON lwu.web_user_id = cca.web_user_id
    WHERE cca.is_active
)
UPDATE casino_commission_ledger ledger
SET creator_account_id = active_account.id
FROM active_account
WHERE ledger.recipient_type = 'creator'
  AND ledger.creator_account_id IS NULL
  AND ledger.recipient_id = (
      SELECT telegram_user_id
      FROM web_users
      WHERE id = active_account.web_user_id
  );

WITH legacy_creator AS (
    SELECT (value ->> 'telegram_id')::BIGINT AS telegram_user_id
    FROM casino_settings
    WHERE key = 'creator_telegram_id'
      AND value ? 'telegram_id'
      AND (value ->> 'telegram_id') ~ '^[1-9][0-9]*$'
), active_account AS (
    SELECT cca.id, wu.telegram_user_id
    FROM casino_creator_accounts cca
    JOIN web_users wu ON wu.id = cca.web_user_id
    JOIN legacy_creator lc ON lc.telegram_user_id = wu.telegram_user_id
    WHERE cca.is_active
)
UPDATE casino_creator_balance balance
SET creator_account_id = active_account.id
FROM active_account
WHERE balance.creator_account_id IS NULL
  AND balance.telegram_id = active_account.telegram_user_id;

WITH legacy_creator AS (
    SELECT (value ->> 'telegram_id')::BIGINT AS telegram_user_id
    FROM casino_settings
    WHERE key = 'creator_telegram_id'
      AND value ? 'telegram_id'
      AND (value ->> 'telegram_id') ~ '^[1-9][0-9]*$'
), active_account AS (
    SELECT cca.id, wu.telegram_user_id
    FROM casino_creator_accounts cca
    JOIN web_users wu ON wu.id = cca.web_user_id
    JOIN legacy_creator lc ON lc.telegram_user_id = wu.telegram_user_id
    WHERE cca.is_active
)
UPDATE casino_creator_withdrawals withdrawal
SET creator_account_id = active_account.id
FROM active_account
WHERE withdrawal.creator_account_id IS NULL
  AND withdrawal.telegram_id = active_account.telegram_user_id;

COMMIT;

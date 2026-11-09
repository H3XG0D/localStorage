-- Make creator withdrawal requests retry-safe without double-reserving balance.
-- Apply after add_casino_tables.sql and add_casino_creator_accounts.sql.

BEGIN;

ALTER TABLE casino_creator_withdrawals
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_creator_withdrawals_account_idempotency
    ON casino_creator_withdrawals (creator_account_id, idempotency_key)
    WHERE creator_account_id IS NOT NULL AND idempotency_key IS NOT NULL;

COMMIT;

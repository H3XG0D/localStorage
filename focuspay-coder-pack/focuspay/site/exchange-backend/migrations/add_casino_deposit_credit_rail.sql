-- Fiat casino deposits must leave via card before crypto withdraw unlocks.
-- Existing credits are legacy: they do not create a card-out obligation.
-- Run after add_casino_deposit_credits.sql.

BEGIN;

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS sub_token VARCHAR(16);

ALTER TABLE casino_deposit_credits
    ADD COLUMN IF NOT EXISTS rail VARCHAR(16);

UPDATE casino_deposit_credits
   SET rail = 'legacy'
 WHERE rail IS NULL;

ALTER TABLE casino_deposit_credits
    ALTER COLUMN rail SET DEFAULT 'fiat';

ALTER TABLE casino_deposit_credits
    ALTER COLUMN rail SET NOT NULL;

ALTER TABLE casino_deposit_credits
    DROP CONSTRAINT IF EXISTS casino_deposit_credits_rail_check;

ALTER TABLE casino_deposit_credits
    ADD CONSTRAINT casino_deposit_credits_rail_check
    CHECK (rail IN ('fiat', 'crypto', 'legacy'));

CREATE INDEX IF NOT EXISTS idx_casino_deposit_credits_telegram_fiat
    ON casino_deposit_credits (telegram_id, credited_at)
    WHERE rail = 'fiat';

COMMENT ON COLUMN casino_deposit_credits.rail IS
    'Pay-in rail: fiat (card/SBP) creates a card-out obligation; crypto does not; legacy is pre-rule history and does not create debt';

COMMIT;

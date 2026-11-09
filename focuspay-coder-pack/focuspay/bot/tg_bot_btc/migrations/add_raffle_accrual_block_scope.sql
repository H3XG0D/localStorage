-- FocusLucky: block scope — all tickets or referral-only (for partners)
ALTER TABLE raffle_accrual_blocks
    ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'all';

ALTER TABLE raffle_accrual_blocks
    DROP CONSTRAINT IF EXISTS raffle_accrual_blocks_scope_chk;

ALTER TABLE raffle_accrual_blocks
    ADD CONSTRAINT raffle_accrual_blocks_scope_chk
    CHECK (scope IN ('all', 'referral'));

COMMENT ON COLUMN raffle_accrual_blocks.scope IS
    'all = no new tickets; referral = only referral tickets blocked';

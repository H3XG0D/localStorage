-- Allow the shared user balance to be reserved/spent from referral accruals.
ALTER TABLE user_referral_ledger
    DROP CONSTRAINT IF EXISTS user_referral_ledger_type_check;

ALTER TABLE user_referral_ledger
    ADD CONSTRAINT user_referral_ledger_type_check
    CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend'));

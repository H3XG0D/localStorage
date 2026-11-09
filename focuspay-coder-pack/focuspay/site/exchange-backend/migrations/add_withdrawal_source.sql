-- Tag unified-balance withdrawals: cabinet/bot = balance, FocusBet cashier = casino.

ALTER TABLE user_referral_withdrawals
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'balance';

UPDATE user_referral_withdrawals
SET source = 'balance'
WHERE source IS NULL OR source = '';

ALTER TABLE user_referral_withdrawals DROP CONSTRAINT IF EXISTS user_referral_withdrawals_source_chk;
ALTER TABLE user_referral_withdrawals
    ADD CONSTRAINT user_referral_withdrawals_source_chk
    CHECK (source IN ('balance', 'casino'));

CREATE INDEX IF NOT EXISTS idx_user_referral_withdrawals_source_status
    ON user_referral_withdrawals (source, status, created_at DESC);

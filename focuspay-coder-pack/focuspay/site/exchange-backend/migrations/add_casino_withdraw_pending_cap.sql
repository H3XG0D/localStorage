-- FocusBet: up to 5 pending casino withdrawals per player.
-- Cabinet/referral still one pending (source = balance).

DROP INDEX IF EXISTS idx_user_referral_wd_one_pending;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_referral_wd_one_pending_balance
    ON user_referral_withdrawals (referrer_user_id)
    WHERE status = 'pending' AND COALESCE(source, 'balance') = 'balance';

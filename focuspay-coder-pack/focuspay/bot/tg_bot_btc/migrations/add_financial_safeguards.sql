-- Финансовые ограничения: hold кешбэка, pending remainder, один pending-вывод

ALTER TABLE user_cashback_ledger DROP CONSTRAINT IF EXISTS user_cashback_ledger_type_check;
ALTER TABLE user_cashback_ledger ADD CONSTRAINT user_cashback_ledger_type_check
    CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit', 'hold'));

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS pending_remainder_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_referral_wd_one_pending
    ON user_referral_withdrawals (referrer_user_id)
    WHERE status = 'pending';

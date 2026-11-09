-- Оператор, взявший заявку на вывод баланса
ALTER TABLE user_referral_withdrawals
    ADD COLUMN IF NOT EXISTS operator_id INT REFERENCES operator_accounts(id);

CREATE INDEX IF NOT EXISTS idx_user_referral_wd_operator_pending
    ON user_referral_withdrawals (operator_id, status)
    WHERE status = 'pending';

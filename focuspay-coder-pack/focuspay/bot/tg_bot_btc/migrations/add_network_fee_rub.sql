-- Комиссия сети: вывод баланса (клиент) и обмен BUY (расход P&L).

ALTER TABLE user_referral_withdrawals
    ADD COLUMN IF NOT EXISTS network_fee_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payout_amount_rub NUMERIC(14, 2);

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS network_fee_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN user_referral_withdrawals.network_fee_rub IS
    'Комиссия сети при crypto-выводе (удерживается с клиента)';
COMMENT ON COLUMN user_referral_withdrawals.payout_amount_rub IS
    'Сумма к отправке оператором в крипте (amount_rub - network_fee_rub)';
COMMENT ON COLUMN orders.network_fee_rub IS
    'Расход на комиссию сети при BUY-выплате (учёт P&L)';

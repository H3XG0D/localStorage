-- Hash транзакции при выплате вывода баланса (крипта)
ALTER TABLE user_referral_withdrawals
    ADD COLUMN IF NOT EXISTS payout_tx_hash TEXT;

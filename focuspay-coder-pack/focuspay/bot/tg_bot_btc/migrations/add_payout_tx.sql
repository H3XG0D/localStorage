-- Подтверждение выплаты крипты оператором (BUY после COMPLETED)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payout_tx_hash TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payout_confirmed_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payout_confirmed_by VARCHAR(64);

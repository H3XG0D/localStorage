-- Apply the same withdrawal fee accounting to partner-only withdrawals.
ALTER TABLE partner_withdrawals
    ADD COLUMN IF NOT EXISTS network_fee_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payout_amount_rub NUMERIC(14, 2);

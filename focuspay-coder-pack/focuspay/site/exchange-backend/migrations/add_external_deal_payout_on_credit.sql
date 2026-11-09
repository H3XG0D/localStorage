-- Intent: after the deal is credited, auto-create a crypto payout request.
ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS payout_on_credit BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS payout_wallet TEXT,
    ADD COLUMN IF NOT EXISTS payout_id INT REFERENCES external_payouts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_external_deals_payout_id
    ON external_deals (payout_id)
    WHERE payout_id IS NOT NULL;

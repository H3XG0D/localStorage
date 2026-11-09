-- Partner withdrawal requests (crypto / card)
ALTER TABLE partner_ledger
    ADD COLUMN IF NOT EXISTS withdrawal_id INT;

CREATE TABLE IF NOT EXISTS partner_withdrawals (
    id                       SERIAL PRIMARY KEY,
    campaign_id              INT NOT NULL REFERENCES promo_campaigns(id) ON DELETE CASCADE,
    partner_account_id       INT NOT NULL REFERENCES partner_accounts(id) ON DELETE CASCADE,
    amount_rub               NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    method                   VARCHAR(10) NOT NULL CHECK (method IN ('card', 'crypto')),
    requisites               TEXT NOT NULL,
    crypto                   VARCHAR(20),
    network                  VARCHAR(20),
    status                   VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'rejected', 'canceled')),
    payout_tx_hash           TEXT,
    admin_message_id         BIGINT,
    processed_by_web_user_id INT REFERENCES web_users(id) ON DELETE SET NULL,
    reject_reason            TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at             TIMESTAMPTZ
);

ALTER TABLE partner_withdrawals
    ADD COLUMN IF NOT EXISTS network_fee_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payout_amount_rub NUMERIC(14, 2);

CREATE INDEX IF NOT EXISTS idx_partner_wd_campaign
    ON partner_withdrawals (campaign_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_wd_one_pending
    ON partner_withdrawals (campaign_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_partner_wd_pending
    ON partner_withdrawals (status)
    WHERE status = 'pending';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'partner_ledger_withdrawal_id_fkey'
    ) THEN
        ALTER TABLE partner_ledger
            ADD CONSTRAINT partner_ledger_withdrawal_id_fkey
            FOREIGN KEY (withdrawal_id) REFERENCES partner_withdrawals(id) ON DELETE SET NULL;
    END IF;
END $$;

COMMENT ON TABLE partner_withdrawals IS 'Заявки партнёров на вывод баланса (крипта / карта)';

-- Partner referral: commission ledger + partner login
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_partner_referral.sql

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS partner_commission_percent NUMERIC(5, 2) NOT NULL DEFAULT 10
        CHECK (partner_commission_percent >= 0 AND partner_commission_percent <= 100);

COMMENT ON COLUMN promo_campaigns.partner_commission_percent IS
    'Процент от прибыли сервиса по PAID-сделкам приведённых клиентов, начисляется партнёру';

CREATE TABLE IF NOT EXISTS partner_accounts (
    id                SERIAL PRIMARY KEY,
    promo_campaign_id INT NOT NULL UNIQUE REFERENCES promo_campaigns(id) ON DELETE CASCADE,
    username          VARCHAR(64) NOT NULL UNIQUE,
    password_hash     VARCHAR(255) NOT NULL,
    display_name      VARCHAR(255),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_partner_accounts_campaign ON partner_accounts (promo_campaign_id);

CREATE TABLE IF NOT EXISTS partner_ledger (
    id                    SERIAL PRIMARY KEY,
    campaign_id           INT NOT NULL REFERENCES promo_campaigns(id) ON DELETE CASCADE,
    type                  VARCHAR(20) NOT NULL CHECK (type IN ('accrual', 'payout', 'adjustment')),
    amount_rub            NUMERIC(14, 2) NOT NULL,
    order_id              VARCHAR(64) UNIQUE,
    note                  TEXT,
    created_by_web_user_id INT REFERENCES web_users(id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_partner_ledger_campaign ON partner_ledger (campaign_id, created_at DESC);

COMMENT ON TABLE partner_accounts IS 'Логин партнёра для кабинета /partner (одна учётка на promo_campaign)';
COMMENT ON TABLE partner_ledger IS 'Начисления и выплаты партнёру; баланс = SUM(amount_rub)';

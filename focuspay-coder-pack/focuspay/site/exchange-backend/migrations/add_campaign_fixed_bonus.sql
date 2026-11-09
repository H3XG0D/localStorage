-- Same as tg_bot_btc/migrations/add_campaign_fixed_bonus.sql
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS client_fixed_bonus_rub NUMERIC(14, 2) DEFAULT NULL
        CHECK (client_fixed_bonus_rub IS NULL OR client_fixed_bonus_rub > 0);

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS campaign_kind VARCHAR(16) NOT NULL DEFAULT 'generic';

ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT UNIQUE;

ALTER TABLE promo_bonus_usages
    ADD COLUMN IF NOT EXISTS bonus_fixed_rub NUMERIC(14, 2) DEFAULT NULL;

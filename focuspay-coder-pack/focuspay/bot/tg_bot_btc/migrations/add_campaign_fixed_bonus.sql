-- Фиксированный бонус клиенту (₽) и тип кампании
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS client_fixed_bonus_rub NUMERIC(14, 2) DEFAULT NULL
        CHECK (client_fixed_bonus_rub IS NULL OR client_fixed_bonus_rub > 0);

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS campaign_kind VARCHAR(16) NOT NULL DEFAULT 'generic';

COMMENT ON COLUMN promo_campaigns.client_fixed_bonus_rub IS
    'Одноразовый бонус клиенту в рублях (вместо bonus_percent)';
COMMENT ON COLUMN promo_campaigns.campaign_kind IS
    'partner | fixed_rub | generic';

ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT UNIQUE;

COMMENT ON COLUMN partner_accounts.telegram_user_id IS
    'Telegram user_id для кабинета партнёра в боте';

-- promo_bonus_usages: фиксированная сумма вместо процента
ALTER TABLE promo_bonus_usages
    ADD COLUMN IF NOT EXISTS bonus_fixed_rub NUMERIC(14, 2) DEFAULT NULL;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO exchange_bot;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;

-- Mirror: tg_bot_btc/migrations/add_partner_tier_settings.sql

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS partner_tier_base_percent NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS partner_tier_step_percent NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS partner_tier_every_n INT,
    ADD COLUMN IF NOT EXISTS partner_tier_max_percent NUMERIC(5, 2);

UPDATE app_settings
SET value = value || '{
    "partner_tier_base_percent": 5,
    "partner_tier_step_percent": 5,
    "partner_tier_every_n": 5,
    "partner_tier_max_percent": 20
}'::jsonb,
    updated_at = now()
WHERE key = 'business'
  AND NOT (value ? 'partner_tier_base_percent');

-- Partner tier: global defaults in app_settings + optional per-campaign override

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS partner_tier_base_percent NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS partner_tier_step_percent NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS partner_tier_every_n INT,
    ADD COLUMN IF NOT EXISTS partner_tier_max_percent NUMERIC(5, 2);

COMMENT ON COLUMN promo_campaigns.partner_tier_base_percent IS
    'Override base % for tier; NULL = global default from app_settings';

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

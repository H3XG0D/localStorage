-- Opaque ref token for share links: /ref/<token> and t.me/bot?start=ref_<token>
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS ref_token VARCHAR(32);

UPDATE promo_campaigns
SET ref_token = LOWER(SUBSTRING(MD5(random()::text || id::text || clock_timestamp()::text) FROM 1 FOR 18))
WHERE ref_token IS NULL;

ALTER TABLE promo_campaigns ALTER COLUMN ref_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_campaigns_ref_token
    ON promo_campaigns (ref_token);

COMMENT ON COLUMN promo_campaigns.ref_token IS
    'Секретный токен реф-ссылки; code остаётся для внутренней отчётности';

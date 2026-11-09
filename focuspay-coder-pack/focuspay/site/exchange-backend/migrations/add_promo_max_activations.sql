-- Mirror: tg_bot_btc/migrations/add_promo_max_activations.sql
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS max_activations INT NOT NULL DEFAULT 5
    CHECK (max_activations >= 1 AND max_activations <= 1000);

ALTER TABLE promo_gift_redemptions DROP CONSTRAINT IF EXISTS promo_gift_redemptions_pkey;

ALTER TABLE promo_gift_redemptions ADD COLUMN IF NOT EXISTS id SERIAL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'promo_gift_redemptions'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE promo_gift_redemptions ADD PRIMARY KEY (id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_gift_redemptions_code_user
    ON promo_gift_redemptions (promo_code, user_id);

CREATE INDEX IF NOT EXISTS idx_promo_gift_redemptions_code
    ON promo_gift_redemptions (promo_code);

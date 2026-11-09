-- Лимит активаций промокода + несколько использований gift-кода
-- psql -U exchange_bot -d exchange_bot -f migrations/add_promo_max_activations.sql

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS max_activations INT NOT NULL DEFAULT 5
    CHECK (max_activations >= 1 AND max_activations <= 1000);

COMMENT ON COLUMN promo_campaigns.max_activations IS
    'Макс. число активаций: gift — promo_gift_redemptions; referral — promo_attributions';

-- Разрешить несколько активаций одного gift-кода (раньше promo_code был PK)
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

COMMENT ON TABLE promo_gift_redemptions IS
    'Активации подарочных промокодов (fixed_rub): до max_activations на код, один раз на user';

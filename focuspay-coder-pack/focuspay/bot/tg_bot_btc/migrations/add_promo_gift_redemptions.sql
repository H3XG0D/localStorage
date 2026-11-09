-- Подарочные промокоды (раздача, рулетки): одноразовая активация по коду → баланс
-- psql -U exchange_bot -d exchange_bot -f migrations/add_promo_gift_redemptions.sql

CREATE TABLE IF NOT EXISTS promo_gift_redemptions (
    promo_code  VARCHAR(32) PRIMARY KEY REFERENCES promo_campaigns(code) ON DELETE RESTRICT,
    user_id     BIGINT NOT NULL,
    amount_rub  NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promo_gift_redemptions_user
    ON promo_gift_redemptions (user_id);

COMMENT ON TABLE promo_gift_redemptions IS 'Активация подарочных промокодов (fixed_rub): один код — один пользователь';

GRANT ALL PRIVILEGES ON TABLE promo_gift_redemptions TO exchange_bot;

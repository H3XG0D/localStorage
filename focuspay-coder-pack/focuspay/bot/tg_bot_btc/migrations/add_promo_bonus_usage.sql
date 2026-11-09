-- Промо-бонус на первую заявку: учёт использования + метаданные в orders
-- psql -U exchange_bot -d exchange_bot -f migrations/add_promo_bonus_usage.sql

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS promo_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS promo_bonus_percent NUMERIC(5, 2);

CREATE TABLE IF NOT EXISTS promo_bonus_usages (
    user_id       BIGINT PRIMARY KEY,
    order_id      VARCHAR NOT NULL,
    promo_code    VARCHAR(32) NOT NULL REFERENCES promo_campaigns(code) ON DELETE RESTRICT,
    bonus_percent NUMERIC(5, 2) NOT NULL,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promo_bonus_usages_order
    ON promo_bonus_usages (order_id);

COMMENT ON TABLE promo_bonus_usages IS 'Одноразовый промо-бонус пользователя (первая заявка после deep-link)';
COMMENT ON COLUMN orders.promo_code IS 'Промо-код, если к заявке применён бонус';
COMMENT ON COLUMN orders.promo_bonus_percent IS 'Процент промо-бонуса, применённый к выплате клиенту';

GRANT ALL PRIVILEGES ON TABLE promo_bonus_usages TO exchange_bot;

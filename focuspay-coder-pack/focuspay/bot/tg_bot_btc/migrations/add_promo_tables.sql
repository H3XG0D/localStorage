-- Промо-кампании и атрибуция пользователей к промо-кодам.
-- Запуск: psql -U exchange_bot -d exchange_bot -f migrations/add_promo_tables.sql

CREATE TABLE IF NOT EXISTS promo_campaigns (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    bonus_percent NUMERIC(5,2) NOT NULL CHECK (bonus_percent >= 0 AND bonus_percent <= 100),
    ad_spend_rub NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (ad_spend_rub >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promo_campaigns_active_created
    ON promo_campaigns (is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS promo_attributions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE,
    promo_code VARCHAR(32) NOT NULL REFERENCES promo_campaigns(code) ON DELETE RESTRICT,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_promo_attributions_code
    ON promo_attributions (promo_code);

COMMENT ON TABLE promo_campaigns IS 'Промо-кампании/реферальные ссылки для рекламы';
COMMENT ON TABLE promo_attributions IS 'Первичная привязка пользователя к promo-коду по deep-link /start';

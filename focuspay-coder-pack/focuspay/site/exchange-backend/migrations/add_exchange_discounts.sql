-- Exchange discount vouchers: promo code → personal voucher → reduced BUY payin

CREATE TABLE IF NOT EXISTS user_exchange_discounts (
    id           SERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL,
    promo_code   VARCHAR(64) NOT NULL,
    amount_rub   NUMERIC(12, 2) NOT NULL CHECK (amount_rub > 0),
    status       VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'held', 'used', 'released')),
    order_id     VARCHAR(64),
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_exchange_discounts_user_active
    ON user_exchange_discounts (user_id, status)
    WHERE status IN ('active', 'held');

CREATE INDEX IF NOT EXISTS idx_user_exchange_discounts_order
    ON user_exchange_discounts (order_id)
    WHERE order_id IS NOT NULL;

COMMENT ON TABLE user_exchange_discounts IS
    'Ваучеры «скидка на обмен» после активации промокода exchange_discount';

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS exchange_discount_applied_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS exchange_discount_id INT REFERENCES user_exchange_discounts(id);

COMMENT ON COLUMN orders.exchange_discount_applied_rub IS
    'Скидка на обмен (₽), уменьшившая сумму к оплате';

GRANT SELECT, INSERT, UPDATE, DELETE ON user_exchange_discounts TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE user_exchange_discounts_id_seq TO exchange_bot;

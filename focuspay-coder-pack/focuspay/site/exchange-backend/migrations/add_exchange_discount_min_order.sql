-- Минимальная сумма заказа для применения скидки на обмен.
-- Пример: скидка 500 ₽ применяется только при заказе от 3000 ₽.
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS exchange_discount_min_order_rub NUMERIC(12, 2) NOT NULL DEFAULT 0;

ALTER TABLE user_exchange_discounts
    ADD COLUMN IF NOT EXISTS min_order_rub NUMERIC(12, 2) NOT NULL DEFAULT 0;

COMMENT ON COLUMN promo_campaigns.exchange_discount_min_order_rub IS
    'Минимальная сумма заказа (₽) для применения скидки на обмен';
COMMENT ON COLUMN user_exchange_discounts.min_order_rub IS
    'Минимальная сумма заказа (₽), при которой ваучер применяется';

-- Снимок реквизитов мерчанта (bill, pay_link) для отображения на сайте после перезагрузки.
ALTER TABLE orders
ADD COLUMN IF NOT EXISTS payment_snapshot JSONB;

COMMENT ON COLUMN orders.payment_snapshot IS 'bill/pay_link из ответа create_order_payin для веб-заявок';

GRANT ALL PRIVILEGES ON TABLE orders TO exchange_bot;

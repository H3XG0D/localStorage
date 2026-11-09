-- Способ оплаты для BUY: CARDRUB / SBPRUB. Выполнить один раз:
-- psql -U exchange_bot -d exchange_bot -f migrations/add_sub_token.sql

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS sub_token VARCHAR(20);

COMMENT ON COLUMN orders.sub_token IS 'CARDRUB или SBPRUB — способ оплаты, выбранный клиентом при создании payin';

-- Добавить колонку merchant_order_id для отмены заявок через API мерча (/cancel_order_payin).
-- Выполнить один раз: psql -U exchange_bot -d exchange_bot -f migrations/add_merchant_order_id.sql

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS merchant_order_id TEXT;

COMMENT ON COLUMN orders.merchant_order_id IS 'uuid_system из ответа мерча при создании payin; нужен для отмены';

-- Причина отмены заявки оператором (доходит до покупателя).
-- Mirror: tg_bot_btc/migrations/add_order_cancel_reason.sql
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS cancel_reason TEXT;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS canceled_by BIGINT;

COMMENT ON COLUMN orders.cancel_reason IS
    'Причина отмены заявки (вводит оператор), отправляется покупателю';
COMMENT ON COLUMN orders.canceled_by IS
    'Кто отменил заявку: id оператора (operator_accounts.id) или NULL';

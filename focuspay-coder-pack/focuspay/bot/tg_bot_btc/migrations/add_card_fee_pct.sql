-- Добавить колонку card_fee_pct для хранения комиссии провайдера карт.
-- Авто-бот: 0.12 (12%), ручные заявки: 0.14 (14%).
-- Чистая прибыль = fiat × (spread 20% − card_fee_pct).

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS card_fee_pct NUMERIC(5, 4) DEFAULT NULL;

COMMENT ON COLUMN orders.card_fee_pct IS
  'Комиссия провайдера карт: 0.12 (авто-бот), 0.14 (ручной). NULL = 0.12 по умолчанию.';

-- Ретроспективно пометить ручные BUY-заявки (merchant_order_id IS NULL)
UPDATE orders
SET card_fee_pct = 0.14
WHERE direction = 'buy'
  AND merchant_order_id IS NULL
  AND status IN ('PAID', 'COMPLETED', 'OPERATOR_PENDING');

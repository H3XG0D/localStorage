-- Пейин-рельса: BUY-заявка, рубли по которой клиент кладёт на карту
-- реквизитчика вместо провайдера карт. Ссылка нужна для аудита — экономия
-- на эквайринге уже сидит в orders.card_fee_pct (там cost_pct/100 вместо 0.12).
-- Rollback: ALTER TABLE orders DROP COLUMN IF EXISTS payin_requisite_id;

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS payin_requisite_id INT;

COMMENT ON COLUMN orders.payin_requisite_id IS
  'operator_payout_requisites.id (direction=payin), на карту которого клиент платил рубли';

CREATE INDEX IF NOT EXISTS idx_orders_payin_requisite
  ON orders (payin_requisite_id)
  WHERE payin_requisite_id IS NOT NULL;

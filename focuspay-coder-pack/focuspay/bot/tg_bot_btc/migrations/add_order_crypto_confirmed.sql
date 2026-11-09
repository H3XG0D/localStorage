-- Подтверждение прихода крипты по SELL-заявке.
-- Оператор жмёт «оплата получена» → ставим timestamp. Матчер реквизитов
-- берёт в пул выплат только заявки с заполненным crypto_confirmed_at,
-- чтобы рубли не уходили раньше крипты.
-- Rollback: ALTER TABLE orders DROP COLUMN IF EXISTS crypto_confirmed_at;

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS crypto_confirmed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS crypto_confirmed_by INT;

COMMENT ON COLUMN orders.crypto_confirmed_at IS
  'Когда оператор подтвердил приход крипты по SELL (гейт для матчера выплат)';
COMMENT ON COLUMN orders.crypto_confirmed_by IS
  'operator_accounts.id, подтвердивший приход крипты';

CREATE INDEX IF NOT EXISTS idx_orders_sell_crypto_confirmed
  ON orders (crypto_confirmed_at)
  WHERE direction = 'sell' AND crypto_confirmed_at IS NOT NULL;

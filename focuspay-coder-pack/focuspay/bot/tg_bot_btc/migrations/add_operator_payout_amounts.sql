-- Фактические суммы при закрытии SELL оператором (QR в банкомате).
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS operator_crypto_received NUMERIC(20, 8);

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS operator_fiat_paid_out NUMERIC(14, 2);

COMMENT ON COLUMN orders.operator_crypto_received IS
  'Сколько крипты оператор фактически получил от клиента (SELL).';
COMMENT ON COLUMN orders.operator_fiat_paid_out IS
  'Сколько рублей оператор выдал клиенту по QR в банкомате (SELL).';

-- Поля для ручных заявок оператора и SBP QR выплаты (SELL).
ALTER TABLE orders ADD COLUMN IF NOT EXISTS wallet_address TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS network VARCHAR(32);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS payout_qr_data TEXT;

COMMENT ON COLUMN orders.wallet_address IS
  'Кошелёк клиента для ручных BUY-заявок оператора.';
COMMENT ON COLUMN orders.network IS
  'Сеть криптовалюты (TRC20, ERC20 и т.д.).';
COMMENT ON COLUMN orders.payout_qr_data IS
  'SBP QR URL/данные для выплаты наличными клиенту (SELL-заявки).';

-- Сумма крипты и курс USD на момент вывода внештатнику
ALTER TABLE external_payouts
    ADD COLUMN IF NOT EXISTS crypto_amount NUMERIC(18, 8),
    ADD COLUMN IF NOT EXISTS crypto_rate_usd NUMERIC(14, 6);

COMMENT ON COLUMN external_payouts.crypto_amount IS 'Сколько монет отправлено (BTC/LTC/USDT и т.д.)';
COMMENT ON COLUMN external_payouts.crypto_rate_usd IS 'Курс 1 единицы crypto в USD на момент выплаты';

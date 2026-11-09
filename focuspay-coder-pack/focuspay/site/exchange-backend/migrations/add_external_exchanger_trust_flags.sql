ALTER TABLE external_exchangers
  ADD COLUMN IF NOT EXISTS is_trusted_client BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS auto_credit_on_payfast BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN external_exchangers.is_trusted_client IS 'Доверенный внештатник — метка в UI/ops';
COMMENT ON COLUMN external_exchangers.auto_credit_on_payfast IS 'После Payfast — автоначисление на баланс без кнопки оператора';

-- Индивидуальный тариф и переплата для ручных BUY-заявок.
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS manual_spread_pct NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS received_fiat_amount NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS overpay_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS overpay_credit_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE user_cashback_ledger DROP CONSTRAINT IF EXISTS user_cashback_ledger_type_check;
ALTER TABLE user_cashback_ledger ADD CONSTRAINT user_cashback_ledger_type_check
    CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit', 'overpay_credit', 'hold'));

COMMENT ON COLUMN orders.manual_spread_pct IS
  'Индивидуальная наценка ручной BUY-заявки в процентах.';
COMMENT ON COLUMN orders.received_fiat_amount IS
  'Фактически полученная оператором сумма на реквизит по ручной BUY-заявке.';
COMMENT ON COLUMN orders.overpay_rub IS
  'Переплата клиента относительно итоговой суммы к оплате.';
COMMENT ON COLUMN orders.overpay_credit_rub IS
  'Сумма дополнительного баланса за переплату после удержания индивидуального процента.';

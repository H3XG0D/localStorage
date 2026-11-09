-- Внештатная сделка: оператор + начисление в payroll pool

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS operator_id INT REFERENCES operator_accounts(id),
    ADD COLUMN IF NOT EXISTS operator_earnings_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE operator_payroll_ledger
    ADD COLUMN IF NOT EXISTS external_deal_id INT REFERENCES external_deals(id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payroll_accrual_external_deal
    ON operator_payroll_ledger (external_deal_id)
    WHERE type = 'accrual' AND external_deal_id IS NOT NULL;

UPDATE external_exchangers SET net_percent = 0;

COMMENT ON COLUMN external_deals.operator_id IS 'Оператор, оформивший сделку (NULL — admin)';
COMMENT ON COLUMN external_deals.operator_earnings_rub IS 'Начисление оператору с маржи сделки';

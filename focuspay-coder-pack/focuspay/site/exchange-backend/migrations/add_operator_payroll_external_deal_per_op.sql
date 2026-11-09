-- Несколько операторов на смене: начисление с одной внештатной сделки каждому.

DROP INDEX IF EXISTS idx_operator_payroll_accrual_external_deal;

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payroll_accrual_external_deal
    ON operator_payroll_ledger (external_deal_id, operator_id)
    WHERE type = 'accrual' AND external_deal_id IS NOT NULL;

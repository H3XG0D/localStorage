-- Штраф списывает ₽ с личного баланса оператора (не расход P&L).
ALTER TABLE operator_payroll_ledger DROP CONSTRAINT IF EXISTS operator_payroll_ledger_type_check;
ALTER TABLE operator_payroll_ledger ADD CONSTRAINT operator_payroll_ledger_type_check
    CHECK (type IN ('accrual', 'hold', 'payout', 'release', 'penalty'));

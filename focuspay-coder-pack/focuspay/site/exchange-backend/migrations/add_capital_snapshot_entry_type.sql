-- Add 'capital_snapshot' entry type to owner_finance_ledger
-- Apply: psql $DATABASE_DSN -f migrations/add_capital_snapshot_entry_type.sql

-- Drop old constraint
ALTER TABLE owner_finance_ledger
    DROP CONSTRAINT IF EXISTS owner_finance_ledger_entry_type_check;

-- Add new constraint with capital_snapshot
ALTER TABLE owner_finance_ledger
    ADD CONSTRAINT owner_finance_ledger_entry_type_check
    CHECK (entry_type IN (
        'commission', 'refund', 'expense', 'adjustment',
        'payroll', 'transfer', 'capital_snapshot', 'other'
    ));

COMMENT ON COLUMN owner_finance_ledger.entry_type IS
    'Entry types: commission (revenue), refund, expense, adjustment, payroll, transfer, capital_snapshot (periodic balance snapshot), other';

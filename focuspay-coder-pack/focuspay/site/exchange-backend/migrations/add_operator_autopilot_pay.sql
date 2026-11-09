-- Оплата операторов, пока включён автопилот.
-- Старые 30% остаются. Новые ставки применяются только к заявкам,
-- которые завершаются при включённом автопилоте.
ALTER TABLE operator_payroll_settings
    ADD COLUMN IF NOT EXISTS autopilot_presence_percent NUMERIC(6, 3) NOT NULL DEFAULT 5
        CHECK (autopilot_presence_percent BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS autopilot_manual_percent NUMERIC(6, 3) NOT NULL DEFAULT 10
        CHECK (autopilot_manual_percent BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS autopilot_hourly_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS autopilot_hourly_rate_rub NUMERIC(12, 2) NOT NULL DEFAULT 0
        CHECK (autopilot_hourly_rate_rub >= 0);

-- NULL = смена открыта до этой схемы, почасовая на неё не начисляется.
ALTER TABLE operator_shifts
    ADD COLUMN IF NOT EXISTS hourly_enabled BOOLEAN,
    ADD COLUMN IF NOT EXISTS hourly_rate_rub NUMERIC(12, 2);

ALTER TABLE operator_payroll_ledger DROP CONSTRAINT IF EXISTS operator_payroll_ledger_type_check;
ALTER TABLE operator_payroll_ledger ADD CONSTRAINT operator_payroll_ledger_type_check
    CHECK (type IN ('accrual', 'hold', 'payout', 'release', 'penalty', 'hourly'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payroll_hourly_shift
    ON operator_payroll_ledger (shift_id)
    WHERE type = 'hourly' AND shift_id IS NOT NULL;

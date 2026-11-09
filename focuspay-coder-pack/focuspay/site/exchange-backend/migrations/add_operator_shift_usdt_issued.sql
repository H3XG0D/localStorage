-- USDT выданные оператору на смену (для расчёта чистой маржи).
ALTER TABLE operator_shifts
    ADD COLUMN IF NOT EXISTS usdt_issued NUMERIC(18, 8);

COMMENT ON COLUMN operator_shifts.usdt_issued IS
    'USDT выданные оператору на смену (учёт в чистой марже)';

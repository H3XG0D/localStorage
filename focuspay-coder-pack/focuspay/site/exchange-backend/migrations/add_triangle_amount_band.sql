-- Corridor on a triangle card: promise to the client and the frozen ruble cap
-- on how much FocusPay may add above the card nominal.
-- Apply: psql ... -f migrations/add_triangle_amount_band.sql

DO $$
BEGIN
    IF to_regclass('public.operator_payout_requisites') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE operator_payout_requisites
        ADD COLUMN IF NOT EXISTS client_due_rub NUMERIC(18, 2),
        ADD COLUMN IF NOT EXISTS subsidy_cap_rub NUMERIC(18, 2);

    COMMENT ON COLUMN operator_payout_requisites.client_due_rub IS
        'Rubles promised to the client. Shortfall below this is a balance credit, not a PnL expense';
    COMMENT ON COLUMN operator_payout_requisites.subsidy_cap_rub IS
        'Frozen cap: FocusPay tops up at most this many rubles above amount_rub';
END $$;

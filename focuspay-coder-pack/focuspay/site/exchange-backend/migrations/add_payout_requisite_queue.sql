-- Payin cards wait in QUEUED until a senior/grant confirms them into the pool.
-- Apply: psql ... -f migrations/add_payout_requisite_queue.sql

ALTER TABLE operator_payout_requisites
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_by INT REFERENCES operator_accounts(id) ON DELETE SET NULL;

DO $$
BEGIN
    ALTER TABLE operator_payout_requisites
        DROP CONSTRAINT IF EXISTS operator_payout_requisites_status_chk;
    ALTER TABLE operator_payout_requisites
        ADD CONSTRAINT operator_payout_requisites_status_chk
        CHECK (status IN (
            'QUEUED', 'OPEN', 'RESERVED', 'PARTIAL', 'CLOSED', 'EXPIRED', 'CANCELED'
        ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

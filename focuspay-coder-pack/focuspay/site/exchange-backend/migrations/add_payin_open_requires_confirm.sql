-- Payin cannot enter the buyer pool without an explicit confirm.
-- Apply: psql ... -f migrations/add_payin_open_requires_confirm.sql
--
-- Idle OPEN payin without confirmed_at is demoted to QUEUED.
-- Rows that already have buyer allocations keep the pool status and get
-- confirmed_at stamped so the CHECK can be added.

DO $$
BEGIN
    IF to_regclass('public.operator_payout_requisites') IS NULL THEN
        RETURN;
    END IF;

    UPDATE operator_payout_requisites r
    SET status = 'QUEUED',
        updated_at = now()
    WHERE COALESCE(r.direction, 'payout') = 'payin'
      AND r.status IN ('OPEN', 'RESERVED', 'PARTIAL')
      AND r.confirmed_at IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM payout_requisite_allocations a
          WHERE a.requisite_id = r.id
            AND a.status IN ('RESERVED', 'PAID')
      );

    UPDATE operator_payout_requisites
    SET confirmed_at = COALESCE(confirmed_at, created_at, now()),
        updated_at = now()
    WHERE COALESCE(direction, 'payout') = 'payin'
      AND status IN ('OPEN', 'RESERVED', 'PARTIAL')
      AND confirmed_at IS NULL;

    ALTER TABLE operator_payout_requisites
        ALTER COLUMN status SET DEFAULT 'QUEUED';

    BEGIN
        ALTER TABLE operator_payout_requisites
            ADD CONSTRAINT operator_payout_requisites_payin_pool_confirm_chk
            CHECK (
                COALESCE(direction, 'payout') <> 'payin'
                OR status NOT IN ('OPEN', 'RESERVED', 'PARTIAL')
                OR confirmed_at IS NOT NULL
            );
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;

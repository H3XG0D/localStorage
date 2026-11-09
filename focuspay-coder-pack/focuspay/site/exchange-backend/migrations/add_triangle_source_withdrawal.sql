-- Card withdrawal offered to BUY payers (triangle). Live unique so a closed
-- card can be retried; a paid check stays attached to the withdrawal.
-- Apply: psql ... -f migrations/add_triangle_source_withdrawal.sql

DO $$
BEGIN
    IF to_regclass('public.operator_payout_requisites') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE operator_payout_requisites
        ADD COLUMN IF NOT EXISTS source_withdrawal_id INT;

    CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_req_source_withdrawal_live
        ON operator_payout_requisites (source_withdrawal_id)
        WHERE source_withdrawal_id IS NOT NULL
          AND status IN ('QUEUED', 'OPEN', 'RESERVED', 'PARTIAL');

    COMMENT ON COLUMN operator_payout_requisites.source_withdrawal_id IS
        'Balance or casino card withdrawal offered to BUY payers (triangle)';

    IF to_regclass('public.user_referral_withdrawals') IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'operator_payout_requisites_source_withdrawal_fk'
    ) THEN
        ALTER TABLE operator_payout_requisites
            ADD CONSTRAINT operator_payout_requisites_source_withdrawal_fk
            FOREIGN KEY (source_withdrawal_id)
            REFERENCES user_referral_withdrawals(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

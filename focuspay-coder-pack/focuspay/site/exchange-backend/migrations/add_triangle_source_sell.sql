-- Triangle: SELL client's card under BUY payin. Live unique so a closed card
-- can be retried; matcher excludes SELL while the card is in the buyer pool.
-- Apply: psql ... -f migrations/add_triangle_source_sell.sql

DO $$
BEGIN
    IF to_regclass('public.operator_payout_requisites') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE operator_payout_requisites
        ADD COLUMN IF NOT EXISTS source_sell_order_id VARCHAR(64);

    CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_req_source_sell_live
        ON operator_payout_requisites (source_sell_order_id)
        WHERE source_sell_order_id IS NOT NULL
          AND status IN ('QUEUED', 'OPEN', 'RESERVED', 'PARTIAL');

    COMMENT ON COLUMN operator_payout_requisites.source_sell_order_id IS
        'SELL order whose client card is offered to BUY payers (triangle)';
END $$;

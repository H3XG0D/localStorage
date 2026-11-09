-- Durable, idempotent audit trail for casino deposits credited from external deals.
-- Run manually after add_external_exchanges.sql and the casino migrations.
-- This migration intentionally refuses to mask existing external-ledger duplicates.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_deposit_credits (
    id              BIGSERIAL PRIMARY KEY,
    deal_id         INTEGER NOT NULL REFERENCES external_deals(id) ON DELETE RESTRICT,
    exchanger_id    INTEGER NOT NULL REFERENCES external_exchangers(id) ON DELETE RESTRICT,
    telegram_id     BIGINT NOT NULL CHECK (telegram_id > 0),
    amount_rub      NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    ledger_order_id VARCHAR(64) NOT NULL,
    status          VARCHAR(32) NOT NULL CHECK (status IN ('credited', 'legacy_reconciled')),
    credited_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deal_id),
    UNIQUE (ledger_order_id)
);

CREATE INDEX IF NOT EXISTS idx_casino_deposit_credits_telegram
    ON casino_deposit_credits (telegram_id, credited_at DESC);

COMMENT ON TABLE casino_deposit_credits IS
    'Authoritative audit mapping from confirmed external casino deals to unified-balance credits';
COMMENT ON COLUMN casino_deposit_credits.status IS
    'credited is the current durable flow; legacy_reconciled records a validated historic payout without re-crediting';

-- External principal is the exchanger liability and must be written once per deal.
DO $block$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM external_ledger
        WHERE type = 'principal' AND deal_id IS NOT NULL
        GROUP BY deal_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION
            'external_ledger contains duplicate principal rows for one or more deals; reconcile them before applying this migration';
    END IF;
END
$block$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_external_ledger_principal_deal
    ON external_ledger (deal_id)
    WHERE type = 'principal' AND deal_id IS NOT NULL;

GRANT ALL PRIVILEGES ON TABLE casino_deposit_credits TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE casino_deposit_credits_id_seq TO exchange_bot;

COMMIT;

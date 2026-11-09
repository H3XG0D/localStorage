-- Idempotent cross-worker claims for business and operator digest delivery.
-- Safe to run repeatedly; no migration is applied by this change.

CREATE TABLE IF NOT EXISTS digest_deliveries (
    id              BIGSERIAL PRIMARY KEY,
    digest_kind     TEXT NOT NULL,
    recipient_key   TEXT NOT NULL,
    delivery_date   DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    claim_token     TEXT,
    claimed_until   TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_digest_deliveries_delivery
    ON digest_deliveries (digest_kind, recipient_key, delivery_date);

CREATE UNIQUE INDEX IF NOT EXISTS uq_digest_deliveries_claim_token
    ON digest_deliveries (claim_token)
    WHERE claim_token IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'digest_deliveries_status_check'
          AND conrelid = 'digest_deliveries'::regclass
    ) THEN
        ALTER TABLE digest_deliveries
            ADD CONSTRAINT digest_deliveries_status_check
            CHECK (status IN ('pending', 'claimed', 'sent'));
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE ON digest_deliveries TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE digest_deliveries_id_seq TO exchange_bot;
    END IF;
END $$;

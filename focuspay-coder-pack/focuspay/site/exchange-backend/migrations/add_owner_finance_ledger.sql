-- Owner finance journal (minimal). No historical backfill.
-- Apply: psql ... -f migrations/add_owner_finance_ledger.sql
-- Rollback: DROP TABLE IF EXISTS owner_finance_ledger;

CREATE TABLE IF NOT EXISTS owner_finance_ledger (
    id                     BIGSERIAL PRIMARY KEY,
    occurred_at            TIMESTAMPTZ NOT NULL,
    entry_type             TEXT NOT NULL
        CHECK (entry_type IN (
            'commission', 'refund', 'expense', 'adjustment',
            'payroll', 'transfer', 'other'
        )),
    amount                 NUMERIC(14, 2) NOT NULL,
    currency               TEXT NOT NULL DEFAULT 'RUB',
    source                 TEXT,
    reference              TEXT,
    status                 TEXT NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('confirmed', 'pending', 'void')),
    note                   TEXT,
    created_by_web_user_id BIGINT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_owner_finance_ledger_occurred
    ON owner_finance_ledger (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_owner_finance_ledger_type_status
    ON owner_finance_ledger (entry_type, status, occurred_at DESC);

COMMENT ON TABLE owner_finance_ledger IS
    'Confirmed owner finance journal entries. Empty until real postings; do not backfill invented history.';

GRANT SELECT, INSERT, UPDATE, DELETE ON owner_finance_ledger TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE owner_finance_ledger_id_seq TO exchange_bot;

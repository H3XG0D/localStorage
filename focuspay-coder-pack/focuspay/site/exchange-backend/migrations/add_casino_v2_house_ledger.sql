-- Additive v2-only settlement audit. Legacy casino tables and ledger remain untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_v2_house_ledger (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL REFERENCES casino_v2_tables(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES casino_house_accounts(id) ON DELETE RESTRICT,
    operation_key VARCHAR(160) NOT NULL UNIQUE,
    entry_type VARCHAR(32) NOT NULL CHECK (entry_type IN ('game_settlement')),
    amount_rub NUMERIC(14,2) NOT NULL,
    balance_after_rub NUMERIC(14,2) NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (table_id, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_casino_v2_house_ledger_table
    ON casino_v2_house_ledger(table_id, created_at DESC);

COMMENT ON TABLE casino_v2_house_ledger IS
    'Immutable house settlement audit for casino multiplayer v2, linked to casino_v2_tables.';

COMMIT;

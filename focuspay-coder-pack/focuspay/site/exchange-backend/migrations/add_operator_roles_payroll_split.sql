-- Role-aware operator workflow and immutable per-order payroll allocation.
-- Safe to run repeatedly; existing orders and ledger rows are preserved.
ALTER TABLE operator_accounts
    ADD COLUMN IF NOT EXISTS operator_role TEXT NOT NULL DEFAULT 'client'
        CHECK (operator_role IN ('client', 'finance')),
    ADD COLUMN IF NOT EXISTS role_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS role_changed_by BIGINT;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS intake_operator_id INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS finance_operator_id INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS finance_claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS order_source TEXT NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS verification_source TEXT;

CREATE INDEX IF NOT EXISTS idx_orders_intake_operator ON orders (intake_operator_id);
CREATE INDEX IF NOT EXISTS idx_orders_finance_operator ON orders (finance_operator_id);
CREATE INDEX IF NOT EXISTS idx_orders_finance_queue ON orders (status, direction, finance_operator_id)
    WHERE status NOT IN ('PAID', 'CANCELED', 'EXPIRED', 'FAILED');

CREATE TABLE IF NOT EXISTS operator_payroll_settings (
    id BIGSERIAL PRIMARY KEY,
    operator_pool_percent NUMERIC(6, 3) NOT NULL CHECK (operator_pool_percent BETWEEN 0 AND 100),
    client_operator_share_percent NUMERIC(6, 3) NOT NULL CHECK (client_operator_share_percent BETWEEN 0 AND 100),
    finance_operator_share_percent NUMERIC(6, 3) NOT NULL CHECK (finance_operator_share_percent BETWEEN 0 AND 100),
    unassigned_policy TEXT NOT NULL DEFAULT 'ledger'
        CHECK (unassigned_policy IN ('ledger', 'business')),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (client_operator_share_percent + finance_operator_share_percent = 100)
);
CREATE INDEX IF NOT EXISTS idx_operator_payroll_settings_current
    ON operator_payroll_settings (valid_from DESC) WHERE valid_to IS NULL;

INSERT INTO operator_payroll_settings
    (operator_pool_percent, client_operator_share_percent, finance_operator_share_percent)
SELECT 30, 30, 70
WHERE NOT EXISTS (SELECT 1 FROM operator_payroll_settings);

CREATE TABLE IF NOT EXISTS order_payroll_splits (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL UNIQUE,
    profit_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    operator_pool_percent NUMERIC(6, 3) NOT NULL,
    pool_rub NUMERIC(14, 2) NOT NULL,
    client_pool_rub NUMERIC(14, 2) NOT NULL,
    finance_pool_rub NUMERIC(14, 2) NOT NULL,
    unassigned_client_pool_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    unassigned_finance_pool_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    settings_id BIGINT REFERENCES operator_payroll_settings(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_payroll_split_lines (
    id BIGSERIAL PRIMARY KEY,
    split_id BIGINT NOT NULL REFERENCES order_payroll_splits(id) ON DELETE CASCADE,
    operator_id INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('client', 'finance', 'unassigned')),
    amount_rub NUMERIC(14, 2) NOT NULL CHECK (amount_rub >= 0),
    weight NUMERIC(14, 6) NOT NULL DEFAULT 1,
    participant_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    ledger_id BIGINT REFERENCES operator_payroll_ledger(id) ON DELETE SET NULL,
    UNIQUE (split_id, operator_id, role)
);

CREATE TABLE IF NOT EXISTS operator_role_audit (
    id BIGSERIAL PRIMARY KEY,
    operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    old_role TEXT,
    new_role TEXT NOT NULL,
    changed_by BIGINT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT ALL PRIVILEGES ON TABLE operator_payroll_settings, order_payroll_splits,
    order_payroll_split_lines, operator_role_audit TO exchange_bot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;

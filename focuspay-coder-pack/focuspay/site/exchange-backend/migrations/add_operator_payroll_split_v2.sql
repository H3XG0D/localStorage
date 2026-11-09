-- Versioned grades, immutable order participants and idempotent role split accruals.
-- Run after add_operator_dual_roles.sql, add_operator_payroll_pool.sql and
-- add_operator_roles_payroll_split.sql. This migration keeps legacy percent data.

CREATE TABLE IF NOT EXISTS operator_payroll_grade_settings (
    id BIGSERIAL PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('client', 'finance')),
    grade TEXT NOT NULL CHECK (grade IN ('trainee', 'junior', 'senior')),
    weight_multiplier NUMERIC(10, 6) NOT NULL CHECK (weight_multiplier > 0),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    created_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_grade_settings_current
    ON operator_payroll_grade_settings (role, grade)
    WHERE valid_to IS NULL;

INSERT INTO operator_payroll_grade_settings (role, grade, weight_multiplier)
SELECT v.role, v.grade, v.weight_multiplier
FROM (VALUES
    ('client', 'trainee', 0.75::numeric),
    ('client', 'junior', 1.00::numeric),
    ('client', 'senior', 1.25::numeric),
    ('finance', 'trainee', 0.75::numeric),
    ('finance', 'junior', 1.00::numeric),
    ('finance', 'senior', 1.25::numeric)
) AS v(role, grade, weight_multiplier)
WHERE NOT EXISTS (
    SELECT 1
    FROM operator_payroll_grade_settings s
    WHERE s.role = v.role AND s.grade = v.grade AND s.valid_to IS NULL
);

CREATE TABLE IF NOT EXISTS operator_role_profiles (
    id BIGSERIAL PRIMARY KEY,
    operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('client', 'finance')),
    grade TEXT NOT NULL CHECK (grade IN ('trainee', 'junior', 'senior')),
    grade_weight NUMERIC(10, 6) NOT NULL CHECK (grade_weight > 0),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    changed_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_role_profiles_current
    ON operator_role_profiles (operator_id, role)
    WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS idx_operator_role_profiles_operator
    ON operator_role_profiles (operator_id, valid_from DESC);

INSERT INTO operator_role_profiles (operator_id, role, grade, grade_weight)
SELECT oa.id, role_value, 'junior', 1.0
FROM operator_accounts oa
CROSS JOIN LATERAL unnest(oa.operator_roles) AS roles(role_value)
WHERE NOT EXISTS (
    SELECT 1
    FROM operator_role_profiles p
    WHERE p.operator_id = oa.id AND p.role = roles.role_value AND p.valid_to IS NULL
);

CREATE TABLE IF NOT EXISTS order_operator_participants (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('client', 'finance')),
    participation_type TEXT NOT NULL CHECK (participation_type IN ('intake', 'payout', 'helper')),
    grade TEXT NOT NULL CHECK (grade IN ('trainee', 'junior', 'senior')),
    grade_weight NUMERIC(10, 6) NOT NULL CHECK (grade_weight > 0),
    weight NUMERIC(14, 6) NOT NULL CHECK (weight > 0),
    participant_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    assigned_by INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_order_operator_participants_active
    ON order_operator_participants (order_id, operator_id, role, participation_type)
    WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_order_operator_participants_order
    ON order_operator_participants (order_id, role) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_order_operator_participants_operator
    ON order_operator_participants (operator_id, assigned_at DESC);

ALTER TABLE order_payroll_splits
    ADD COLUMN IF NOT EXISTS settings_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE order_payroll_split_lines
    ADD COLUMN IF NOT EXISTS unassigned_for TEXT
        CHECK (unassigned_for IS NULL OR unassigned_for IN ('client', 'finance'));

ALTER TABLE operator_payroll_ledger
    ADD COLUMN IF NOT EXISTS payroll_split_line_id BIGINT
        REFERENCES order_payroll_split_lines(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payroll_ledger_split_line
    ON operator_payroll_ledger (payroll_split_line_id)
    WHERE type = 'accrual' AND payroll_split_line_id IS NOT NULL;

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS payroll_model TEXT NOT NULL DEFAULT 'legacy'
        CHECK (payroll_model IN ('legacy', 'role_split')),
    ADD COLUMN IF NOT EXISTS payroll_split_required BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS payroll_split_id BIGINT
        REFERENCES order_payroll_splits(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_orders_payroll_split_required
    ON orders (status, payroll_split_required)
    WHERE payroll_split_required = TRUE;

GRANT ALL PRIVILEGES ON TABLE operator_payroll_grade_settings,
    operator_role_profiles, order_operator_participants TO exchange_bot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;

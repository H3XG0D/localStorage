-- Dual-role capability support. Keeps operator_role as legacy display/compatibility field.
ALTER TABLE operator_accounts
    ADD COLUMN IF NOT EXISTS operator_roles TEXT[];

UPDATE operator_accounts
SET operator_roles = ARRAY[COALESCE(operator_role, 'client')]
WHERE operator_roles IS NULL OR cardinality(operator_roles) = 0;

ALTER TABLE operator_accounts
    ALTER COLUMN operator_roles SET DEFAULT ARRAY['client']::TEXT[],
    ALTER COLUMN operator_roles SET NOT NULL;

ALTER TABLE operator_accounts
    DROP CONSTRAINT IF EXISTS operator_accounts_operator_roles_check;
ALTER TABLE operator_accounts
    ADD CONSTRAINT operator_accounts_operator_roles_check
    CHECK (operator_roles <@ ARRAY['client', 'finance']::TEXT[] AND cardinality(operator_roles) BETWEEN 1 AND 2);

CREATE INDEX IF NOT EXISTS idx_operator_accounts_roles_gin ON operator_accounts USING GIN (operator_roles);

COMMENT ON COLUMN operator_accounts.operator_roles IS 'Capabilities assigned to the operator: client, finance, or both.';

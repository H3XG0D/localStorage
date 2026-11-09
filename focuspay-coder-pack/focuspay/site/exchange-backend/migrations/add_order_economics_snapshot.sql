ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS economics_snapshot JSONB;

COMMENT ON COLUMN orders.economics_snapshot IS
    'Immutable quote-time pricing and service-profit snapshot; legacy rows are backfilled separately.';

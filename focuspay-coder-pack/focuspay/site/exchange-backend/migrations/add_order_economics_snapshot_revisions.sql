CREATE TABLE IF NOT EXISTS order_economics_snapshot_revisions (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
    run_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    old_snapshot JSONB,
    new_snapshot JSONB NOT NULL,
    old_service_profit_rub NUMERIC(18, 2),
    new_service_profit_rub NUMERIC(18, 2) NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reverted_at TIMESTAMPTZ,
    rollback_skipped_at TIMESTAMPTZ,
    UNIQUE (run_id, order_id)
);

CREATE INDEX IF NOT EXISTS idx_order_economics_snapshot_revisions_run_id
    ON order_economics_snapshot_revisions (run_id);

COMMENT ON TABLE order_economics_snapshot_revisions IS
    'Auditable revisions made by the historical BUY economics reprice script.';

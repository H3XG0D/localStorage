-- Дедуп алертов владельцу о зависших COMPLETED (переживает рестарт бота)
CREATE TABLE IF NOT EXISTS owner_stale_alerts (
    order_id VARCHAR(64) PRIMARY KEY,
    alerted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_owner_stale_alerts_at ON owner_stale_alerts (alerted_at);

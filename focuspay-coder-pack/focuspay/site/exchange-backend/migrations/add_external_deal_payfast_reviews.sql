-- Safety incidents for PayFast external-deal callbacks and receipt processing.
CREATE TABLE IF NOT EXISTS external_deal_payfast_reviews (
    id BIGSERIAL PRIMARY KEY,
    incident_type TEXT NOT NULL CHECK (incident_type IN (
        'unknown_callback',
        'callback_mismatch',
        'receipt_rejected_permanent',
        'post_completion_provider_error'
    )),
    deal_id INT REFERENCES external_deals(id) ON DELETE SET NULL,
    merchant_ref TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dedupe_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_external_deal_payfast_reviews_deal_created
    ON external_deal_payfast_reviews (deal_id, created_at DESC);

GRANT ALL PRIVILEGES ON TABLE external_deal_payfast_reviews TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE external_deal_payfast_reviews_id_seq TO exchange_bot;

COMMENT ON TABLE external_deal_payfast_reviews IS
    'Deduplicated PayFast safety incidents; detail contains only safe codes and field names.';

-- 000009: FocusPay-driven grants (plans/E4-billing, ADR-010).
--
-- billing_events.idempotency_key is the FocusPay purchase id. The event row and
-- the subscription change are written in one transaction (store.GrantSubscription).
-- amount_kopecks is what FocusPay charged; CP does not price anything.

ALTER TABLE billing_events
    ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'paid' CHECK (kind IN ('paid', 'trial')),
    ADD COLUMN IF NOT EXISTS plan_code text NOT NULL DEFAULT 'week',
    ADD COLUMN IF NOT EXISTS amount_kopecks bigint NOT NULL DEFAULT 0 CHECK (amount_kopecks >= 0),
    ADD COLUMN IF NOT EXISTS ends_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_events_one_trial
    ON billing_events (user_id) WHERE kind = 'trial';

CREATE INDEX IF NOT EXISTS idx_billing_events_created ON billing_events (created_at);

INSERT INTO plans (id, code, name, max_devices, period_days, price_cents, features) VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa5', 'month', 'Month', 3, 30, 0, '{"source":"focuspay_wallet"}'::jsonb),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa6', 'q3', '3 months', 3, 90, 0, '{"source":"focuspay_wallet"}'::jsonb),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa7', 'trial', 'Trial', 1, 1, 0, '{"source":"focuspay_trial"}'::jsonb)
ON CONFLICT (code) DO NOTHING;

-- Prices are owned by FocusPay; the CP plan row is a reference only.
UPDATE plans SET price_cents = 0, updated_at = now() WHERE code = 'week';

-- One canonical VLESS protocol name.
UPDATE vpn_endpoints e SET protocol = 'vless', updated_at = now()
WHERE e.protocol IN ('vless-ws', 'xray')
  AND NOT EXISTS (
      SELECT 1 FROM vpn_endpoints o
      WHERE o.node_id = e.node_id AND o.port = e.port AND o.protocol = 'vless'
  );

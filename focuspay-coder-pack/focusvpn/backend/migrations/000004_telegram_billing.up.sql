-- E1: Telegram identity + billing idempotency + week plan (ADR-007).

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS telegram_id bigint;

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_id
    ON users (telegram_id) WHERE telegram_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS billing_events (
    idempotency_key text PRIMARY KEY,
    telegram_id     bigint NOT NULL,
    days            int    NOT NULL,
    subscription_id uuid   NOT NULL REFERENCES subscriptions (id),
    user_id         uuid   NOT NULL REFERENCES users (id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_events_telegram ON billing_events (telegram_id);

INSERT INTO plans (id, code, name, max_devices, period_days, price_cents, features)
VALUES (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4',
    'week',
    'Week',
    3,
    7,
    30000,
    '{"source":"focuspay_wallet"}'::jsonb
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    max_devices = EXCLUDED.max_devices,
    period_days = EXCLUDED.period_days,
    price_cents = EXCLUDED.price_cents,
    features = EXCLUDED.features,
    updated_at = now();

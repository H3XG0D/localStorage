-- E2: Telegram app login (deep-link + short code) + week plan max_devices = 1.

CREATE TABLE IF NOT EXISTS app_login_requests (
    id               uuid PRIMARY KEY,
    start_token_hash text UNIQUE,
    pair_code_hash   text UNIQUE,
    wait_token_hash  text UNIQUE,
    telegram_id      bigint,
    user_id          uuid REFERENCES users (id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    expires_at       timestamptz NOT NULL,
    attached_at      timestamptz,
    consumed_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_app_login_expires ON app_login_requests (expires_at);

UPDATE plans SET max_devices = 1, updated_at = now() WHERE code = 'week';

-- Реквизиты по HMAC API + таймер оплаты внештатной сделки
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_exchanger_hmac_api_and_expires.sql

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS client_transaction_id TEXT,
    ADD COLUMN IF NOT EXISTS callback_url TEXT,
    ADD COLUMN IF NOT EXISTS customer_fingerprint TEXT;

COMMENT ON COLUMN external_deals.expires_at IS
    'Дедлайн оплаты клиента (20 мин или dateEnd мерчанта); UI-таймер, без автоотмены';
COMMENT ON COLUMN external_deals.client_transaction_id IS
    'Идемпотентный id сделки магазина (HMAC API)';
COMMENT ON COLUMN external_deals.callback_url IS
    'URL магазина: credited / cancelled / expired';
COMMENT ON COLUMN external_deals.customer_fingerprint IS
    'Id клиента магазина → fingerprint payin (не -exchanger_id)';

CREATE UNIQUE INDEX IF NOT EXISTS external_deals_exchanger_client_tx_uidx
    ON external_deals (exchanger_id, client_transaction_id)
    WHERE client_transaction_id IS NOT NULL AND client_transaction_id <> '';

CREATE TABLE IF NOT EXISTS external_exchanger_api_keys (
    id           SERIAL PRIMARY KEY,
    exchanger_id INTEGER NOT NULL REFERENCES external_exchangers(id),
    api_key      VARCHAR(64) NOT NULL UNIQUE,
    secret       TEXT NOT NULL,
    secret_hash  VARCHAR(128) NOT NULL,
    secret_hint  VARCHAR(16) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS external_exchanger_api_keys_one_active
    ON external_exchanger_api_keys (exchanger_id)
    WHERE is_active = TRUE;

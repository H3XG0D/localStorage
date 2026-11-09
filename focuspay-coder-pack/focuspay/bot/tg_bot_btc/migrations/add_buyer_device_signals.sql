-- Device fingerprint / IP signals from Telegram Mini App (requisites reveal).
CREATE TABLE IF NOT EXISTS buyer_device_signals (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    order_id        VARCHAR(32),
    fingerprint     VARCHAR(128),
    ip              INET,
    user_agent      TEXT,
    platform        TEXT,
    screen          TEXT,
    timezone        TEXT,
    languages       JSONB,
    extra           JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_buyer_device_signals_fp
    ON buyer_device_signals (fingerprint)
    WHERE fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_buyer_device_signals_ip
    ON buyer_device_signals (ip)
    WHERE ip IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_buyer_device_signals_user
    ON buyer_device_signals (user_id, created_at DESC);

COMMENT ON TABLE buyer_device_signals IS 'TG Mini App device fingerprint + IP for antifraud reuse';

ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS device_review_status VARCHAR(20) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS device_review_reason TEXT,
    ADD COLUMN IF NOT EXISTS device_review_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS device_review_by BIGINT;

COMMENT ON COLUMN bot_users.device_review_status IS 'none|pending|approved|rejected — device/FP reuse review (отдельно от account_review)';

GRANT ALL PRIVILEGES ON TABLE buyer_device_signals TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE buyer_device_signals_id_seq TO exchange_bot;

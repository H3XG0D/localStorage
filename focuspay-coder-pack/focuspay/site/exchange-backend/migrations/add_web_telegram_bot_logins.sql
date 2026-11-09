-- One-time casino login via exchange-bot /start cauth_<token>.
-- Idempotent.

CREATE TABLE IF NOT EXISTS web_telegram_bot_logins (
    id                  BIGSERIAL PRIMARY KEY,
    start_token_hash    TEXT UNIQUE,
    ticket_hash         TEXT UNIQUE,
    return_path         TEXT NOT NULL DEFAULT '/casino',
    telegram_user_id    BIGINT,
    tg_username         TEXT,
    tg_first_name       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at          TIMESTAMPTZ NOT NULL,
    wait_consumed_at    TIMESTAMPTZ,
    ticket_consumed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_web_telegram_bot_logins_expires
    ON web_telegram_bot_logins (expires_at);

CREATE INDEX IF NOT EXISTS idx_web_telegram_bot_logins_tg
    ON web_telegram_bot_logins (telegram_user_id)
    WHERE telegram_user_id IS NOT NULL;

COMMENT ON TABLE web_telegram_bot_logins IS
    'Casino site → t.me/?start=cauth_ TOKEN; bot sets telegram_user_id; site polls wait or opens ticket URL';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON web_telegram_bot_logins TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE web_telegram_bot_logins_id_seq TO exchange_bot;
    END IF;
END $$;

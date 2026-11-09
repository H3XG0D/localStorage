-- Лог /start с реферальным payload (для восстановления и аудита).
CREATE TABLE IF NOT EXISTS bot_start_ref_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    payload     TEXT NOT NULL,
    ref_token   VARCHAR(32),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bot_start_ref_log_user
    ON bot_start_ref_log (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bot_start_ref_log_token
    ON bot_start_ref_log (ref_token, created_at DESC)
    WHERE ref_token IS NOT NULL;

COMMENT ON TABLE bot_start_ref_log IS
    'Сырые deep-link payload из /start; пишется до капчи';

GRANT ALL PRIVILEGES ON TABLE bot_start_ref_log TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE bot_start_ref_log_id_seq TO exchange_bot;

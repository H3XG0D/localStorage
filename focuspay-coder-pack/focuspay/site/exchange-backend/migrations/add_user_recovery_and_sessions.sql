-- Восстановление пароля по разовому recovery-коду + постоянные cookie-сессии
-- покупателя + антифрод-метки (fingerprint/IP при регистрации).
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_user_recovery_and_sessions.sql

-- 1. Recovery-код и антифрод-метки на аккаунте покупателя
ALTER TABLE web_users
    ADD COLUMN IF NOT EXISTS recovery_code_hash   TEXT,
    ADD COLUMN IF NOT EXISTS recovery_code_set_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS signup_ip            TEXT,
    ADD COLUMN IF NOT EXISTS signup_fingerprint   TEXT;

COMMENT ON COLUMN web_users.recovery_code_hash IS
    'bcrypt-хэш разового recovery-кода для сброса пароля (email не используется)';
COMMENT ON COLUMN web_users.recovery_code_set_at IS
    'Когда recovery-код был выдан/ротирован';
COMMENT ON COLUMN web_users.signup_ip IS
    'IP при регистрации — антифрод по мультиаккаунтам';
COMMENT ON COLUMN web_users.signup_fingerprint IS
    'Browser fingerprint при регистрации — привязка к устройству';

CREATE INDEX IF NOT EXISTS idx_web_users_signup_fingerprint
    ON web_users (signup_fingerprint)
    WHERE signup_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_web_users_signup_ip
    ON web_users (signup_ip)
    WHERE signup_ip IS NOT NULL;

-- 2. Постоянные отзываемые cookie-сессии покупателя
CREATE TABLE IF NOT EXISTS web_user_sessions (
    id            BIGSERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip            TEXT,
    fingerprint   TEXT,
    revoked       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_web_user_sessions_user_id
    ON web_user_sessions (user_id);

CREATE INDEX IF NOT EXISTS idx_web_user_sessions_active
    ON web_user_sessions (token_hash)
    WHERE revoked = FALSE;

COMMENT ON TABLE web_user_sessions IS
    'Постоянные HttpOnly cookie-сессии покупателя (хранится только хэш токена), можно отзывать';

GRANT ALL PRIVILEGES ON TABLE web_user_sessions TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_user_sessions_id_seq TO exchange_bot;

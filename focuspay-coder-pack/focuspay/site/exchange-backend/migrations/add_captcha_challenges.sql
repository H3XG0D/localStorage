-- Stateful captcha challenges для предотвращения replay attacks
-- Каждый challenge используется только один раз

CREATE TABLE IF NOT EXISTS captcha_challenges (
    id BIGSERIAL PRIMARY KEY,
    challenge_text TEXT NOT NULL,
    answer_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    guest_session UUID,
    ip_address INET,
    user_agent TEXT
);

-- Index для быстрого поиска по ID и проверки TTL
CREATE INDEX IF NOT EXISTS captcha_challenges_created_at_idx 
    ON captcha_challenges(created_at) 
    WHERE consumed_at IS NULL;

-- Index для cleanup старых записей
CREATE INDEX IF NOT EXISTS captcha_challenges_cleanup_idx 
    ON captcha_challenges(created_at);

-- Опционально: track по guest_session для rate limiting
CREATE INDEX IF NOT EXISTS captcha_challenges_guest_session_idx 
    ON captcha_challenges(guest_session, created_at);

COMMENT ON TABLE captcha_challenges IS 'Stateful captcha challenges с single-use enforcement';
COMMENT ON COLUMN captcha_challenges.challenge_text IS 'Текст задания (для логов/отладки)';
COMMENT ON COLUMN captcha_challenges.answer_hash IS 'SHA256 хэш правильного ответа';
COMMENT ON COLUMN captcha_challenges.consumed_at IS 'Когда challenge был использован (NULL = не использован)';
COMMENT ON COLUMN captcha_challenges.guest_session IS 'UUID гостевой сессии (если есть)';
COMMENT ON COLUMN captcha_challenges.ip_address IS 'IP адрес запросившего challenge';

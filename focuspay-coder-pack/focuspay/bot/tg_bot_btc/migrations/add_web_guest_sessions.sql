CREATE TABLE IF NOT EXISTS web_guest_sessions (
    session_token   UUID PRIMARY KEY,
    synthetic_user_id BIGINT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS web_guest_user_id_seq START 1;

COMMENT ON TABLE web_guest_sessions IS 'Гостевые сессии сайта; synthetic_user_id (отрицательный) в orders.user_id';

GRANT ALL PRIVILEGES ON TABLE web_guest_sessions TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_guest_user_id_seq TO exchange_bot;

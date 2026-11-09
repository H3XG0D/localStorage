-- Casino player nickname and uploaded avatar (web, not only Telegram cache).
BEGIN;

CREATE TABLE IF NOT EXISTS casino_player_cosmetics (
    user_id BIGINT PRIMARY KEY CHECK (user_id <> 0),
    nickname VARCHAR(32),
    avatar_ext VARCHAR(8),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE casino_player_cosmetics IS
    'Optional casino nick and uploaded avatar; public_actors prefers these over Telegram.';

COMMIT;

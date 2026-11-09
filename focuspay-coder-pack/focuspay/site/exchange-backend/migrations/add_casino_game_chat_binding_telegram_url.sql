-- Explicit navigation URL for the administrator-approved PVP game chat.
-- The bot never derives private invite links from Telegram.

ALTER TABLE casino_game_chat_bindings
    ADD COLUMN IF NOT EXISTS telegram_url VARCHAR(255);

COMMENT ON COLUMN casino_game_chat_bindings.telegram_url IS
    'Public t.me URL or explicit invite URL supplied by the administrator for personal lobby navigation';

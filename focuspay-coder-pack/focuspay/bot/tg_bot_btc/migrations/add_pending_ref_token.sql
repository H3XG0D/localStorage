-- Отложенная реферальная ссылка (если /start пришёл без payload)
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS pending_ref_token VARCHAR(32);

COMMENT ON COLUMN bot_users.pending_ref_token IS
    'Последний uref-токен из ссылки; применяется при /start если атрибуции ещё нет';

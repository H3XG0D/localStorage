-- Отметка о прохождении капчи в боте при первом /start.
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS captcha_passed_at TIMESTAMPTZ DEFAULT NULL;

-- Фото в чате поддержки.
ALTER TABLE web_chat_messages
ADD COLUMN IF NOT EXISTS message_type VARCHAR(10) NOT NULL DEFAULT 'text';

ALTER TABLE web_chat_messages
ADD COLUMN IF NOT EXISTS attachment_id VARCHAR(64);

ALTER TABLE web_chat_messages
ALTER COLUMN body DROP NOT NULL;

ALTER TABLE web_chat_messages
ALTER COLUMN body SET DEFAULT '';

UPDATE web_chat_messages SET body = '' WHERE body IS NULL;

ALTER TABLE web_chat_messages DROP CONSTRAINT IF EXISTS web_chat_messages_type_check;

-- На проде могли накопиться сообщения с другими значениями message_type.
-- Приводим к допустимым, чтобы миграция была идемпотентной.
UPDATE web_chat_messages
SET message_type = 'text'
WHERE COALESCE(TRIM(message_type), '') NOT IN ('text', 'image');

ALTER TABLE web_chat_messages
ADD CONSTRAINT web_chat_messages_type_check
CHECK (message_type IN ('text', 'image'));

COMMENT ON COLUMN web_chat_messages.attachment_id IS 'UUID файла в chat_uploads/';
COMMENT ON COLUMN web_chat_messages.message_type IS 'text | image';

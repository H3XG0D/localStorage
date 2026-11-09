-- Стикеры в чате поддержки (Telegram Business).
ALTER TABLE web_chat_messages DROP CONSTRAINT IF EXISTS web_chat_messages_type_check;
ALTER TABLE web_chat_messages
  ADD CONSTRAINT web_chat_messages_type_check
  CHECK (message_type IN ('text', 'image', 'video', 'document', 'audio', 'sticker'));

ALTER TABLE web_chat_messages
  ADD COLUMN IF NOT EXISTS sticker_file_id VARCHAR(256);

ALTER TABLE web_chat_messages
  ADD COLUMN IF NOT EXISTS sticker_emoji VARCHAR(32);

ALTER TABLE web_chat_messages
  ADD COLUMN IF NOT EXISTS sticker_set_name VARCHAR(256);

COMMENT ON COLUMN web_chat_messages.sticker_file_id IS 'Telegram file_id для sendSticker (исходящие и inbound)';
COMMENT ON COLUMN web_chat_messages.message_type IS 'text | image | video | document | audio | sticker';

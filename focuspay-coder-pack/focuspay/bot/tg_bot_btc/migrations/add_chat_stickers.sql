-- Mirror: exchange/backend/migrations/add_chat_stickers.sql
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

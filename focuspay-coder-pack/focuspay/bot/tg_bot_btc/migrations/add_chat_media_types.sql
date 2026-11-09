-- Расширение типов сообщений чата: video, document, audio.
ALTER TABLE web_chat_messages DROP CONSTRAINT IF EXISTS web_chat_messages_type_check;
ALTER TABLE web_chat_messages
  ADD CONSTRAINT web_chat_messages_type_check
  CHECK (message_type IN ('text', 'image', 'video', 'document', 'audio'));

ALTER TABLE web_chat_messages
  ADD COLUMN IF NOT EXISTS attachment_filename VARCHAR(255);

COMMENT ON COLUMN web_chat_messages.attachment_filename IS 'Оригинальное имя файла (документы, видео)';
COMMENT ON COLUMN web_chat_messages.message_type IS 'text | image | video | document | audio';

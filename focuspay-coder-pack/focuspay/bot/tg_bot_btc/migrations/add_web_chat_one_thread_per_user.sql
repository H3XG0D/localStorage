-- Один диалог на Telegram-пользователя; слияние дубликатов.

DO $$
DECLARE
  rec RECORD;
  v_keep_id BIGINT;
  v_extra_unread INT;
BEGIN
  FOR rec IN
    SELECT telegram_user_id AS uid
    FROM web_chat_threads
    WHERE telegram_user_id IS NOT NULL
    GROUP BY telegram_user_id
    HAVING COUNT(*) > 1
  LOOP
    SELECT id INTO v_keep_id
    FROM web_chat_threads
    WHERE telegram_user_id = rec.uid
    ORDER BY last_message_at DESC NULLS LAST, id ASC
    LIMIT 1;

    SELECT COALESCE(SUM(admin_unread), 0)::int INTO v_extra_unread
    FROM web_chat_threads
    WHERE telegram_user_id = rec.uid AND id <> v_keep_id;

    UPDATE web_chat_messages SET thread_id = v_keep_id
    WHERE thread_id IN (
      SELECT id FROM web_chat_threads
      WHERE telegram_user_id = rec.uid AND id <> v_keep_id
    );

    UPDATE web_chat_threads SET
      admin_unread = admin_unread + v_extra_unread,
      last_message_at = GREATEST(
        last_message_at,
        (SELECT MAX(last_message_at) FROM web_chat_threads
         WHERE telegram_user_id = rec.uid AND id <> v_keep_id)
      ),
      source = CASE
        WHEN EXISTS (
          SELECT 1 FROM web_chat_threads x
          WHERE x.telegram_user_id = rec.uid AND x.id <> v_keep_id
            AND x.source IN ('telegram', 'both')
        ) AND source = 'web' THEN 'both'
        WHEN source = 'telegram' AND EXISTS (
          SELECT 1 FROM web_chat_threads x
          WHERE x.telegram_user_id = rec.uid AND x.id <> v_keep_id AND x.source = 'web'
        ) THEN 'both'
        ELSE source
      END,
      telegram_dm_chat_id = COALESCE(
        telegram_dm_chat_id,
        (SELECT telegram_dm_chat_id FROM web_chat_threads
         WHERE telegram_user_id = rec.uid AND id <> v_keep_id
           AND telegram_dm_chat_id IS NOT NULL LIMIT 1)
      ),
      business_connection_id = COALESCE(
        business_connection_id,
        (SELECT business_connection_id FROM web_chat_threads
         WHERE telegram_user_id = rec.uid AND id <> v_keep_id
           AND business_connection_id IS NOT NULL LIMIT 1)
      ),
      updated_at = now()
    WHERE id = v_keep_id;

    DELETE FROM web_chat_threads
    WHERE telegram_user_id = rec.uid AND id <> v_keep_id;
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_web_chat_threads_telegram_user_unique
    ON web_chat_threads (telegram_user_id)
    WHERE telegram_user_id IS NOT NULL;

COMMENT ON INDEX idx_web_chat_threads_telegram_user_unique IS
    'Один сохранённый диалог на Telegram user_id';

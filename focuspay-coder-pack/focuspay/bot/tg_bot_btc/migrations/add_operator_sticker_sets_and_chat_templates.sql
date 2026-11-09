-- Личные sticker-set'ы операторов и быстрые ответы / автоответы в чате.

CREATE TABLE IF NOT EXISTS operator_sticker_sets (
  id SERIAL PRIMARY KEY,
  operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
  set_name VARCHAR(256) NOT NULL,
  title VARCHAR(256),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (operator_id, set_name)
);

CREATE INDEX IF NOT EXISTS idx_operator_sticker_sets_op ON operator_sticker_sets(operator_id);

CREATE TABLE IF NOT EXISTS operator_chat_templates (
  id SERIAL PRIMARY KEY,
  operator_id INT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
  title VARCHAR(64) NOT NULL,
  body TEXT NOT NULL,
  trigger_phrase VARCHAR(256) NULL,
  sort_order INT NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_templates_global
  ON operator_chat_templates(sort_order, id)
  WHERE operator_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_chat_templates_op
  ON operator_chat_templates(operator_id, sort_order, id)
  WHERE operator_id IS NOT NULL;

INSERT INTO operator_chat_templates (operator_id, title, body, trigger_phrase, sort_order)
SELECT NULL, v.title, v.body, v.trigger_phrase, v.sort_order
FROM (VALUES
  (
    'Ожидайте',
    'Ожидайте, оператор скоро ответит.',
    NULL::VARCHAR(256),
    10
  ),
  (
    'Номер заявки',
    'Пришлите, пожалуйста, номер заявки или скрин оплаты.',
    NULL::VARCHAR(256),
    20
  ),
  (
    'Че кого',
    E'Че как! На связи — оператор скоро ответит.\nЕсли срочно, напишите вопрос одним сообщением.',
    'че кого'::VARCHAR(256),
    30
  )
) AS v(title, body, trigger_phrase, sort_order)
WHERE NOT EXISTS (
  SELECT 1 FROM operator_chat_templates WHERE operator_id IS NULL LIMIT 1
);

-- RBAC grants + усиление shared chat templates (author / system / version / audit).

CREATE TABLE IF NOT EXISTS operator_permission_grants (
  operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
  permission TEXT NOT NULL,
  granted BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (operator_id, permission)
);

ALTER TABLE operator_chat_templates
  ADD COLUMN IF NOT EXISTS created_by_operator_id INT NULL REFERENCES operator_accounts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS is_system BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

-- Seed / legacy global templates без автора считаем системными.
UPDATE operator_chat_templates
SET is_system = TRUE
WHERE operator_id IS NULL
  AND created_by_operator_id IS NULL
  AND title IN ('Ожидайте', 'Номер заявки', 'Че кого');

CREATE TABLE IF NOT EXISTS operator_chat_template_audit (
  id BIGSERIAL PRIMARY KEY,
  template_id INT NOT NULL,
  actor_kind TEXT NOT NULL, -- operator | admin | system
  actor_id INT NULL,
  action TEXT NOT NULL, -- create | update | delete | priority
  before_json JSONB NULL,
  after_json JSONB NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_template_audit_template
  ON operator_chat_template_audit(template_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_templates_created_by
  ON operator_chat_templates(created_by_operator_id)
  WHERE created_by_operator_id IS NOT NULL;

COMMENT ON COLUMN operator_chat_templates.is_system IS 'Системный шаблон: менять только с templates.edit_system';
COMMENT ON COLUMN operator_chat_templates.version IS 'Optimistic lock для concurrent update/delete';
COMMENT ON COLUMN operator_chat_templates.created_by_operator_id IS 'Автор shared-шаблона (operator_id IS NULL = global scope)';

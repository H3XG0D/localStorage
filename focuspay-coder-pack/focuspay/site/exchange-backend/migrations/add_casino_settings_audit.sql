-- Журнал изменений casino_settings. Повторный прогон безопасен.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_settings_audit (
    id          BIGSERIAL PRIMARY KEY,
    batch_id    UUID NOT NULL,
    key         TEXT NOT NULL,
    old_value   JSONB,
    new_value   JSONB NOT NULL,
    changed_by  TEXT NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_casino_settings_audit_changed_at
    ON casino_settings_audit (changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_settings_audit_batch_id
    ON casino_settings_audit (batch_id);
CREATE INDEX IF NOT EXISTS idx_casino_settings_audit_key
    ON casino_settings_audit (key);
CREATE INDEX IF NOT EXISTS idx_casino_settings_audit_changed_by
    ON casino_settings_audit (changed_by);

COMMENT ON TABLE casino_settings_audit IS 'Аудит PATCH /casino/settings: одна строка на изменённый ключ, общий batch_id на сохранение';

COMMIT;

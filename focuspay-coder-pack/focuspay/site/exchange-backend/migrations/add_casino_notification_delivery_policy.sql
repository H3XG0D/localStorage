BEGIN;

ALTER TABLE casino_notification_outbox
    ADD COLUMN IF NOT EXISTS last_error_kind VARCHAR(32);

ALTER TABLE casino_v2_notification_outbox
    ADD COLUMN IF NOT EXISTS last_error_kind VARCHAR(32);

UPDATE casino_notification_outbox
SET last_error_kind = 'dm_unavailable'
WHERE last_error_kind IS NULL AND (
    lower(COALESCE(last_error, '')) LIKE '%bot was blocked%'
    OR lower(COALESCE(last_error, '')) LIKE '%chat not found%'
    OR lower(COALESCE(last_error, '')) LIKE '%can''t initiate conversation%'
    OR lower(COALESCE(last_error, '')) LIKE '%user is deactivated%'
);

UPDATE casino_v2_notification_outbox
SET last_error_kind = 'dm_unavailable'
WHERE last_error_kind IS NULL AND (
    lower(COALESCE(last_error, '')) LIKE '%bot was blocked%'
    OR lower(COALESCE(last_error, '')) LIKE '%chat not found%'
    OR lower(COALESCE(last_error, '')) LIKE '%can''t initiate conversation%'
    OR lower(COALESCE(last_error, '')) LIKE '%user is deactivated%'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'casino_notification_outbox_error_kind_check'
          AND conrelid = 'casino_notification_outbox'::regclass
    ) THEN
        ALTER TABLE casino_notification_outbox
            ADD CONSTRAINT casino_notification_outbox_error_kind_check
            CHECK (last_error_kind IS NULL OR last_error_kind IN ('dm_unavailable','rate_limited','temporary'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'casino_v2_notification_outbox_error_kind_check'
          AND conrelid = 'casino_v2_notification_outbox'::regclass
    ) THEN
        ALTER TABLE casino_v2_notification_outbox
            ADD CONSTRAINT casino_v2_notification_outbox_error_kind_check
            CHECK (last_error_kind IS NULL OR last_error_kind IN ('dm_unavailable','rate_limited','temporary'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_casino_outbox_resume_dm
    ON casino_notification_outbox (recipient_id, id DESC)
    WHERE status IN ('pending','dead') AND last_error_kind = 'dm_unavailable';

CREATE INDEX IF NOT EXISTS idx_casino_v2_outbox_resume_dm
    ON casino_v2_notification_outbox (recipient_id, id DESC)
    WHERE status IN ('pending','dead') AND last_error_kind = 'dm_unavailable';

COMMIT;

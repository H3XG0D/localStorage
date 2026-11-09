BEGIN;

-- Group board jobs are delivered through the game chat and must never be
-- resumed as personal DM notifications, even for the creator's recipient id.
ALTER TABLE casino_v2_notification_outbox
    ADD CONSTRAINT casino_v2_notification_outbox_personal_resume_check
    CHECK (last_error_kind IS DISTINCT FROM 'dm_unavailable' OR event_type NOT IN ('public_settled', 'public_cancelled'))
    NOT VALID;

COMMIT;

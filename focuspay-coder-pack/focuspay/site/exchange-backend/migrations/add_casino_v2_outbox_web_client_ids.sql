-- Password-web accounts use negative client_user_id. Outbox still required > 0,
-- so V2 settle INSERT failed and the closer rolled back the card deal.
BEGIN;

ALTER TABLE casino_v2_notification_outbox
    DROP CONSTRAINT IF EXISTS casino_v2_notification_outbox_recipient_id_check;
ALTER TABLE casino_v2_notification_outbox
    ADD CONSTRAINT casino_v2_notification_outbox_recipient_id_check
    CHECK (recipient_id <> 0);

COMMIT;

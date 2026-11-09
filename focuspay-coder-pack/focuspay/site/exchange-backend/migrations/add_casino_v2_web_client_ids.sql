-- Password-web accounts use negative client_user_id. Zero is never a user.
-- V2 tables were created for Telegram ids only (CHECK > 0), so site create 500'd.
BEGIN;

ALTER TABLE casino_v2_tables
    DROP CONSTRAINT IF EXISTS casino_v2_tables_creator_id_check;
ALTER TABLE casino_v2_tables
    ADD CONSTRAINT casino_v2_tables_creator_id_check CHECK (creator_id <> 0);

ALTER TABLE casino_v2_table_seats
    DROP CONSTRAINT IF EXISTS casino_v2_table_seats_telegram_id_check;
ALTER TABLE casino_v2_table_seats
    ADD CONSTRAINT casino_v2_table_seats_telegram_id_check
    CHECK (telegram_id IS NULL OR telegram_id <> 0);

COMMIT;

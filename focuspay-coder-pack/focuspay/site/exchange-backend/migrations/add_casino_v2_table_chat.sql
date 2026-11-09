-- Bind V2 tables to the confirmed game chat so rolls can be accepted there.
BEGIN;

ALTER TABLE casino_v2_tables
    ADD COLUMN IF NOT EXISTS game_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS game_chat_binding_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_casino_v2_tables_game_chat
    ON casino_v2_tables(game_chat_id)
    WHERE game_chat_id IS NOT NULL;

COMMENT ON COLUMN casino_v2_tables.game_chat_id IS 'Telegram chat where the table card is published and rolls are accepted.';
COMMENT ON COLUMN casino_v2_tables.game_chat_binding_id IS 'Optional casino_game_chat_bindings.id used when the table was created.';

COMMIT;

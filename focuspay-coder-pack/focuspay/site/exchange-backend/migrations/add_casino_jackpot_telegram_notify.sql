-- Telegram origin chat for jackpot stakes. Site-only bets keep NULL.
-- Apply after add_casino_jackpot.sql. Repeat is a no-op.
BEGIN;

ALTER TABLE casino_jackpot_bets
    ADD COLUMN IF NOT EXISTS notify_chat_id BIGINT;

COMMENT ON COLUMN casino_jackpot_bets.notify_chat_id IS
    'Telegram chat to notify when this jackpot round settles; NULL for site-only stakes.';

COMMIT;

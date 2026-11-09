-- Panel hot-wallet send: commission row without a Telegram message.
-- Mirror: site/exchange-backend/migrations/add_swap_commission_panel_send.sql
-- Telegram /c inserts stay unchanged (chat_id + message_id).

ALTER TABLE swap_commission_entries
    ALTER COLUMN chat_id DROP NOT NULL,
    ALTER COLUMN message_id DROP NOT NULL;

ALTER TABLE swap_commission_entries
    ADD COLUMN IF NOT EXISTS operator_id INT,
    ADD COLUMN IF NOT EXISTS send_request_id TEXT,
    ADD COLUMN IF NOT EXISTS dest_address TEXT;

-- NULLs in the telegram unique index stay distinct, so panel rows need their own key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_swap_commission_send_request
    ON swap_commission_entries (send_request_id);

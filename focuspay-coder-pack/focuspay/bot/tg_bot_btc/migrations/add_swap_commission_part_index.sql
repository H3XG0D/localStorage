-- Несколько валют в одном сообщении (10trx + 2usdt + …).
ALTER TABLE swap_commission_entries
    ADD COLUMN IF NOT EXISTS part_index INT NOT NULL DEFAULT 0;

ALTER TABLE swap_commission_entries
    DROP CONSTRAINT IF EXISTS swap_commission_entries_chat_id_message_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_swap_commission_msg_part
    ON swap_commission_entries (chat_id, message_id, part_index);

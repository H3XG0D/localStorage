-- Эскалация чата внештатника в TG при отсутствии ответа оператора.
ALTER TABLE web_chat_threads
    ADD COLUMN IF NOT EXISTS chat_escalation_msg_id BIGINT,
    ADD COLUMN IF NOT EXISTS chat_escalated_at TIMESTAMPTZ;

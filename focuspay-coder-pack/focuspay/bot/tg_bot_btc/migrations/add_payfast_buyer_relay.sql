-- Якорь /msg: какое сообщение бота в личке покупателя отвечает в какой чат Payfast.
-- В чат группы пишется только псевдоним, buyer_user_id наружу не уходит.

CREATE TABLE IF NOT EXISTS payfast_buyer_relay (
    id BIGSERIAL PRIMARY KEY,
    order_id TEXT NOT NULL,
    buyer_user_id BIGINT NOT NULL,
    buyer_message_id BIGINT NOT NULL,
    group_chat_id BIGINT NOT NULL,
    group_message_id BIGINT NOT NULL,
    message_thread_id BIGINT,
    sender_tg_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS payfast_buyer_relay_buyer_msg_uidx
    ON payfast_buyer_relay (buyer_user_id, buyer_message_id);

GRANT ALL PRIVILEGES ON TABLE payfast_buyer_relay TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE payfast_buyer_relay_id_seq TO exchange_bot;

COMMENT ON TABLE payfast_buyer_relay IS
    'Мост /msg Payfast ↔ личка покупателя. В группу уходит копия без профиля.';

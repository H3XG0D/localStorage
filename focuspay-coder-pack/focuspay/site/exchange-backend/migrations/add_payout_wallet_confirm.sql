-- Клиент подтверждает адрес перед автовыплатой покупки BTC/LTC.
-- Пока статус не confirmed, воркер не создаёт payout_requests и не зовёт подписанта.

CREATE TABLE IF NOT EXISTS payout_wallet_confirms (
    order_id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    coin TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'awaiting_address', 'confirmed')),
    asked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    telegram_chat_id BIGINT,
    telegram_message_id BIGINT
);

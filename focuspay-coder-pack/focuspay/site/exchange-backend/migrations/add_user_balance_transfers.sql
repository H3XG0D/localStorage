-- Переводы между людьми с баланса FocusPay. Комиссия остаётся у проекта:
-- отправитель списывается на amount_rub, получатель получает net_rub.
CREATE TABLE IF NOT EXISTS user_balance_transfers (
    id              BIGSERIAL PRIMARY KEY,
    sender_user_id  BIGINT NOT NULL,
    recipient_user_id BIGINT NOT NULL,
    amount_rub      NUMERIC(14, 2) NOT NULL,
    fee_rub         NUMERIC(14, 2) NOT NULL,
    net_rub         NUMERIC(14, 2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (sender_user_id <> recipient_user_id),
    CHECK (amount_rub >= 100),
    CHECK (fee_rub >= 0),
    CHECK (net_rub > 0),
    CHECK (amount_rub = fee_rub + net_rub)
);

CREATE INDEX IF NOT EXISTS idx_user_balance_transfers_sender
    ON user_balance_transfers (sender_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_balance_transfers_recipient
    ON user_balance_transfers (recipient_user_id, created_at DESC);

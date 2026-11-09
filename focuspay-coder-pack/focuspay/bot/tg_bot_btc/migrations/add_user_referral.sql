-- Реферальная программа обычных пользователей (5% от прибыли сервиса).
ALTER TABLE bot_users
ADD COLUMN IF NOT EXISTS ref_token VARCHAR(32) UNIQUE;

CREATE INDEX IF NOT EXISTS idx_bot_users_ref_token ON bot_users (ref_token)
WHERE ref_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_referral_attributions (
    user_id           BIGINT PRIMARY KEY,
    referrer_user_id  BIGINT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_referral_attr_referrer
    ON user_referral_attributions (referrer_user_id);

CREATE TABLE IF NOT EXISTS user_referral_ledger (
    id                BIGSERIAL PRIMARY KEY,
    referrer_user_id  BIGINT NOT NULL,
    type              VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'payout', 'adjustment')),
    amount_rub        NUMERIC(14, 2) NOT NULL,
    order_id          VARCHAR(64) UNIQUE,
    withdrawal_id     INT,
    note              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_referral_ledger_referrer
    ON user_referral_ledger (referrer_user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_referral_withdrawals (
    id                SERIAL PRIMARY KEY,
    referrer_user_id  BIGINT NOT NULL,
    amount_rub        NUMERIC(14, 2) NOT NULL,
    method            VARCHAR(10) NOT NULL CHECK (method IN ('card', 'crypto')),
    requisites        TEXT NOT NULL,
    crypto            VARCHAR(20),
    network           VARCHAR(20),
    status            VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'rejected', 'canceled')),
    admin_message_id  BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_referral_wd_referrer
    ON user_referral_withdrawals (referrer_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_referral_wd_pending
    ON user_referral_withdrawals (status)
WHERE status = 'pending';

COMMENT ON TABLE user_referral_attributions IS 'Первый переход по uref_ ссылке';
COMMENT ON TABLE user_referral_ledger IS 'Начисления и выплаты рефереру';
COMMENT ON TABLE user_referral_withdrawals IS 'Заявки на вывод реферального баланса';

GRANT ALL PRIVILEGES ON TABLE user_referral_attributions TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE user_referral_ledger TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE user_referral_withdrawals TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE user_referral_ledger_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE user_referral_withdrawals_id_seq TO exchange_bot;

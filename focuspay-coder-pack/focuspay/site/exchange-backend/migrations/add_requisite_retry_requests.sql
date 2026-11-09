-- Черновик повторного запроса реквизитов. Это не заявка: в orders её нет.
-- Окно 30 минут с первого отказа, повтор не чаще раза в 5 минут.

CREATE TABLE IF NOT EXISTS requisite_retry_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    fiat_amount NUMERIC(14, 2) NOT NULL,
    crypto TEXT NOT NULL,
    network TEXT,
    wallet TEXT NOT NULL,
    sub_token TEXT NOT NULL,
    rate NUMERIC(20, 8),
    crypto_amount NUMERIC(24, 12),
    amount_currency TEXT,
    order_source TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
    closed_at TIMESTAMPTZ,
    order_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_requisite_retry_open_user
    ON requisite_retry_requests (user_id)
    WHERE status = 'open';

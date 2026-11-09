-- Split-платежи, OPERATOR_PENDING, кешбэк покупателя
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ADD CONSTRAINT orders_status_check CHECK (
    status IN (
        'CREATED', 'PENDING', 'COMPLETED', 'PAID', 'FAILED',
        'CANCELED', 'EXPIRED', 'DISPUTE', 'AWAITING_CHECK', 'OPERATOR_PENDING'
    )
);

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS group_id BIGINT,
    ADD COLUMN IF NOT EXISTS part_index INT,
    ADD COLUMN IF NOT EXISTS cashback_applied_rub NUMERIC(14, 2) NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_orders_group_id ON orders (group_id);

CREATE TABLE IF NOT EXISTS order_groups (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL,
    crypto          VARCHAR(30) NOT NULL,
    direction       VARCHAR(10) NOT NULL DEFAULT 'buy',
    total_fiat      NUMERIC(14, 2) NOT NULL,
    total_crypto    DOUBLE PRECISION NOT NULL,
    rate            DOUBLE PRECISION NOT NULL,
    requisites      TEXT NOT NULL,
    sub_token       VARCHAR(20),
    parts_count     INT NOT NULL DEFAULT 1,
    parts_paid      INT NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'canceled')),
    wallet_text     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_order_groups_user ON order_groups (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_cashback_ledger (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    type        VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit')),
    amount_rub  NUMERIC(14, 2) NOT NULL,
    order_id    VARCHAR(64) UNIQUE,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_cashback_user ON user_cashback_ledger (user_id, created_at DESC);

ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS use_cashback_on_next_order BOOLEAN NOT NULL DEFAULT FALSE;

GRANT ALL PRIVILEGES ON TABLE order_groups TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE user_cashback_ledger TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE order_groups_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE user_cashback_ledger_id_seq TO exchange_bot;

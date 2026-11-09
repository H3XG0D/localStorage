-- FocusPay SANDBOX schema for E1 VPN wallet only.
-- NOT production. No orders / Payfast / merchant tables.

CREATE TABLE IF NOT EXISTS bot_users (
    user_id    BIGINT PRIMARY KEY,
    username   VARCHAR(255),
    first_name VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    captcha_passed_at TIMESTAMPTZ,
    previous_username VARCHAR(255),
    username_changed_at TIMESTAMPTZ,
    account_review_status VARCHAR(32),
    account_review_reason TEXT,
    account_reviewed_at TIMESTAMPTZ,
    account_reviewed_by BIGINT,
    use_cashback_on_next_order BOOLEAN NOT NULL DEFAULT FALSE,
    ref_token VARCHAR(32) UNIQUE
);

CREATE TABLE IF NOT EXISTS user_cashback_ledger (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    type        VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'spend', 'adjustment', 'remainder_credit', 'hold')),
    amount_rub  NUMERIC(14, 2) NOT NULL,
    order_id    VARCHAR(64) UNIQUE,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sbx_cashback_user ON user_cashback_ledger (user_id);

CREATE TABLE IF NOT EXISTS user_referral_ledger (
    id                BIGSERIAL PRIMARY KEY,
    referrer_user_id  BIGINT NOT NULL,
    type              VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend')),
    amount_rub        NUMERIC(14, 2) NOT NULL,
    order_id          VARCHAR(64) UNIQUE,
    withdrawal_id     INT,
    note              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sbx_ref_ledger ON user_referral_ledger (referrer_user_id);

CREATE TABLE IF NOT EXISTS user_referral_withdrawals (
    id                SERIAL PRIMARY KEY,
    referrer_user_id  BIGINT NOT NULL,
    amount_rub        NUMERIC(14, 2) NOT NULL,
    method            VARCHAR(10) NOT NULL DEFAULT 'card',
    requisites        TEXT NOT NULL DEFAULT '',
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS promo_campaigns (
    id         BIGSERIAL PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    is_active  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS partner_accounts (
    id               BIGSERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    promo_campaign_id BIGINT REFERENCES promo_campaigns(id),
    is_active        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS partner_ledger (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL,
    type        VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend')),
    amount_rub  NUMERIC(14, 2) NOT NULL,
    order_id    VARCHAR(64) UNIQUE,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS partner_withdrawals (
    id          BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL,
    amount_rub  NUMERIC(14, 2) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS vpn_crypto_invoices (
    id               TEXT PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    vpn_order_id     TEXT NOT NULL UNIQUE,
    amount_rub       NUMERIC(12,2) NOT NULL CHECK (amount_rub > 0),
    asset            TEXT NOT NULL DEFAULT 'USDT-TRC20',
    amount_crypto    NUMERIC(24,8),
    pay_address      TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','paid','cancelled','expired')),
    held_rub         NUMERIC(12,2) NOT NULL DEFAULT 0,
    note             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at          TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed test buyer with 300₽ cashback (sandbox only).
INSERT INTO bot_users (user_id, username, first_name)
VALUES (900042, 'sandbox_buyer', 'Sandbox')
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO user_cashback_ledger (user_id, type, amount_rub, order_id, note)
VALUES (900042, 'accrual', 300.00, 'sandbox-seed-300', 'SANDBOX seed cashback')
ON CONFLICT (order_id) DO NOTHING;

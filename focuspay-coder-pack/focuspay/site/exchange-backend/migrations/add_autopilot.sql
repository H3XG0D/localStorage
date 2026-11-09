-- Autopilot: no-shift requisites, auto payouts, signer idempotency audit.

ALTER TABLE orders ADD COLUMN IF NOT EXISTS auto_served BOOLEAN NOT NULL DEFAULT FALSE;

-- Reserve/send states for auto withdrawals. The original CHECK allowed only
-- pending/paid/rejected/canceled, which would reject every autopilot write.
ALTER TABLE user_referral_withdrawals
    DROP CONSTRAINT IF EXISTS user_referral_withdrawals_status_check;
ALTER TABLE user_referral_withdrawals
    ADD CONSTRAINT user_referral_withdrawals_status_check
    CHECK (status IN ('pending', 'reserved', 'sending', 'paid', 'rejected', 'canceled', 'failed'));

ALTER TABLE user_referral_withdrawals ADD COLUMN IF NOT EXISTS auto_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE user_referral_withdrawals ADD COLUMN IF NOT EXISTS auto_reason TEXT;
ALTER TABLE user_referral_withdrawals ADD COLUMN IF NOT EXISTS auto_sent_at TIMESTAMPTZ;

-- One open balance withdrawal per user: must also cover the in-flight states,
-- otherwise a reserved row no longer blocks a second request at DB level.
DROP INDEX IF EXISTS idx_user_referral_wd_one_pending_balance;
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_referral_wd_one_open_balance
    ON user_referral_withdrawals (referrer_user_id)
    WHERE status IN ('pending', 'reserved', 'sending')
      AND COALESCE(source, 'balance') = 'balance';

CREATE INDEX IF NOT EXISTS idx_user_referral_wd_auto_queue
    ON user_referral_withdrawals (status, id)
    WHERE status IN ('reserved', 'sending');

ALTER TABLE bot_users ADD COLUMN IF NOT EXISTS auto_service_override BOOLEAN;

COMMENT ON COLUMN bot_users.auto_service_override IS
  'NULL=default rules; TRUE=force autopilot; FALSE=never autopilot';

CREATE TABLE IF NOT EXISTS payout_requests (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    user_id BIGINT,
    coin TEXT NOT NULL,
    address TEXT NOT NULL,
    -- NULL до отправки: курс фиксируется в момент отправки, а не резерва.
    amount_crypto NUMERIC(24, 12),
    amount_rub NUMERIC(14, 2),
    status TEXT NOT NULL DEFAULT 'queued',
    txid TEXT,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ
);

ALTER TABLE payout_requests ALTER COLUMN amount_crypto DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_payout_requests_status ON payout_requests (status, created_at);
CREATE INDEX IF NOT EXISTS idx_payout_requests_ref ON payout_requests (kind, ref_id);

CREATE TABLE IF NOT EXISTS auto_payout_audit (
    id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auto_payout_audit_request ON auto_payout_audit (request_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hot_wallet_balances (
    id BIGSERIAL PRIMARY KEY,
    coin TEXT NOT NULL,
    confirmed NUMERIC(24, 12) NOT NULL DEFAULT 0,
    unconfirmed NUMERIC(24, 12) NOT NULL DEFAULT 0,
    spendable NUMERIC(24, 12) NOT NULL DEFAULT 0,
    signer_ok BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Рублёвая оценка запаса: без неё порог auto_min_hot_balance_rub несравним.
ALTER TABLE hot_wallet_balances ADD COLUMN IF NOT EXISTS value_rub NUMERIC(18, 2) NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_hot_wallet_balances_coin ON hot_wallet_balances (coin, recorded_at DESC);

CREATE TABLE IF NOT EXISTS auto_service_gate_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    direction TEXT NOT NULL,
    fiat_amount BIGINT,
    decision TEXT NOT NULL,
    reason TEXT,
    shadow_mode BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auto_service_gate_log_created ON auto_service_gate_log (created_at DESC);

CREATE TABLE IF NOT EXISTS auto_recon_entries (
    id BIGSERIAL PRIMARY KEY,
    shift_id INT,
    order_id TEXT,
    withdrawal_id BIGINT,
    amount_rub NUMERIC(14, 2) NOT NULL,
    coin TEXT,
    txid TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auto_recon_shift ON auto_recon_entries (shift_id, created_at DESC);

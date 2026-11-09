-- Ускорение Bitcoin-выплаты: журнал списания и замены txid.
CREATE TABLE IF NOT EXISTS payout_fee_bumps (
    id                BIGSERIAL PRIMARY KEY,
    order_id          TEXT NOT NULL,
    user_id           BIGINT NOT NULL,
    old_txid          TEXT NOT NULL,
    new_txid          TEXT,
    coin              TEXT NOT NULL DEFAULT 'btc',
    fee_delta_crypto  NUMERIC(24, 12),
    fee_delta_rub     NUMERIC(14, 2),
    debited_rub       NUMERIC(14, 2) NOT NULL,
    charged_rub       NUMERIC(14, 2),
    refunded_rub      NUMERIC(14, 2) NOT NULL DEFAULT 0,
    cashback_rub      NUMERIC(14, 2) NOT NULL DEFAULT 0,
    referral_rub      NUMERIC(14, 2) NOT NULL DEFAULT 0,
    partner_rub       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fee_rate_btc_kvb  NUMERIC(24, 12),
    operator_id       BIGINT,
    status            TEXT NOT NULL,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('pending', 'sent', 'failed', 'unknown', 'asked', 'accepted')),
    CHECK (debited_rub >= 0),
    CHECK (refunded_rub >= 0)
);

-- Одна незакрытая попытка на заявку: повторное нажатие не списывает второй раз.
CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_fee_bumps_open
    ON payout_fee_bumps (order_id)
    WHERE status IN ('pending', 'unknown', 'asked');

-- Если таблица уже создана без вопроса оператору.
ALTER TABLE payout_fee_bumps ADD COLUMN IF NOT EXISTS operator_id BIGINT;
ALTER TABLE payout_fee_bumps DROP CONSTRAINT IF EXISTS payout_fee_bumps_status_check;
ALTER TABLE payout_fee_bumps ADD CONSTRAINT payout_fee_bumps_status_check
    CHECK (status IN ('pending', 'sent', 'failed', 'unknown', 'asked', 'accepted'));
DROP INDEX IF EXISTS ux_payout_fee_bumps_open;
CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_fee_bumps_open
    ON payout_fee_bumps (order_id)
    WHERE status IN ('pending', 'unknown', 'asked');

CREATE INDEX IF NOT EXISTS idx_payout_fee_bumps_user
    ON payout_fee_bumps (user_id, created_at DESC);

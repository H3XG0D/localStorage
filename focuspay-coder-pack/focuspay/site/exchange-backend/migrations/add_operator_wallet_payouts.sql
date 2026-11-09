-- Operator-recorded crypto wallet payouts (e.g. FocusLucky LTC prizes).
-- Mirror: tg_bot_btc/migrations/add_operator_wallet_payouts.sql

CREATE TABLE IF NOT EXISTS operator_wallet_payouts (
    id                      SERIAL PRIMARY KEY,
    recipient_name          VARCHAR(256) NOT NULL,
    user_id                 BIGINT,
    crypto                  VARCHAR(16) NOT NULL DEFAULT 'ltc',
    amount_rub              NUMERIC(14, 2) NOT NULL,
    wallet_address          TEXT NOT NULL,
    payout_tx_hash          TEXT NOT NULL,
    label                   TEXT,
    issued_by_operator_id   INT NOT NULL REFERENCES operator_accounts(id) ON DELETE RESTRICT,
    raffle_winner_id        INT REFERENCES raffle_winners(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operator_wallet_payouts_crypto_chk
        CHECK (crypto IN ('ltc', 'btc', 'usdt')),
    CONSTRAINT operator_wallet_payouts_amount_chk
        CHECK (amount_rub > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_wallet_payouts_tx_hash
    ON operator_wallet_payouts (payout_tx_hash);

CREATE INDEX IF NOT EXISTS idx_operator_wallet_payouts_created
    ON operator_wallet_payouts (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_wallet_payouts_issuer
    ON operator_wallet_payouts (issued_by_operator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_wallet_payouts_user
    ON operator_wallet_payouts (user_id)
    WHERE user_id IS NOT NULL;

ALTER TABLE raffle_winners
    ADD COLUMN IF NOT EXISTS payout_tx_hash TEXT,
    ADD COLUMN IF NOT EXISTS payout_wallet TEXT,
    ADD COLUMN IF NOT EXISTS paid_by_operator_id INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS operator_wallet_payout_id INT REFERENCES operator_wallet_payouts(id) ON DELETE SET NULL;

GRANT ALL PRIVILEGES ON TABLE operator_wallet_payouts TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_wallet_payouts_id_seq TO exchange_bot;

COMMENT ON TABLE operator_wallet_payouts IS
    'Crypto payouts recorded by operators (raffle prizes, manual transfers)';

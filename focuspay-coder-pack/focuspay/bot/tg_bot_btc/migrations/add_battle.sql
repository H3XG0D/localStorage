-- FocusPay Battle: rounds, bets, wallet hold tracking (schema parity with exchange)
-- Apply on exchange_bot database alongside exchange backend migrations.

CREATE TABLE IF NOT EXISTS battle_rounds (
    id            BIGSERIAL PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'open',
    red_total     NUMERIC(12, 2) NOT NULL DEFAULT 0,
    blue_total    NUMERIC(12, 2) NOT NULL DEFAULT 0,
    winner        TEXT,
    ends_at       TIMESTAMPTZ NOT NULL,
    resolved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS battle_bets (
    id            BIGSERIAL PRIMARY KEY,
    round_id      BIGINT NOT NULL REFERENCES battle_rounds(id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('red', 'blue')),
    amount_rub    NUMERIC(12, 2) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_id, user_id, side)
);

CREATE INDEX IF NOT EXISTS idx_battle_bets_round ON battle_bets (round_id);
CREATE INDEX IF NOT EXISTS idx_battle_bets_user ON battle_bets (user_id);
CREATE INDEX IF NOT EXISTS idx_battle_rounds_status ON battle_rounds (status);

CREATE TABLE IF NOT EXISTS battle_wallet_holds (
    id            BIGSERIAL PRIMARY KEY,
    round_id      BIGINT NOT NULL REFERENCES battle_rounds(id) ON DELETE CASCADE,
    user_id       BIGINT NOT NULL,
    order_ref     TEXT NOT NULL UNIQUE,
    amount_rub    NUMERIC(12, 2) NOT NULL,
    status        TEXT NOT NULL DEFAULT 'held',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_battle_wallet_holds_round_user
    ON battle_wallet_holds (round_id, user_id);

CREATE SEQUENCE IF NOT EXISTS battle_hold_ref_seq START 1;

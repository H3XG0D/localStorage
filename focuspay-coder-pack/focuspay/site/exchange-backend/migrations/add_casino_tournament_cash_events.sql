-- Tournament cash events: entry / rebuy fees (income) and prize / refund (expense).
-- Used by finance_pnl so rebuys and buy-ins reduce the owner's net tournament cost.

CREATE TABLE IF NOT EXISTS casino_tournament_cash_events (
    id BIGSERIAL PRIMARY KEY,
    tournament_id BIGINT NOT NULL REFERENCES casino_tournaments(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL CHECK (kind IN ('entry', 'rebuy', 'prize', 'refund')),
    amount_rub NUMERIC(18, 2) NOT NULL CHECK (amount_rub >= 0),
    order_ref VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT casino_tournament_cash_events_order_uq UNIQUE (order_ref)
);

CREATE INDEX IF NOT EXISTS idx_casino_tournament_cash_events_created
    ON casino_tournament_cash_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_tournament_cash_events_kind_day
    ON casino_tournament_cash_events (kind, created_at);
CREATE INDEX IF NOT EXISTS idx_casino_tournament_cash_events_tournament
    ON casino_tournament_cash_events (tournament_id, created_at DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT ALL PRIVILEGES ON TABLE casino_tournament_cash_events TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE casino_tournament_cash_events_id_seq TO exchange_bot;
    END IF;
END $$;

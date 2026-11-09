-- Лог выдачи USDT операторам (владелец, несколько раз за смену).
CREATE TABLE IF NOT EXISTS operator_usdt_issuances (
    id              SERIAL PRIMARY KEY,
    operator_id     INTEGER NOT NULL REFERENCES operator_accounts (id),
    shift_id        INTEGER REFERENCES operator_shifts (id),
    amount_usdt     NUMERIC(18, 8) NOT NULL CHECK (amount_usdt >= 0),
    recorded_by     INTEGER REFERENCES web_users (id),
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operator_usdt_iss_operator_time
    ON operator_usdt_issuances (operator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_usdt_iss_shift
    ON operator_usdt_issuances (shift_id, created_at DESC);

COMMENT ON TABLE operator_usdt_issuances IS
    'USDT выданные оператору владельцем во время смены (для чистой маржи)';

GRANT SELECT, INSERT ON operator_usdt_issuances TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_usdt_issuances_id_seq TO exchange_bot;

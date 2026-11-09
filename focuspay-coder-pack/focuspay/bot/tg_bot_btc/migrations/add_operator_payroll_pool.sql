-- Общий пул зарплаты операторов и заявки на вывод
CREATE TABLE IF NOT EXISTS operator_payout_requests (
    id                SERIAL PRIMARY KEY,
    operator_id       INT NOT NULL REFERENCES operator_accounts(id),
    amount_rub        NUMERIC(14, 2) NOT NULL,
    requisites        TEXT NOT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'rejected', 'canceled')),
    admin_message_id  BIGINT,
    processed_at      TIMESTAMPTZ,
    payout_note       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operator_payout_req_status
    ON operator_payout_requests (status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payout_one_pending
    ON operator_payout_requests (operator_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS operator_payroll_ledger (
    id                SERIAL PRIMARY KEY,
    type              VARCHAR(20) NOT NULL
        CHECK (type IN ('accrual', 'hold', 'payout', 'release')),
    amount_rub        NUMERIC(14, 2) NOT NULL,
    shift_id          INT REFERENCES operator_shifts(id),
    payout_request_id INT REFERENCES operator_payout_requests(id),
    operator_id       INT REFERENCES operator_accounts(id),
    note              TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_operator_payroll_accrual_shift
    ON operator_payroll_ledger (shift_id)
    WHERE type = 'accrual' AND shift_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_operator_payroll_created
    ON operator_payroll_ledger (created_at DESC);

GRANT ALL PRIVILEGES ON TABLE operator_payout_requests TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE operator_payroll_ledger TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_payout_requests_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_payroll_ledger_id_seq TO exchange_bot;

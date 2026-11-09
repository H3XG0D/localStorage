-- Смены операторов: фиксируют рабочие периоды для расчёта зарплаты.
CREATE TABLE IF NOT EXISTS operator_shifts (
    id          SERIAL PRIMARY KEY,
    operator_id INT NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ,
    note        TEXT
);

COMMENT ON TABLE operator_shifts IS
  'Смены оператора: прибыль считается только за заявки, созданные в дни смены.';

CREATE INDEX IF NOT EXISTS idx_operator_shifts_operator
    ON operator_shifts (operator_id);

CREATE INDEX IF NOT EXISTS idx_operator_shifts_active
    ON operator_shifts (operator_id)
    WHERE ended_at IS NULL;

GRANT SELECT, INSERT, UPDATE ON operator_shifts TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_shifts_id_seq TO exchange_bot;

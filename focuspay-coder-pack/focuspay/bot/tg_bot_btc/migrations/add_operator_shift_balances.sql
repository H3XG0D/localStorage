-- Балансы кошельков оператора на начало и конец смены.
-- Используется для расчёта сетевых комиссий (gas fees):
-- network_fees = (balance_start − sent_in_buy + recv_in_sell) − balance_end
CREATE TABLE IF NOT EXISTS operator_shift_balances (
    id             SERIAL PRIMARY KEY,
    shift_id       INT NOT NULL REFERENCES operator_shifts(id) ON DELETE CASCADE,
    crypto         VARCHAR(16) NOT NULL,
    balance_start  NUMERIC(20, 8),
    balance_end    NUMERIC(20, 8)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_op_shift_balances_shift_crypto
    ON operator_shift_balances (shift_id, crypto);

COMMENT ON TABLE operator_shift_balances IS
  'Балансы крипто-кошельков оператора на начало/конец смены; разность с ожидаемым = сетевые комиссии.';

GRANT SELECT, INSERT, UPDATE ON operator_shift_balances TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_shift_balances_id_seq TO exchange_bot;

-- Аккаунты операторов: ручная обработка заявок, подтверждение платежей.
CREATE TABLE IF NOT EXISTS operator_accounts (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) NOT NULL UNIQUE,
    display_name  VARCHAR(128),
    password_hash TEXT NOT NULL,
    percent       NUMERIC(6, 3) NOT NULL DEFAULT 10.0
                  CHECK (percent >= 0 AND percent <= 100),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE operator_accounts IS
  'Операторы: логин по username/пароль, % зарплаты от прибыли за дни их смен.';

CREATE INDEX IF NOT EXISTS idx_operator_accounts_active
    ON operator_accounts (is_active);

GRANT SELECT, INSERT, UPDATE, DELETE ON operator_accounts TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_accounts_id_seq TO exchange_bot;

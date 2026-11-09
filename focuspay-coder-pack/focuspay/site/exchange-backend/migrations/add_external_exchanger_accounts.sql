-- Личный кабинет внештатника: логин 1:1 с external_exchangers
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_external_exchanger_accounts.sql

CREATE TABLE IF NOT EXISTS external_exchanger_accounts (
    id                    SERIAL PRIMARY KEY,
    external_exchanger_id INT NOT NULL UNIQUE REFERENCES external_exchangers(id) ON DELETE CASCADE,
    username              VARCHAR(64) NOT NULL,
    password_hash         VARCHAR(255) NOT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_exch_accounts_username_lower
    ON external_exchanger_accounts (LOWER(username));

CREATE INDEX IF NOT EXISTS idx_ext_exch_accounts_exchanger
    ON external_exchanger_accounts (external_exchanger_id);

GRANT ALL PRIVILEGES ON TABLE external_exchanger_accounts TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE external_exchanger_accounts_id_seq TO exchange_bot;

COMMENT ON TABLE external_exchanger_accounts IS
    'Логин кабинета /exchanger (одна учётка на external_exchanger)';

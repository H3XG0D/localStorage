-- Адреса проекта, которые уже светились. Строки не удаляются:
-- смена текущего адреса только помечает предыдущий как сменённый.

CREATE TABLE IF NOT EXISTS project_wallet_addresses (
    id BIGSERIAL PRIMARY KEY,
    coin TEXT NOT NULL,
    address TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ,
    UNIQUE (coin, source, address)
);

CREATE INDEX IF NOT EXISTS idx_project_wallet_addresses_current
    ON project_wallet_addresses (coin, source)
    WHERE retired_at IS NULL;

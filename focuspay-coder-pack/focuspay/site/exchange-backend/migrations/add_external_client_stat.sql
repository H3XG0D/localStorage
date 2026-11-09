-- Сводка клиента магазина для /check и карточки оператора.
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_external_client_stat.sql

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS client_stat JSONB,
    ADD COLUMN IF NOT EXISTS client_stat_at TIMESTAMPTZ;

COMMENT ON COLUMN external_deals.client_stat IS
    'Сводка клиента магазина (paid_orders, conversion, turnover) без ПДн';
COMMENT ON COLUMN external_deals.client_stat_at IS
    'Когда магазин последний раз прислал client_stat по этой сделке';

CREATE TABLE IF NOT EXISTS external_client_stats (
    exchanger_id INTEGER NOT NULL REFERENCES external_exchangers(id) ON DELETE CASCADE,
    fingerprint  TEXT NOT NULL,
    payload      JSONB NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchanger_id, fingerprint)
);

COMMENT ON TABLE external_client_stats IS
    'Последняя сводка клиента магазина по fingerprint — подставляется в новые сделки';

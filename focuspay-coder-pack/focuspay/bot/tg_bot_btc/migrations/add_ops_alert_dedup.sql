-- Дедуп повторяющихся ops-алертов по заявке (вебхук Payfast ретраит запрос,
-- иначе одно и то же уведомление уходит в ops-группу много раз).

CREATE TABLE IF NOT EXISTS ops_alert_dedup (
    order_id VARCHAR(64) NOT NULL,
    kind VARCHAR(64) NOT NULL,
    alerted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, kind)
);

GRANT ALL PRIVILEGES ON TABLE ops_alert_dedup TO exchange_bot;

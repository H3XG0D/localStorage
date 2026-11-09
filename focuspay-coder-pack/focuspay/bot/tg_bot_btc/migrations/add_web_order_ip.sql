-- IP-логирование веб-заявок и привязка заявки к IP клиента.
ALTER TABLE orders
ADD COLUMN IF NOT EXISTS client_ip INET;

CREATE TABLE IF NOT EXISTS web_order_ip_log (
    id          BIGSERIAL PRIMARY KEY,
    ip_address  INET NOT NULL,
    event       VARCHAR(40) NOT NULL,
    order_id    VARCHAR(32),
    user_id     BIGINT,
    user_agent  TEXT,
    extra       JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_web_order_ip_log_ip_time
    ON web_order_ip_log (ip_address, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_orders_client_ip
    ON orders (client_ip)
    WHERE client_ip IS NOT NULL;

COMMENT ON TABLE web_order_ip_log IS 'События создания заявок с сайта по IP';
COMMENT ON COLUMN orders.client_ip IS 'IP клиента при создании заявки с сайта';

GRANT ALL PRIVILEGES ON TABLE web_order_ip_log TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_order_ip_log_id_seq TO exchange_bot;

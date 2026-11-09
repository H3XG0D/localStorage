-- Журнал реквизитов, выданных оператору вручную до создания заявки.
-- Заявку оператор заводит в /ops/create и указывает там код тикета — только так
-- выдача связывается с orders и попадает в кешбек/рефералку/лотерею.

CREATE TABLE IF NOT EXISTS manual_requisite_tickets (
    code           VARCHAR(16) PRIMARY KEY,
    source         VARCHAR(16) NOT NULL,
    sub_token      VARCHAR(20) NOT NULL,
    amount_rub     NUMERIC(14, 2) NOT NULL,
    bill           JSONB,
    requisite_id   INT,
    merchant_order_id TEXT,
    operator_tg_id BIGINT,
    order_id       VARCHAR(64),
    status         VARCHAR(12) NOT NULL DEFAULT 'ISSUED',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT manual_requisite_tickets_source_chk
        CHECK (source IN ('rail', 'merchant', 'reki_bot')),
    CONSTRAINT manual_requisite_tickets_status_chk
        CHECK (status IN ('ISSUED', 'LINKED', 'CANCELED'))
);

CREATE INDEX IF NOT EXISTS manual_requisite_tickets_status_idx
    ON manual_requisite_tickets (status, created_at);

CREATE INDEX IF NOT EXISTS manual_requisite_tickets_order_idx
    ON manual_requisite_tickets (order_id)
    WHERE order_id IS NOT NULL;

GRANT ALL PRIVILEGES ON TABLE manual_requisite_tickets TO exchange_bot;

COMMENT ON TABLE manual_requisite_tickets IS
    'Ручные выдачи реквизита оператору: код MAN-xxxx, источник и привязка к заявке.';
COMMENT ON COLUMN manual_requisite_tickets.source IS
    'rail — карта оператора, merchant — счёт мерчанта, reki_bot — сторонний бот.';
COMMENT ON COLUMN manual_requisite_tickets.order_id IS
    'Заполняется, когда оператор указал код тикета при создании заявки.';

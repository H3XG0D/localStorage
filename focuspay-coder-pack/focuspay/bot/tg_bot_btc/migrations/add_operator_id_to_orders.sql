-- Привязка заявки к оператору, который её создал / обработал.
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS operator_id INT REFERENCES operator_accounts(id);

CREATE INDEX IF NOT EXISTS idx_orders_operator_id
    ON orders (operator_id)
    WHERE operator_id IS NOT NULL;

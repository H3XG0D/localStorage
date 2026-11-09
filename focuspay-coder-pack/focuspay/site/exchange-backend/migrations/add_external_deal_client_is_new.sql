-- Тип конечного клиента на сделке: новый / повторный (выбор при создании).
ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS client_is_new BOOLEAN NOT NULL DEFAULT TRUE;

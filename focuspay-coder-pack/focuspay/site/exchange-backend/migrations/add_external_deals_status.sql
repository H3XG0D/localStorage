-- Добавить статус к внештатным сделкам
-- Существующие записи получают 'confirmed' — они уже начислены в ledger

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'confirmed'
        CHECK (status IN ('awaiting_receipt', 'confirmed', 'cancelled'));

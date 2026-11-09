-- Тип чека для сделок кабинета: 2=PDF, 3=видео (через оператора)
ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS required_receipt_type SMALLINT DEFAULT 2;

UPDATE external_deals SET required_receipt_type = 2 WHERE required_receipt_type IS NULL;

COMMENT ON COLUMN external_deals.required_receipt_type IS '2=PDF, 3=видео через оператора';

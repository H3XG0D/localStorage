-- Имя файла чека/видео, загруженного клиентом (для просмотра в админке).
ALTER TABLE orders
ADD COLUMN IF NOT EXISTS receipt_file TEXT;

COMMENT ON COLUMN orders.receipt_file IS 'Имя файла чека/видео в каталоге receipts (последний загруженный клиентом)';

GRANT ALL PRIVILEGES ON TABLE orders TO exchange_bot;

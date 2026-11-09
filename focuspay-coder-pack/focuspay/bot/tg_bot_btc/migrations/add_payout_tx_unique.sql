-- Уникальность hash выплаты: один on-chain tx не может оплачивать две заявки.
-- Частичный индекс — только для непустых значений (NULL не конфликтуют).
-- Если упадёт на дубликатах — это сигнал о ранее задвоенной выплате, разобрать вручную.
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_payout_tx_hash_unique
    ON orders (payout_tx_hash)
    WHERE payout_tx_hash IS NOT NULL;

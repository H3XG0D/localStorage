-- Кто выдал промокод (оператор из кабинета /ops)
ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS issued_by_operator_id INT
    REFERENCES operator_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_promo_campaigns_issued_by_operator
    ON promo_campaigns (issued_by_operator_id);

COMMENT ON COLUMN promo_campaigns.issued_by_operator_id IS
    'Оператор, создавший подарочный промокод; NULL — создан админом';

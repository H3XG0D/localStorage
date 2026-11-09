-- Прямая выдача скидки на обмен оператором (без промокода).
-- Mirror: exchange/backend/migrations/add_exchange_discount_operator_grant.sql
ALTER TABLE user_exchange_discounts
    ADD COLUMN IF NOT EXISTS issued_by_operator_id INT
    REFERENCES operator_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_user_exchange_discounts_issued_by_operator
    ON user_exchange_discounts (issued_by_operator_id)
    WHERE issued_by_operator_id IS NOT NULL;

COMMENT ON COLUMN user_exchange_discounts.issued_by_operator_id IS
    'Оператор, выдавший скидку напрямую; NULL — активирована по промокоду';

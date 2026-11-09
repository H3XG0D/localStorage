-- Операторские промокоды: created_by = web_users, issued_by_operator_id = operator_accounts
ALTER TABLE promo_campaigns
    ALTER COLUMN created_by DROP NOT NULL;

COMMENT ON COLUMN promo_campaigns.created_by IS
    'web_users.id админа; NULL если код создан оператором (см. issued_by_operator_id)';

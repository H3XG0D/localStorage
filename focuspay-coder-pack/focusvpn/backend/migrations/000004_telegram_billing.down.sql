DROP TABLE IF EXISTS billing_events;
DROP INDEX IF EXISTS uq_users_telegram_id;
ALTER TABLE users DROP COLUMN IF EXISTS telegram_id;
DELETE FROM plans WHERE code = 'week';

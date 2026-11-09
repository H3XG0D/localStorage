-- Админ-карточка вывода внештатника в Telegram + чек выплаты
ALTER TABLE external_payouts
    ADD COLUMN IF NOT EXISTS admin_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS receipt_file TEXT;

COMMENT ON COLUMN external_payouts.admin_message_id IS
    'message_id карточки заявки в reports/ops группе';
COMMENT ON COLUMN external_payouts.receipt_file IS
    'Файл чека выплаты, прикреплённый админом из Telegram';

-- Отклонение из админки/бота использует status=rejected
ALTER TABLE external_payouts DROP CONSTRAINT IF EXISTS external_payouts_status_check;
ALTER TABLE external_payouts
    ADD CONSTRAINT external_payouts_status_check
    CHECK (status IN ('paid', 'pending', 'canceled', 'rejected'));

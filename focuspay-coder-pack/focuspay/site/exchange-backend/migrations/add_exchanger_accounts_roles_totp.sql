-- Кабинет внештатника: несколько логинов на магазин (owner/clerk) и 2FA.
-- Хозяин: реквизиты, чек, баланс, выводы, настройки. Кассир: всё кроме выводов.
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_exchanger_accounts_roles_totp.sql

ALTER TABLE external_exchanger_accounts
    DROP CONSTRAINT IF EXISTS external_exchanger_accounts_external_exchanger_id_key;

ALTER TABLE external_exchanger_accounts
    ADD COLUMN IF NOT EXISTS role         VARCHAR(16) NOT NULL DEFAULT 'owner',
    ADD COLUMN IF NOT EXISTS label        VARCHAR(128),
    ADD COLUMN IF NOT EXISTS totp_secret  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_by_account_id INT;

ALTER TABLE external_exchanger_accounts
    DROP CONSTRAINT IF EXISTS external_exchanger_accounts_role_check;
ALTER TABLE external_exchanger_accounts
    ADD CONSTRAINT external_exchanger_accounts_role_check
    CHECK (role IN ('owner', 'clerk'));

-- Хозяин ровно один на магазин, кассиров сколько нужно.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ext_exch_accounts_single_owner
    ON external_exchanger_accounts (external_exchanger_id)
    WHERE role = 'owner';

COMMENT ON COLUMN external_exchanger_accounts.role IS
    'owner — хозяин магазина (выводы, настройки), clerk — кассир (реквизиты и чеки)';
COMMENT ON COLUMN external_exchanger_accounts.label IS
    'Пометка логина для хозяина: имя кассира, смена';
COMMENT ON TABLE external_exchanger_accounts IS
    'Логины кабинета /exchanger: один owner и любое число clerk на external_exchanger';

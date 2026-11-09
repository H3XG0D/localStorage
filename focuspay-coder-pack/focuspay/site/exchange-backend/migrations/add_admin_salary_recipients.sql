-- Ежедневная зарплата админ-персонала (начисление на partner_ledger)

CREATE TABLE IF NOT EXISTS admin_salary_recipients (
    id                 SERIAL PRIMARY KEY,
    partner_account_id INT NOT NULL UNIQUE REFERENCES partner_accounts(id) ON DELETE CASCADE,
    label              VARCHAR(128) NOT NULL,
    daily_salary_rub   NUMERIC(12, 2) NOT NULL DEFAULT 1000
        CHECK (daily_salary_rub >= 0),
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admin_salary_accruals (
    id                 SERIAL PRIMARY KEY,
    recipient_id       INT NOT NULL REFERENCES admin_salary_recipients(id) ON DELETE CASCADE,
    accrual_date       DATE NOT NULL,
    amount_rub         NUMERIC(12, 2) NOT NULL,
    partner_ledger_id  INT REFERENCES partner_ledger(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recipient_id, accrual_date)
);

CREATE INDEX IF NOT EXISTS idx_admin_salary_accruals_date
    ON admin_salary_accruals (accrual_date DESC);

COMMENT ON TABLE admin_salary_recipients IS 'Админ-персонал с фиксированной дневной зарплатой';
COMMENT ON TABLE admin_salary_accruals IS 'История дневных начислений зарплаты';

-- legendaryira — админка, 1000 ₽/день (7000 ₽/нед)
INSERT INTO admin_salary_recipients (partner_account_id, label, daily_salary_rub, is_active)
SELECT pa.id, COALESCE(pa.username, pa.display_name, 'admin'), 1000, TRUE
FROM partner_accounts pa
WHERE LOWER(pa.username) = 'legendaryira'
  AND NOT EXISTS (
      SELECT 1 FROM admin_salary_recipients r WHERE r.partner_account_id = pa.id
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON admin_salary_recipients TO exchange_bot;
GRANT SELECT, INSERT, UPDATE, DELETE ON admin_salary_accruals TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE admin_salary_recipients_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE admin_salary_accruals_id_seq TO exchange_bot;

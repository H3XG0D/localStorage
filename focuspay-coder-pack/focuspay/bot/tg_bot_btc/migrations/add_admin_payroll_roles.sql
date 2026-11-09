-- Доли зарплат/выплат сотрудникам: % от прибыли после кешбэка, рефералов и партнёров.

CREATE TABLE IF NOT EXISTS admin_payroll_roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128) NOT NULL,
    percent     NUMERIC(6, 3) NOT NULL CHECK (percent >= 0 AND percent <= 100),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE admin_payroll_roles IS
  'Доля от чистой прибыли после начислений (кешбэк/реф/партнёр). Несколько ролей — % считаются от одной базы.';

CREATE INDEX IF NOT EXISTS idx_admin_payroll_roles_active
    ON admin_payroll_roles (is_active, sort_order);

INSERT INTO admin_payroll_roles (name, percent, sort_order)
SELECT 'Админка', 10.0, 1
WHERE NOT EXISTS (SELECT 1 FROM admin_payroll_roles WHERE name = 'Админка');

GRANT SELECT, INSERT, UPDATE, DELETE ON admin_payroll_roles TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE admin_payroll_roles_id_seq TO exchange_bot;

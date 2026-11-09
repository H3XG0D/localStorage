-- Operator-supplied payout requisites (чужая карта/СБП под выплату) + автоподбор чеков.
-- Apply: psql ... -f migrations/add_payout_requisites.sql
-- Rollback:
--   DROP TABLE IF EXISTS payout_requisite_plans;
--   DROP TABLE IF EXISTS payout_requisite_allocations;
--   DROP TABLE IF EXISTS operator_payout_requisites;

CREATE TABLE IF NOT EXISTS operator_payout_requisites (
    id                  SERIAL PRIMARY KEY,
    operator_id         INT NOT NULL REFERENCES operator_accounts(id) ON DELETE RESTRICT,
    label               VARCHAR(128),
    -- payout: с карты уходят рубли клиентам по SELL.
    -- payin:  на карту приходят рубли клиентов по BUY вместо провайдера карт.
    direction           VARCHAR(8) NOT NULL DEFAULT 'payout',
    method              VARCHAR(8) NOT NULL,
    requisites          TEXT NOT NULL,
    bank                VARCHAR(128),
    holder_name         VARCHAR(256),
    amount_rub          NUMERIC(14, 2) NOT NULL,
    -- Стоимость реквизита: +3 = доплачиваем 3%, 0 = бесплатно, -3 = получаем 3%.
    cost_pct            NUMERIC(6, 3) NOT NULL DEFAULT 0,
    -- Чем рассчитываемся с реквизитчиком за проход.
    crypto              VARCHAR(8) NOT NULL DEFAULT 'usdt',
    paid_rub            NUMERIC(14, 2) NOT NULL DEFAULT 0,
    max_checks          SMALLINT NOT NULL DEFAULT 3,
    doliv_limit_rub     INTEGER NOT NULL DEFAULT 2000,
    -- Payin create always writes QUEUED; payout create writes OPEN.
    -- DEFAULT is QUEUED so an omitted status cannot silently enter the buyer pool.
    status              VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
    deadline_at         TIMESTAMPTZ NOT NULL,
    closed_at           TIMESTAMPTZ,
    close_note          TEXT,
    confirmed_at        TIMESTAMPTZ,
    confirmed_by        INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    -- SELL whose client card is offered to BUY payers (triangle). Live unique
    -- is created below so a closed/canceled card can be retried.
    source_sell_order_id VARCHAR(64),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT operator_payout_requisites_method_chk
        CHECK (method IN ('card', 'sbp')),
    CONSTRAINT operator_payout_requisites_status_chk
        CHECK (status IN ('QUEUED', 'OPEN', 'RESERVED', 'PARTIAL', 'CLOSED', 'EXPIRED', 'CANCELED')),
    CONSTRAINT operator_payout_requisites_amount_chk
        CHECK (amount_rub > 0),
    CONSTRAINT operator_payout_requisites_cost_chk
        CHECK (cost_pct >= -100 AND cost_pct <= 100),
    CONSTRAINT operator_payout_requisites_paid_chk
        CHECK (paid_rub >= 0 AND paid_rub <= amount_rub),
    CONSTRAINT operator_payout_requisites_checks_chk
        CHECK (max_checks >= 1 AND max_checks <= 5),
    CONSTRAINT operator_payout_requisites_doliv_chk
        CHECK (doliv_limit_rub >= 0),
    CONSTRAINT operator_payout_requisites_crypto_chk
        CHECK (crypto IN ('usdt', 'btc', 'trx', 'ltc')),
    CONSTRAINT operator_payout_requisites_direction_chk
        CHECK (direction IN ('payout', 'payin')),
    CONSTRAINT operator_payout_requisites_payin_pool_confirm_chk
        CHECK (
            direction <> 'payin'
            OR status NOT IN ('OPEN', 'RESERVED', 'PARTIAL')
            OR confirmed_at IS NOT NULL
        )
);

-- Для стендов, где таблица уже создана предыдущей версией миграции.
ALTER TABLE operator_payout_requisites
    ADD COLUMN IF NOT EXISTS crypto VARCHAR(8) NOT NULL DEFAULT 'usdt',
    ADD COLUMN IF NOT EXISTS direction VARCHAR(8) NOT NULL DEFAULT 'payout',
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_by INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_sell_order_id VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_req_source_sell_live
    ON operator_payout_requisites (source_sell_order_id)
    WHERE source_sell_order_id IS NOT NULL
      AND status IN ('QUEUED', 'OPEN', 'RESERVED', 'PARTIAL');

DO $$
BEGIN
    ALTER TABLE operator_payout_requisites
        ADD CONSTRAINT operator_payout_requisites_crypto_chk
        CHECK (crypto IN ('usdt', 'btc', 'trx', 'ltc'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE operator_payout_requisites
        ADD CONSTRAINT operator_payout_requisites_direction_chk
        CHECK (direction IN ('payout', 'payin'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE operator_payout_requisites
        DROP CONSTRAINT IF EXISTS operator_payout_requisites_status_chk;
    ALTER TABLE operator_payout_requisites
        ADD CONSTRAINT operator_payout_requisites_status_chk
        CHECK (status IN (
            'QUEUED', 'OPEN', 'RESERVED', 'PARTIAL', 'CLOSED', 'EXPIRED', 'CANCELED'
        ));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_payout_requisites_open
    ON operator_payout_requisites (status, deadline_at)
    WHERE status IN ('OPEN', 'RESERVED', 'PARTIAL');

CREATE INDEX IF NOT EXISTS idx_payout_requisites_operator
    ON operator_payout_requisites (operator_id, created_at DESC);

-- Привязка «реквизит → чек». order_id без FK: таблица orders живёт в схеме бота
-- и отсутствует в отдельных staging-профилях (как и в user_cashback_ledger).
CREATE TABLE IF NOT EXISTS payout_requisite_allocations (
    id              BIGSERIAL PRIMARY KEY,
    requisite_id    INT NOT NULL REFERENCES operator_payout_requisites(id) ON DELETE CASCADE,
    order_id        VARCHAR(64),
    kind            VARCHAR(8) NOT NULL,
    amount_rub      NUMERIC(14, 2) NOT NULL,
    status          VARCHAR(12) NOT NULL DEFAULT 'RESERVED',
    receipt_file    TEXT,
    paid_at         TIMESTAMPTZ,
    operator_id     INT REFERENCES operator_accounts(id) ON DELETE SET NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT payout_requisite_allocations_kind_chk
        CHECK (kind IN ('order', 'doliv', 'payin')),
    CONSTRAINT payout_requisite_allocations_status_chk
        CHECK (status IN ('RESERVED', 'PAID', 'CANCELED')),
    CONSTRAINT payout_requisite_allocations_amount_chk
        CHECK (amount_rub > 0),
    CONSTRAINT payout_requisite_allocations_order_chk
        CHECK (
            (kind IN ('order', 'payin') AND order_id IS NOT NULL)
            OR (kind = 'doliv' AND order_id IS NULL)
        )
);

-- Стенды с предыдущей версией миграции не знают про kind='payin' (BUY-заявка,
-- рубли которой клиент кладёт на карту реквизитчика вместо провайдера).
ALTER TABLE payout_requisite_allocations
    DROP CONSTRAINT IF EXISTS payout_requisite_allocations_kind_chk,
    DROP CONSTRAINT IF EXISTS payout_requisite_allocations_order_chk;

ALTER TABLE payout_requisite_allocations
    ADD CONSTRAINT payout_requisite_allocations_kind_chk
        CHECK (kind IN ('order', 'doliv', 'payin')),
    ADD CONSTRAINT payout_requisite_allocations_order_chk
        CHECK (
            (kind IN ('order', 'payin') AND order_id IS NOT NULL)
            OR (kind = 'doliv' AND order_id IS NULL)
        );

-- Одна заявка не может висеть на двух реквизитах одновременно.
CREATE UNIQUE INDEX IF NOT EXISTS ux_payout_alloc_active_order
    ON payout_requisite_allocations (order_id)
    WHERE order_id IS NOT NULL AND status IN ('RESERVED', 'PAID');

CREATE INDEX IF NOT EXISTS idx_payout_alloc_requisite
    ON payout_requisite_allocations (requisite_id, status);

-- Аудит предложений матчера: что бот считал лучшим планом и когда.
CREATE TABLE IF NOT EXISTS payout_requisite_plans (
    id              BIGSERIAL PRIMARY KEY,
    requisite_id    INT NOT NULL REFERENCES operator_payout_requisites(id) ON DELETE CASCADE,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    plan            JSONB NOT NULL,
    checks_count    SMALLINT NOT NULL DEFAULT 0,
    doliv_rub       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    leftover_rub    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    is_applied      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_payout_requisite_plans_latest
    ON payout_requisite_plans (requisite_id, computed_at DESC);

GRANT ALL PRIVILEGES ON TABLE operator_payout_requisites TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE payout_requisite_allocations TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE payout_requisite_plans TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE operator_payout_requisites_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE payout_requisite_allocations_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE payout_requisite_plans_id_seq TO exchange_bot;

ALTER TABLE operator_payout_requisites
    ALTER COLUMN doliv_limit_rub SET DEFAULT 2000;

ALTER TABLE payout_requisite_allocations
    ADD COLUMN IF NOT EXISTS client_confirmed_at TIMESTAMPTZ;

COMMENT ON TABLE operator_payout_requisites IS
    'Operator-declared payout requisites: amount to drain, cost in percent, analysis deadline';
COMMENT ON TABLE payout_requisite_allocations IS
    'Which SELL orders (or operator доливы) are assigned to a payout requisite';
COMMENT ON TABLE payout_requisite_plans IS
    'Audit trail of matcher proposals for a payout requisite';
COMMENT ON COLUMN payout_requisite_allocations.client_confirmed_at IS
    'When the SELL client confirmed they received the payout (Telegram or site)';
COMMENT ON COLUMN operator_payout_requisites.source_sell_order_id IS
    'SELL order whose client card is offered to BUY payers (triangle)';

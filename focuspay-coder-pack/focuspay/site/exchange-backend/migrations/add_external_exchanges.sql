-- Внештатные обмены: люди вне бота, которым мы ведём учёт долга в USDT.
-- Таблицы полностью изолированы от orders / operator_payroll_ledger / finance_pnl.

-- Справочник внештатников
CREATE TABLE IF NOT EXISTS external_exchangers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(256) NOT NULL,
    contact     VARCHAR(512),
    net_percent NUMERIC(6, 3) NOT NULL DEFAULT 20.0
                CHECK (net_percent >= 0 AND net_percent <= 100),
    note        TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_exchangers_active
    ON external_exchangers (is_active, created_at DESC);

-- Сделки: каждый ввод базовой суммы
CREATE TABLE IF NOT EXISTS external_deals (
    id              SERIAL PRIMARY KEY,
    exchanger_id    INT NOT NULL REFERENCES external_exchangers(id) ON DELETE RESTRICT,
    amount_rub      NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    crypto          VARCHAR(16) NOT NULL DEFAULT 'usdt'
                    CHECK (crypto IN ('btc', 'usdt', 'trx', 'ltc')),
    markup_pct      NUMERIC(6, 3) NOT NULL,       -- наценка на клиента, напр. 20.0
    card_fee_pct    NUMERIC(6, 4) NOT NULL,       -- комиссия пейфаст, напр. 0.12
    usdt_rate_rub   NUMERIC(14, 4) NOT NULL,      -- курс USDT/RUB на момент сделки
    client_pays_rub NUMERIC(14, 2) NOT NULL,      -- amount_rub * (1 + markup_pct/100)
    payfast_fee_rub NUMERIC(14, 2) NOT NULL,      -- client_pays_rub * card_fee_pct
    net_profit_rub  NUMERIC(14, 2) NOT NULL,      -- client_pays - payfast_fee - amount_rub
    principal_usdt  NUMERIC(14, 6) NOT NULL,      -- amount_rub / usdt_rate_rub (долг)
    reward_usdt     NUMERIC(14, 6) NOT NULL,      -- (net_profit_rub * net_percent/100) / usdt_rate_rub
    receive_fee_usd NUMERIC(14, 6) NOT NULL,      -- фикс. потеря при получении монет ($2)
    house_profit_usd NUMERIC(14, 6) NOT NULL,     -- наша прибыль = net_profit_rub/rate - reward_usdt - receive_fee_usd
    note            TEXT,
    created_by      VARCHAR(128),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_deals_exchanger
    ON external_deals (exchanger_id, created_at DESC);

-- Выводы: владелец выплачивает накопленный баланс
CREATE TABLE IF NOT EXISTS external_payouts (
    id           SERIAL PRIMARY KEY,
    exchanger_id INT NOT NULL REFERENCES external_exchangers(id) ON DELETE RESTRICT,
    gross_usd    NUMERIC(14, 6) NOT NULL CHECK (gross_usd > 0),  -- сколько списали с баланса
    fee_usd      NUMERIC(14, 6) NOT NULL DEFAULT 3.0,            -- комиссия вывода (наша прибыль)
    net_usd      NUMERIC(14, 6) NOT NULL,                        -- gross - fee (на руки)
    crypto       VARCHAR(16) NOT NULL DEFAULT 'usdt'
                 CHECK (crypto IN ('btc', 'usdt', 'trx', 'ltc')),
    tx_hash      TEXT,
    status       VARCHAR(20) NOT NULL DEFAULT 'paid'
                 CHECK (status IN ('paid', 'pending', 'canceled')),
    note         TEXT,
    created_by   VARCHAR(128),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_payouts_exchanger
    ON external_payouts (exchanger_id, created_at DESC);

-- Леджер баланса: SUM(amount_usd) = текущий долг перед внештатником
CREATE TABLE IF NOT EXISTS external_ledger (
    id           SERIAL PRIMARY KEY,
    exchanger_id INT NOT NULL REFERENCES external_exchangers(id) ON DELETE RESTRICT,
    type         VARCHAR(20) NOT NULL
                 CHECK (type IN ('principal', 'reward', 'payout', 'adjust')),
    amount_usd   NUMERIC(14, 6) NOT NULL,   -- положительное = начисление, отрицательное = списание
    deal_id      INT REFERENCES external_deals(id) ON DELETE SET NULL,
    payout_id    INT REFERENCES external_payouts(id) ON DELETE SET NULL,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_ledger_exchanger
    ON external_ledger (exchanger_id, created_at DESC);

-- Гранты
GRANT ALL PRIVILEGES ON TABLE external_exchangers TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE external_deals TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE external_payouts TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE external_ledger TO exchange_bot;

GRANT USAGE, SELECT ON SEQUENCE external_exchangers_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE external_deals_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE external_payouts_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE external_ledger_id_seq TO exchange_bot;

COMMENT ON TABLE external_exchangers IS
    'Внештатники: люди вне бота, которым ведём учёт долга в USDT';
COMMENT ON TABLE external_deals IS
    'Сделки внештатников: base_rub → principal+reward USDT';
COMMENT ON TABLE external_payouts IS
    'Выводы накопленного баланса внештатника';
COMMENT ON TABLE external_ledger IS
    'Леджер баланса USDT; SUM(amount_usd) = текущий баланс';

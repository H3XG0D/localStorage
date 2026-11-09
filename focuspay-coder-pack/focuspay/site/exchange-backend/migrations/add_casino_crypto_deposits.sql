-- Пополнение казино в BTC/LTC: свой адрес на клиента, кредит после подтверждения.
-- Запускать после add_casino_wagering_locks.sql.
-- Не использует external_deals: монеты приходят на наш горячий кошелёк.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_crypto_addresses (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL CHECK (user_id <> 0),
    coin        VARCHAR(8) NOT NULL CHECK (coin IN ('btc', 'ltc')),
    address     VARCHAR(128) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, coin),
    UNIQUE (coin, address)
);

CREATE TABLE IF NOT EXISTS casino_crypto_credits (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL CHECK (user_id <> 0),
    coin            VARCHAR(8) NOT NULL CHECK (coin IN ('btc', 'ltc')),
    address         VARCHAR(128) NOT NULL,
    txid            VARCHAR(64) NOT NULL,
    amount_crypto   NUMERIC(20, 8) NOT NULL CHECK (amount_crypto > 0),
    amount_rub      NUMERIC(14, 2),
    rate            NUMERIC(18, 8),
    confirmations   INTEGER NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
    status          VARCHAR(32) NOT NULL CHECK (status IN ('credited', 'below_minimum')),
    ledger_order_id VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (coin, txid)
);

CREATE INDEX IF NOT EXISTS idx_casino_crypto_credits_user
    ON casino_crypto_credits (user_id, created_at DESC);

COMMENT ON TABLE casino_crypto_addresses IS
    'Постоянный адрес приёма BTC/LTC клиента казино. Не является текущим адресом дома.';
COMMENT ON TABLE casino_crypto_credits IS
    'Один входящий txid зачисляется один раз. below_minimum остаётся в кошельке и не увеличивает баланс.';

ALTER TABLE casino_wagering_locks
    ALTER COLUMN deal_id DROP NOT NULL;

ALTER TABLE casino_wagering_locks
    ADD COLUMN IF NOT EXISTS crypto_credit_id BIGINT
        REFERENCES casino_crypto_credits(id) ON DELETE RESTRICT;

DO $block$
DECLARE
    cons name;
BEGIN
    FOR cons IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'public'
          AND rel.relname = 'casino_wagering_locks'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ILIKE '%telegram_id%'
    LOOP
        EXECUTE format('ALTER TABLE casino_wagering_locks DROP CONSTRAINT %I', cons);
    END LOOP;
END
$block$;

ALTER TABLE casino_wagering_locks
    DROP CONSTRAINT IF EXISTS casino_wagering_locks_user_id_nonzero;

ALTER TABLE casino_wagering_locks
    ADD CONSTRAINT casino_wagering_locks_user_id_nonzero
    CHECK (telegram_id <> 0);

ALTER TABLE casino_wagering_locks
    DROP CONSTRAINT IF EXISTS casino_wagering_locks_one_source;

ALTER TABLE casino_wagering_locks
    ADD CONSTRAINT casino_wagering_locks_one_source
    CHECK (
        (deal_id IS NOT NULL AND crypto_credit_id IS NULL)
        OR (deal_id IS NULL AND crypto_credit_id IS NOT NULL)
    );

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_wagering_locks_crypto_credit
    ON casino_wagering_locks (crypto_credit_id)
    WHERE crypto_credit_id IS NOT NULL;

COMMENT ON COLUMN casino_wagering_locks.crypto_credit_id IS
    'Лок отыгрыша криптопополнения. Ровно одно из deal_id и crypto_credit_id заполнено.';

GRANT ALL PRIVILEGES ON TABLE casino_crypto_addresses TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE casino_crypto_credits TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE casino_crypto_addresses_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE casino_crypto_credits_id_seq TO exchange_bot;

COMMIT;

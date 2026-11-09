-- Полная схема для пустой БД exchange_bot (запустить один раз на Ubuntu).
-- Подключение: psql -U exchange_bot -d exchange_bot -f migrations/create_tables.sql
-- Или из-под postgres: sudo -u postgres psql -d exchange_bot -f migrations/create_tables.sql

-- ============================================================
-- ТАБЛИЦА orders
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id                    SERIAL PRIMARY KEY,
    order_id              VARCHAR NOT NULL UNIQUE,
    user_id               BIGINT NOT NULL,
    status                VARCHAR NOT NULL,
    crypto_amount         DOUBLE PRECISION NOT NULL,
    fiat_amount           DOUBLE PRECISION NOT NULL,
    direction             VARCHAR NOT NULL,
    requisites            VARCHAR NOT NULL,
    rate                  DOUBLE PRECISION NOT NULL,
    created_at            TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    crypto                VARCHAR(30) NOT NULL,
    updated_at            TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    expires_at            TIMESTAMPTZ NOT NULL,
    merchant_order_id     TEXT,
    required_receipt_type SMALLINT,
    receipt_file          TEXT,
    sub_token             VARCHAR(20),
    CONSTRAINT orders_status_check CHECK (
        status IN (
            'CREATED', 'PENDING', 'COMPLETED', 'PAID', 'FAILED',
            'CANCELED', 'EXPIRED', 'DISPUTE', 'AWAITING_CHECK'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_orders_expires ON orders (status, expires_at);

COMMENT ON TABLE orders IS 'Заявки на обмен (покупка/продажа крипты)';
COMMENT ON COLUMN orders.merchant_order_id IS 'uuid_system из ответа мерча при создании payin; нужен для отмены';
COMMENT ON COLUMN orders.receipt_file IS 'Имя файла чека/видео в каталоге receipts (последний загруженный клиентом)';
COMMENT ON COLUMN orders.sub_token IS 'CARDRUB или SBPRUB — способ оплаты при создании payin';

-- ============================================================
-- ТАБЛИЦА bot_users
-- ============================================================
CREATE TABLE IF NOT EXISTS bot_users (
    user_id       BIGINT PRIMARY KEY,
    username      VARCHAR(255),
    first_name    VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bot_users IS 'Пользователи, хотя бы раз запустившие бота (/start); для рассылки';

CREATE INDEX IF NOT EXISTS idx_bot_users_last_seen ON bot_users (last_seen_at DESC);

-- Права для пользователя exchange_bot (если скрипт запускается от postgres)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO exchange_bot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO exchange_bot;

-- Оплата покупок клиента по QR СБП через finance666.
-- Рубли уходят получателю кода, с клиента списывается charged_rub (сумма + наша наценка),
-- с мерчантского баланса платформы — amount_usdt + fee_usdt.
--
-- local_status — наше состояние резерва на балансе клиента, оно не совпадает со статусом
-- платформы: RESERVED держит деньги до итога, SETTLED списал их проводками в ledger,
-- RELEASED вернул резерв (отказ/сбой), REFUNDED — возврат уже списанного.

CREATE TABLE IF NOT EXISTS qr_sbp_payments (
    id                      BIGSERIAL PRIMARY KEY,
    merchant_transaction_id VARCHAR(64) NOT NULL UNIQUE,
    provider_transaction_id VARCHAR(64) UNIQUE,
    user_id                 BIGINT NOT NULL,
    qr_code                 TEXT NOT NULL,
    payee_name              TEXT,
    amount_rub              NUMERIC(14, 2),
    charged_rub             NUMERIC(14, 2),
    markup_pct              NUMERIC(5, 2),
    charge_split            JSONB,
    amount_usdt             NUMERIC(20, 6),
    fee_usdt                NUMERIC(20, 6),
    status_group            VARCHAR(20),
    status_code             VARCHAR(64),
    is_final                BOOLEAN NOT NULL DEFAULT FALSE,
    local_status            VARCHAR(16) NOT NULL DEFAULT 'CHECKED',
    provider_updated_at     TIMESTAMPTZ,
    expires_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    settled_at              TIMESTAMPTZ,
    CONSTRAINT qr_sbp_payments_local_status_chk
        CHECK (local_status IN ('CHECKED', 'RESERVED', 'SETTLED', 'RELEASED', 'REFUNDED'))
);

-- Активные резервы клиента: читается на каждом расчёте доступного баланса.
CREATE INDEX IF NOT EXISTS qr_sbp_payments_reserved_idx
    ON qr_sbp_payments (user_id)
    WHERE local_status = 'RESERVED';

-- Суточный лимит и история клиента.
CREATE INDEX IF NOT EXISTS qr_sbp_payments_user_created_idx
    ON qr_sbp_payments (user_id, created_at DESC);

-- Фолбэк-опрос статуса, когда вебхук не дошёл.
CREATE INDEX IF NOT EXISTS qr_sbp_payments_pending_idx
    ON qr_sbp_payments (updated_at)
    WHERE local_status = 'RESERVED' AND is_final = FALSE;

-- Дедуп повторов вебхука: один и тот же X-Webhook-Id может прийти несколько раз.
CREATE TABLE IF NOT EXISTS qr_sbp_webhook_events (
    webhook_id   UUID PRIMARY KEY,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT ALL PRIVILEGES ON TABLE qr_sbp_payments TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE qr_sbp_webhook_events TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE qr_sbp_payments_id_seq TO exchange_bot;

COMMENT ON TABLE qr_sbp_payments IS
    'Оплаты клиентов по QR СБП через finance666: резерв баланса, статус платформы, итог.';
COMMENT ON COLUMN qr_sbp_payments.merchant_transaction_id IS
    'Наш идентификатор выплаты, уходит в check. Ключ идемпотентности.';
COMMENT ON COLUMN qr_sbp_payments.charged_rub IS
    'Списано с клиента: amount_rub + наценка markup_pct.';
COMMENT ON COLUMN qr_sbp_payments.charge_split IS
    'Откуда списали при SETTLED: cashback/referral/partner. Нужен, чтобы вернуть ровно так же.';
COMMENT ON COLUMN qr_sbp_payments.local_status IS
    'Состояние резерва у нас: CHECKED/RESERVED/SETTLED/RELEASED/REFUNDED.';
COMMENT ON COLUMN qr_sbp_payments.provider_updated_at IS
    'updated_at платформы. Статус применяем только если он новее сохранённого.';
COMMENT ON TABLE qr_sbp_webhook_events IS
    'Обработанные вебхуки finance666 (X-Webhook-Id) для отсечения повторов.';

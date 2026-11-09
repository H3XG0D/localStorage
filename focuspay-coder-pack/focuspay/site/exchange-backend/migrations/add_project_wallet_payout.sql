-- Ручные заявки с выплатой с кошелька проекта + учёт сетевых комиссий.

-- Последний принятый шаг TOTP: один и тот же код нельзя предъявить дважды.
ALTER TABLE operator_accounts ADD COLUMN IF NOT EXISTS totp_last_step BIGINT;

-- Отправка с кошелька проекта по ручной заявке записывается на смену оператора:
-- рубли пришли на его карту, на закрытии смены он их должен проекту.
ALTER TABLE auto_recon_entries ADD COLUMN IF NOT EXISTS operator_id BIGINT;
ALTER TABLE auto_recon_entries ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'auto_buy';
CREATE INDEX IF NOT EXISTS idx_auto_recon_operator ON auto_recon_entries (operator_id, created_at DESC);

-- Кто нажал «Отправить»: дневной лимит оператора считается по всем его
-- отправкам, включая ещё не закрытые заявки.
ALTER TABLE payout_requests ADD COLUMN IF NOT EXISTS operator_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_payout_requests_operator ON payout_requests (operator_id, created_at DESC)
    WHERE operator_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS network_fees (
    id BIGSERIAL PRIMARY KEY,
    txid TEXT NOT NULL,
    coin TEXT NOT NULL,
    fee_crypto NUMERIC(24, 12),
    fee_rub NUMERIC(14, 2),
    vsize INT,
    feerate_sat_vb NUMERIC(14, 3),
    -- project_wallet: отправка с горячего кошелька; operator_wallet: хеш от оператора.
    source TEXT NOT NULL,
    order_id TEXT,
    request_id TEXT,
    -- ok | not_found | error: строки с ошибкой перепроверяются фоновой задачей.
    status TEXT NOT NULL DEFAULT 'ok',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (coin, txid)
);

CREATE INDEX IF NOT EXISTS idx_network_fees_created ON network_fees (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_network_fees_order ON network_fees (order_id);

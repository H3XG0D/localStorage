-- Payfast + чек на внештатных сделках; индивидуальная наценка
-- psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_external_deal_payin.sql

ALTER TABLE external_exchangers
    ADD COLUMN IF NOT EXISTS markup_pct NUMERIC(6, 3)
    CHECK (markup_pct IS NULL OR (markup_pct >= 0 AND markup_pct <= 100));

COMMENT ON COLUMN external_exchangers.markup_pct IS
    'Наценка клиенту (%); NULL = settings.ext_markup_pct';

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS merchant_order_id TEXT,
    ADD COLUMN IF NOT EXISTS payment_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS receipt_file TEXT,
    ADD COLUMN IF NOT EXISTS sub_token VARCHAR(16),
    ADD COLUMN IF NOT EXISTS receipt_submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS paid_confirmed_at TIMESTAMPTZ;

ALTER TABLE external_deals DROP CONSTRAINT IF EXISTS external_deals_status_check;
ALTER TABLE external_deals ADD CONSTRAINT external_deals_status_check
    CHECK (status IN ('awaiting_receipt', 'pending', 'confirmed', 'cancelled'));

COMMENT ON COLUMN external_deals.merchant_order_id IS 'client_transaction_id / uuid для Payfast';
COMMENT ON COLUMN external_deals.payment_snapshot IS 'bill, pay_link, merchant_uuid';
COMMENT ON COLUMN external_deals.paid_confirmed_at IS 'Внештатник нажал «Я оплатил»';

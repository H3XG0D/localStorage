-- Multi-merchant attribution: which merchant accepted each payin.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS merchant_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS merchant_attempts JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE external_deals ADD COLUMN IF NOT EXISTS merchant_id TEXT;
ALTER TABLE external_deals ADD COLUMN IF NOT EXISTS merchant_attempts JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_orders_merchant_id ON orders (merchant_id);
CREATE INDEX IF NOT EXISTS idx_external_deals_merchant_id ON external_deals (merchant_id);

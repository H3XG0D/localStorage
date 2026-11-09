-- FocusLucky: weekly + monthly kinds, month grouping, 24h spacing guard
-- psql -U exchange_bot -d exchange_bot -f migrations/add_raffle_weekly.sql

ALTER TABLE raffle_campaigns
    ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'monthly',
    ADD COLUMN IF NOT EXISTS month_key VARCHAR(7);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'raffle_campaigns_kind_chk'
    ) THEN
        ALTER TABLE raffle_campaigns
            ADD CONSTRAINT raffle_campaigns_kind_chk CHECK (kind IN ('weekly', 'monthly'));
    END IF;
END $$;

-- Backfill kind/month_key (month_key = YYYY-MM of draw_at in MSK)
UPDATE raffle_campaigns
SET kind = 'monthly'
WHERE kind IS NULL OR kind NOT IN ('weekly', 'monthly');

UPDATE raffle_campaigns
SET month_key = to_char((draw_at AT TIME ZONE 'Europe/Moscow'), 'YYYY-MM')
WHERE month_key IS NULL AND draw_at IS NOT NULL;

UPDATE raffle_campaigns
SET month_key = to_char((starts_at AT TIME ZONE 'Europe/Moscow'), 'YYYY-MM')
WHERE month_key IS NULL;

CREATE INDEX IF NOT EXISTS idx_raffle_campaigns_kind_draw
    ON raffle_campaigns (kind, draw_at DESC);

CREATE INDEX IF NOT EXISTS idx_raffle_campaigns_month_key
    ON raffle_campaigns (month_key, kind);

-- Same columns for bot-side DBs (they share raffle_campaigns table; harmless if rerun)

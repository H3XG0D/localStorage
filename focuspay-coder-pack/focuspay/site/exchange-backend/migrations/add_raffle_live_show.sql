-- FocusLucky live draw: sequential places, auto RUB payout, Telegram outbox.
-- Additive. No-op when raffle_campaigns is absent (pvp-only bootstrap).

DO $$
BEGIN
    IF to_regclass('public.raffle_campaigns') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE raffle_campaigns DROP CONSTRAINT IF EXISTS raffle_campaigns_status_chk;
    ALTER TABLE raffle_campaigns
        ADD CONSTRAINT raffle_campaigns_status_chk
        CHECK (status IN ('draft', 'active', 'closed', 'drawing', 'drawn'));

    ALTER TABLE raffle_campaigns
        ADD COLUMN IF NOT EXISTS spin_interval_seconds INTEGER NOT NULL DEFAULT 30,
        ADD COLUMN IF NOT EXISTS pre_show_seconds INTEGER NOT NULL DEFAULT 30,
        ADD COLUMN IF NOT EXISTS notify_minutes_before INTEGER NOT NULL DEFAULT 15,
        ADD COLUMN IF NOT EXISTS show_started_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS spin_started_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS current_place INTEGER,
        ADD COLUMN IF NOT EXISTS next_spin_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS notify_sent_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS draw_commit TEXT;

    ALTER TABLE raffle_campaigns DROP CONSTRAINT IF EXISTS raffle_campaigns_spin_interval_chk;
    ALTER TABLE raffle_campaigns
        ADD CONSTRAINT raffle_campaigns_spin_interval_chk
        CHECK (spin_interval_seconds >= 10 AND spin_interval_seconds <= 120);

    ALTER TABLE raffle_campaigns DROP CONSTRAINT IF EXISTS raffle_campaigns_pre_show_chk;
    ALTER TABLE raffle_campaigns
        ADD CONSTRAINT raffle_campaigns_pre_show_chk
        CHECK (pre_show_seconds >= 5 AND pre_show_seconds <= 300);

    ALTER TABLE raffle_campaigns DROP CONSTRAINT IF EXISTS raffle_campaigns_notify_minutes_chk;
    ALTER TABLE raffle_campaigns
        ADD CONSTRAINT raffle_campaigns_notify_minutes_chk
        CHECK (notify_minutes_before >= 1 AND notify_minutes_before <= 120);

    ALTER TABLE raffle_winners DROP CONSTRAINT IF EXISTS raffle_winners_place_chk;
    ALTER TABLE raffle_winners
        ADD CONSTRAINT raffle_winners_place_chk
        CHECK (place >= 1 AND place <= 20);

    ALTER TABLE raffle_winners
        ADD COLUMN IF NOT EXISTS eligible_tickets INTEGER,
        ADD COLUMN IF NOT EXISTS hmac_index INTEGER;

    ALTER TABLE raffle_winners DROP CONSTRAINT IF EXISTS raffle_winners_payout_chk;
    ALTER TABLE raffle_winners
        ADD CONSTRAINT raffle_winners_payout_chk
        CHECK (payout_method IN ('ltc', 'balance'));
END $$;

CREATE TABLE IF NOT EXISTS raffle_notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(160) NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    campaign_id INTEGER NOT NULL,
    recipient_id BIGINT NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT raffle_notification_outbox_status_chk
        CHECK (status IN ('pending', 'processing', 'sent', 'failed')),
    CONSTRAINT raffle_notification_outbox_recipient_chk
        CHECK (recipient_id > 0)
);

DO $$
BEGIN
    IF to_regclass('public.raffle_campaigns') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conname = 'raffle_notification_outbox_campaign_fk'
       ) THEN
        ALTER TABLE raffle_notification_outbox
            ADD CONSTRAINT raffle_notification_outbox_campaign_fk
            FOREIGN KEY (campaign_id) REFERENCES raffle_campaigns(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_raffle_outbox_claim
    ON raffle_notification_outbox (status, available_at, id)
    WHERE status IN ('pending', 'processing');

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exchange_bot') THEN
        GRANT ALL PRIVILEGES ON TABLE raffle_notification_outbox TO exchange_bot;
        GRANT USAGE, SELECT ON SEQUENCE raffle_notification_outbox_id_seq TO exchange_bot;
    END IF;
END $$;

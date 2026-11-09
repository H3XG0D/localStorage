-- FocusLucky: admin draw_at, winner chance at settle, multi-wave bot notices.
-- Additive. No-op when raffle_campaigns is absent.

DO $$
BEGIN
    IF to_regclass('public.raffle_campaigns') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE raffle_campaigns
        ADD COLUMN IF NOT EXISTS notify_milestones JSONB NOT NULL DEFAULT '{}'::jsonb;

    UPDATE raffle_campaigns
    SET spin_interval_seconds = 12
    WHERE spin_interval_seconds < 12;

    ALTER TABLE raffle_campaigns DROP CONSTRAINT IF EXISTS raffle_campaigns_spin_interval_chk;
    ALTER TABLE raffle_campaigns
        ADD CONSTRAINT raffle_campaigns_spin_interval_chk
        CHECK (spin_interval_seconds >= 12 AND spin_interval_seconds <= 120);

    IF to_regclass('public.raffle_winners') IS NOT NULL THEN
        ALTER TABLE raffle_winners
            ADD COLUMN IF NOT EXISTS winner_tickets INTEGER;
    END IF;
END $$;

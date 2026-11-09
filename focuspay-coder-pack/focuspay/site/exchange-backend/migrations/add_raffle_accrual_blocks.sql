-- FocusLucky admin accrual blocks. Shared exchange/bot DB.
-- Additive. No-op when raffle_campaigns is absent.

DO $$
BEGIN
    IF to_regclass('public.raffle_campaigns') IS NULL THEN
        RETURN;
    END IF;

    CREATE TABLE IF NOT EXISTS raffle_accrual_blocks (
        campaign_id INTEGER NOT NULL REFERENCES raffle_campaigns(id) ON DELETE CASCADE,
        user_id     BIGINT NOT NULL,
        blocked_by  BIGINT,
        note        TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (campaign_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_raffle_accrual_blocks_user
        ON raffle_accrual_blocks (user_id);

    ALTER TABLE raffle_accrual_blocks
        ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'all';

    ALTER TABLE raffle_accrual_blocks
        DROP CONSTRAINT IF EXISTS raffle_accrual_blocks_scope_chk;
    ALTER TABLE raffle_accrual_blocks
        ADD CONSTRAINT raffle_accrual_blocks_scope_chk
        CHECK (scope IN ('all', 'referral'));
END $$;

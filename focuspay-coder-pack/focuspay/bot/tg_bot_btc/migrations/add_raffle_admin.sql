-- FocusLucky admin: editable texts + per-user accrual blocks
-- psql -U exchange_bot -d exchange_bot -f migrations/add_raffle_admin.sql

ALTER TABLE raffle_campaigns
    ADD COLUMN IF NOT EXISTS info_text TEXT,
    ADD COLUMN IF NOT EXISTS how_to_text TEXT;

COMMENT ON COLUMN raffle_campaigns.info_text IS
    'Custom footer text on FocusLucky screen; NULL = default from bot code';
COMMENT ON COLUMN raffle_campaigns.how_to_text IS
    'Custom how-to-earn text; NULL = default from bot code';

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

GRANT ALL PRIVILEGES ON TABLE raffle_accrual_blocks TO exchange_bot;

COMMENT ON TABLE raffle_accrual_blocks IS
    'Stop future ticket accrual for user in campaign; existing tickets remain';

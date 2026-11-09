-- FocusVPN reminders: one row per sent "ends soon" / "ended" message, so the
-- VPN bot never repeats a reminder for the same subscription end.

CREATE TABLE IF NOT EXISTS vpn_notifications (
    telegram_id BIGINT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('soon', 'ended')),
    ends_at     TIMESTAMPTZ NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (telegram_id, kind, ends_at)
);

CREATE INDEX IF NOT EXISTS idx_vpn_notifications_sent ON vpn_notifications (sent_at);

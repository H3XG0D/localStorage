-- Happ and similar clients take a subscription URL. The link is a device
-- seat (platform "link"); the raw token is sealed so the bot can show it again.

ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_platform_check;
ALTER TABLE devices ADD CONSTRAINT devices_platform_check
    CHECK (platform IN ('android', 'ios', 'macos', 'windows', 'linux', 'link'));

CREATE TABLE subscription_links (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    device_id   uuid NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    token_hash  text NOT NULL,
    token_enc   bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz,
    CONSTRAINT uq_sub_links_token UNIQUE (token_hash)
);

CREATE UNIQUE INDEX uq_sub_links_live_user
    ON subscription_links (user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_sub_links_device ON subscription_links (device_id);

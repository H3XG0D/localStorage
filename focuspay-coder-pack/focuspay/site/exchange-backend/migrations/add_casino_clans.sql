-- Player clans: persistent teams, invite codes, membership history for weekly turnover.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_clans (
    id BIGSERIAL PRIMARY KEY,
    tag VARCHAR(8) NOT NULL,
    name VARCHAR(32) NOT NULL,
    owner_id BIGINT NOT NULL CHECK (owner_id <> 0),
    invite_code VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disbanded_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_clans_tag
    ON casino_clans (tag);
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_clans_invite_code
    ON casino_clans (invite_code);
CREATE INDEX IF NOT EXISTS idx_casino_clans_owner
    ON casino_clans (owner_id) WHERE disbanded_at IS NULL;

CREATE TABLE IF NOT EXISTS casino_clan_members (
    id BIGSERIAL PRIMARY KEY,
    clan_id BIGINT NOT NULL REFERENCES casino_clans(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL CHECK (user_id <> 0),
    role VARCHAR(16) NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    left_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_clan_active_member
    ON casino_clan_members (user_id) WHERE left_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_casino_clan_members_clan
    ON casino_clan_members (clan_id, left_at);
CREATE INDEX IF NOT EXISTS idx_casino_clan_members_left
    ON casino_clan_members (user_id, left_at DESC);

INSERT INTO casino_settings (key, value, description) VALUES
    ('clans_enabled', '{"enabled": true}'::jsonb, 'Player clans: create and join'),
    ('clan_max_members', '{"value": 20}'::jsonb, 'Max live members per clan')
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE casino_clans IS 'Persistent player clans. No clan wallet; turnover is attributed via membership history.';
COMMENT ON TABLE casino_clan_members IS 'Clan roster with left_at history so weekly turnover is not farmed by hopping.';

COMMIT;

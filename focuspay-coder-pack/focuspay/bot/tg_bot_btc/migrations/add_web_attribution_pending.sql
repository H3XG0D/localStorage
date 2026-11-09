-- Same as exchange/backend/migrations/add_web_attribution_pending.sql
CREATE TABLE IF NOT EXISTS web_attribution_pending (
    id              BIGSERIAL PRIMARY KEY,
    ref_kind        VARCHAR(8) NOT NULL CHECK (ref_kind IN ('promo', 'user')),
    ref_token       VARCHAR(32) NOT NULL,
    guest_user_id   BIGINT NOT NULL,
    fingerprint     VARCHAR(64),
    client_ip       INET,
    user_agent      TEXT,
    applied         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '30 days')
);

CREATE INDEX IF NOT EXISTS idx_web_attr_pending_guest
    ON web_attribution_pending (guest_user_id);

CREATE INDEX IF NOT EXISTS idx_web_attr_pending_fp
    ON web_attribution_pending (fingerprint, ref_kind)
    WHERE applied = FALSE AND fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_web_attr_pending_ip
    ON web_attribution_pending (client_ip, ref_kind)
    WHERE applied = FALSE AND client_ip IS NOT NULL;

COMMENT ON TABLE web_attribution_pending IS
    'Pending ref visits from web before login; applied to guest_user_id then merged on auth';

GRANT SELECT, INSERT, UPDATE, DELETE ON web_attribution_pending TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE web_attribution_pending_id_seq TO exchange_bot;

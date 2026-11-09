-- FocusLucky: monthly raffle with numbered tickets
-- psql -U exchange_bot -d exchange_bot -f migrations/add_raffle.sql

CREATE TABLE IF NOT EXISTS raffle_campaigns (
    id                      SERIAL PRIMARY KEY,
    slug                    VARCHAR(64) NOT NULL UNIQUE,
    title                   VARCHAR(128) NOT NULL DEFAULT 'FocusLucky',
    month_label             VARCHAR(64),
    starts_at               TIMESTAMPTZ NOT NULL,
    ends_at                 TIMESTAMPTZ NOT NULL,
    draw_at                 TIMESTAMPTZ,
    rub_per_own_ticket      NUMERIC(14, 2) NOT NULL DEFAULT 1000,
    rub_per_referral_ticket NUMERIC(14, 2) NOT NULL DEFAULT 3000,
    min_order_rub           NUMERIC(14, 2) NOT NULL DEFAULT 500,
    max_tickets_per_user    INTEGER,
    prize_pool_rub          NUMERIC(14, 2) NOT NULL DEFAULT 14500,
    prize_places            JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_ticket_no          INTEGER NOT NULL DEFAULT 1,
    total_tickets_issued    INTEGER NOT NULL DEFAULT 0,
    total_tickets_void      INTEGER NOT NULL DEFAULT 0,
    status                  VARCHAR(16) NOT NULL DEFAULT 'draft',
    draw_seed               TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT raffle_campaigns_status_chk
        CHECK (status IN ('draft', 'active', 'closed', 'drawn'))
);

CREATE INDEX IF NOT EXISTS idx_raffle_campaigns_status
    ON raffle_campaigns (status, starts_at DESC);

CREATE TABLE IF NOT EXISTS raffle_participants (
    campaign_id         INTEGER NOT NULL REFERENCES raffle_campaigns(id) ON DELETE CASCADE,
    user_id             BIGINT NOT NULL,
    own_volume_rub      NUMERIC(14, 2) NOT NULL DEFAULT 0,
    referral_volume_rub NUMERIC(14, 2) NOT NULL DEFAULT 0,
    tickets_own         INTEGER NOT NULL DEFAULT 0,
    tickets_referral    INTEGER NOT NULL DEFAULT 0,
    tickets_total       INTEGER NOT NULL DEFAULT 0,
    ticket_no_first     INTEGER,
    ticket_no_last      INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_raffle_participants_user
    ON raffle_participants (user_id);

CREATE TABLE IF NOT EXISTS raffle_ticket_ranges (
    id               SERIAL PRIMARY KEY,
    campaign_id      INTEGER NOT NULL REFERENCES raffle_campaigns(id) ON DELETE CASCADE,
    user_id          BIGINT NOT NULL,
    order_id         VARCHAR(64) NOT NULL,
    kind             VARCHAR(16) NOT NULL,
    fiat_amount      NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ticket_no_from   INTEGER NOT NULL,
    ticket_no_to     INTEGER NOT NULL,
    ticket_count     INTEGER NOT NULL,
    status           VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT raffle_ticket_ranges_kind_chk CHECK (kind IN ('own', 'referral')),
    CONSTRAINT raffle_ticket_ranges_status_chk CHECK (status IN ('active', 'void')),
    CONSTRAINT raffle_ticket_ranges_count_chk CHECK (ticket_count > 0),
    CONSTRAINT raffle_ticket_ranges_range_chk CHECK (ticket_no_to >= ticket_no_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_raffle_ticket_ranges_idempotent
    ON raffle_ticket_ranges (campaign_id, order_id, kind, user_id);

CREATE INDEX IF NOT EXISTS idx_raffle_ticket_ranges_campaign_user
    ON raffle_ticket_ranges (campaign_id, user_id, status);

CREATE INDEX IF NOT EXISTS idx_raffle_ticket_ranges_lookup
    ON raffle_ticket_ranges (campaign_id, ticket_no_from, ticket_no_to)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS raffle_winners (
    id                 SERIAL PRIMARY KEY,
    campaign_id        INTEGER NOT NULL REFERENCES raffle_campaigns(id) ON DELETE CASCADE,
    place              INTEGER NOT NULL,
    user_id            BIGINT NOT NULL,
    winning_ticket_no  INTEGER NOT NULL,
    prize_rub          NUMERIC(14, 2) NOT NULL,
    payout_method      VARCHAR(16) NOT NULL DEFAULT 'balance',
    status             VARCHAR(16) NOT NULL DEFAULT 'pending',
    payout_note        TEXT,
    paid_at            TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT raffle_winners_place_chk CHECK (place >= 1 AND place <= 10),
    CONSTRAINT raffle_winners_payout_chk CHECK (payout_method IN ('ltc', 'balance')),
    CONSTRAINT raffle_winners_status_chk CHECK (status IN ('pending', 'paid')),
    UNIQUE (campaign_id, place)
);

GRANT ALL PRIVILEGES ON TABLE raffle_campaigns TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE raffle_participants TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE raffle_ticket_ranges TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE raffle_winners TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE raffle_campaigns_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE raffle_ticket_ranges_id_seq TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE raffle_winners_id_seq TO exchange_bot;

COMMENT ON TABLE raffle_campaigns IS 'FocusLucky monthly raffle campaigns';
COMMENT ON TABLE raffle_ticket_ranges IS 'Allocated ticket number ranges per PAID order';

-- Activate first campaign (adjust dates as needed):
-- INSERT INTO raffle_campaigns (
--     slug, title, month_label, starts_at, ends_at, draw_at, status, prize_places
-- ) VALUES (
--     'focuslucky-2026-06',
--     'FocusLucky',
--     'июнь 2026',
--     '2026-06-01 00:00:00+03',
--     '2026-06-30 23:59:59+03',
--     '2026-07-01 20:00:00+03',
--     'active',
--     '[
--       {"place":1,"prize_rub":5000,"payout_method":"ltc"},
--       {"place":2,"prize_rub":3000,"payout_method":"ltc"},
--       {"place":3,"prize_rub":2000,"payout_method":"ltc"},
--       {"place":4,"prize_rub":1000,"payout_method":"balance"},
--       {"place":5,"prize_rub":1000,"payout_method":"balance"},
--       {"place":6,"prize_rub":500,"payout_method":"balance"},
--       {"place":7,"prize_rub":500,"payout_method":"balance"},
--       {"place":8,"prize_rub":500,"payout_method":"balance"},
--       {"place":9,"prize_rub":500,"payout_method":"balance"},
--       {"place":10,"prize_rub":500,"payout_method":"balance"}
--     ]'::jsonb
-- );

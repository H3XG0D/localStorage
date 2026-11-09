-- FocusVPN billing: one row per VPN purchase or trial (saga state + revenue ledger).
-- Money lives in the unified balance ledgers (hold/spend by order_ref);
-- days live in the FocusVPN control plane (billing_events keyed by id).

CREATE TABLE IF NOT EXISTS vpn_purchases (
    id          UUID PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('paid', 'trial')),
    plan_code   TEXT NOT NULL,
    days        INT NOT NULL CHECK (days > 0),
    price_rub   NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
    status      TEXT NOT NULL CHECK (status IN ('held', 'granted', 'paid', 'released', 'failed')),
    idem_key    TEXT NOT NULL,
    order_ref   TEXT NOT NULL,
    cp_ends_at  TIMESTAMPTZ,
    error       TEXT,
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at     TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vpn_purchases_idem ON vpn_purchases (idem_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vpn_purchases_order_ref ON vpn_purchases (order_ref);

-- One trial per Telegram account, ever (released/failed attempts do not count).
CREATE UNIQUE INDEX IF NOT EXISTS uq_vpn_purchases_one_trial
    ON vpn_purchases (telegram_id)
    WHERE kind = 'trial' AND status IN ('held', 'granted', 'paid');

CREATE INDEX IF NOT EXISTS idx_vpn_purchases_open
    ON vpn_purchases (updated_at)
    WHERE status IN ('held', 'granted');

CREATE INDEX IF NOT EXISTS idx_vpn_purchases_paid_at
    ON vpn_purchases (paid_at)
    WHERE status = 'paid';

CREATE INDEX IF NOT EXISTS idx_vpn_purchases_tg ON vpn_purchases (telegram_id, created_at DESC);

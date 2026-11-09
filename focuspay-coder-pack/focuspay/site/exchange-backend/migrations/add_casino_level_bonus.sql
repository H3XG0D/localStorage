-- One-time weekly balance credit when weekly wager crosses a volume level.
BEGIN;

CREATE TABLE IF NOT EXISTS casino_level_bonus_grants (
    telegram_id BIGINT NOT NULL,
    week_start DATE NOT NULL,
    min_wager_rub NUMERIC(14, 2) NOT NULL,
    bonus_rub NUMERIC(14, 2) NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (telegram_id, week_start, min_wager_rub)
);

INSERT INTO casino_settings (key, value, description) VALUES
    (
        'level_reach_bonuses',
        '[]'::jsonb,
        'One-time weekly balance credit when weekly wager crosses a volume level'
    )
ON CONFLICT (key) DO NOTHING;

COMMENT ON TABLE casino_level_bonus_grants IS
    'Idempotent weekly volume-level bonus: one credit per player, Moscow week, and min_wager threshold.';

COMMIT;

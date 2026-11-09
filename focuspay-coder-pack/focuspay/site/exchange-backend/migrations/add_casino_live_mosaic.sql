-- Live mosaic: 10s start countdown on rooms; concurrent-games default 10.
BEGIN;

ALTER TABLE casino_fixed_room_rounds
    DROP CONSTRAINT IF EXISTS casino_fixed_room_rounds_status_check;

ALTER TABLE casino_fixed_room_rounds
    ADD CONSTRAINT casino_fixed_room_rounds_status_check
    CHECK (status IN ('open', 'countdown', 'locked', 'settled', 'refunded'));

ALTER TABLE casino_fixed_room_rounds
    ADD COLUMN IF NOT EXISTS countdown_ends_at TIMESTAMPTZ;

UPDATE casino_settings
SET value = '{"value": 10}'::jsonb
WHERE key = 'max_concurrent_games_per_player'
  AND value = '{"value": 3}'::jsonb;

COMMIT;

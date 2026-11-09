-- Fixed-stake rooms: bot seats (house-backed) and pvp_robot allowed_games.
BEGIN;

ALTER TABLE casino_fixed_room_seats
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE casino_fixed_room_seats
    DROP CONSTRAINT IF EXISTS casino_fixed_room_seats_user_id_check;

ALTER TABLE casino_fixed_room_seats
    ADD COLUMN IF NOT EXISTS participant_kind VARCHAR(16) NOT NULL DEFAULT 'player';

ALTER TABLE casino_fixed_room_seats
    ADD COLUMN IF NOT EXISTS robot_profile_id BIGINT;

UPDATE casino_fixed_room_seats
SET participant_kind = 'player'
WHERE participant_kind IS NULL OR participant_kind = '';

ALTER TABLE casino_fixed_room_seats
    DROP CONSTRAINT IF EXISTS casino_fixed_room_seats_participant_chk;

ALTER TABLE casino_fixed_room_seats
    ADD CONSTRAINT casino_fixed_room_seats_participant_chk CHECK (
        (participant_kind = 'player' AND user_id IS NOT NULL AND user_id <> 0 AND robot_profile_id IS NULL)
        OR (participant_kind = 'bot' AND user_id IS NULL AND robot_profile_id IS NOT NULL)
    );

UPDATE casino_robot_profiles
SET allowed_games = CASE
    WHEN COALESCE(allowed_games, '[]'::jsonb) ? 'fixed_room' THEN allowed_games
    ELSE COALESCE(allowed_games, '[]'::jsonb) || '["fixed_room"]'::jsonb
END
WHERE mode = 'pvp_robot';

COMMENT ON COLUMN casino_fixed_room_seats.participant_kind IS
    'player = Telegram/web user; bot = house pvp_robot with equal stake';

COMMIT;

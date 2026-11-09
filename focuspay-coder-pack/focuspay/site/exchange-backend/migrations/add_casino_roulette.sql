-- European roulette (single zero, 37 pockets) as a 1×1 house game.
-- Apply after add_casino_house_bankroll.sql.
--
-- Only two things are needed: casino_games must accept the new game_type, and the
-- settings registry must know the enabled flag. Payouts are wheel rules
-- (red/black 1:1, zero 35:1) and live in casino_roulette.py, deliberately NOT in
-- casino_house_policies — an operator must not be able to retune them. Roulette
-- reuses the cub house policy row and the cub house robot bankroll.
--
-- Rerunnable: the enabled flag keeps whatever value it already has, so a repeated
-- bootstrap never flips a live game on or off.
BEGIN;

DO $$
BEGIN
    IF to_regclass('public.casino_games') IS NULL
       OR to_regclass('public.casino_settings') IS NULL
       OR to_regclass('public.casino_house_accounts') IS NULL THEN
        RAISE EXCEPTION 'casino roulette requires the existing casino schema';
    END IF;
END $$;

DO $$
DECLARE
    constraint_name TEXT;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'casino_games'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%pvp_dice%'
      AND pg_get_constraintdef(oid) LIKE '%game_type%'
    LIMIT 1;
    IF constraint_name IS NULL THEN
        RAISE EXCEPTION 'casino_games game_type constraint not found';
    END IF;
    EXECUTE format('ALTER TABLE casino_games DROP CONSTRAINT %I', constraint_name);
END $$;
ALTER TABLE casino_games ADD CONSTRAINT casino_games_game_type_check
    CHECK (game_type IN (
        'pvp_dice', 'pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball',
        'baccara', 'blackjack', 'raffle', 'cub', 'roulette'
    )) NOT VALID;
ALTER TABLE casino_games VALIDATE CONSTRAINT casino_games_game_type_check;

INSERT INTO casino_settings (key, value, description)
VALUES ('enabled_games', '{"roulette": false}'::jsonb, 'Casino games enabled flags')
ON CONFLICT (key) DO UPDATE
SET value = COALESCE(casino_settings.value, '{}'::jsonb) || jsonb_build_object(
    'roulette', COALESCE(casino_settings.value->'roulette', 'false'::jsonb)
), updated_at = now();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'casino_games'::regclass
          AND conname = 'casino_games_game_type_check'
          AND pg_get_constraintdef(oid) LIKE '%roulette%'
    ) THEN
        RAISE EXCEPTION 'casino_games must accept game_type roulette';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM casino_settings WHERE key = 'enabled_games' AND value ? 'roulette'
    ) THEN
        RAISE EXCEPTION 'enabled_games must carry the roulette flag';
    END IF;
END $$;

COMMIT;

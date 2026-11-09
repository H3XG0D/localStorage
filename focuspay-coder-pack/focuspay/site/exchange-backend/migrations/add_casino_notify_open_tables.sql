-- Opt-in Telegram DMs for new blackjack player tables. Default off.
BEGIN;

ALTER TABLE casino_player_cosmetics
    ADD COLUMN IF NOT EXISTS notify_open_tables BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN casino_player_cosmetics.notify_open_tables IS
    'If true, casino-bot DMs about new blackjack player tables. Off until the player enables it.';

UPDATE casino_robot_profiles
SET allowed_games = COALESCE(allowed_games, '[]'::jsonb) || '["blackjack"]'::jsonb,
    updated_at = now()
WHERE mode = 'pvp_robot'
  AND is_active
  AND NOT (COALESCE(allowed_games, '[]'::jsonb) ? 'blackjack');

COMMIT;

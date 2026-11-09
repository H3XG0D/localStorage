-- Remove retired sport PvP keys from live settings JSON.
-- Historical casino_games rows are kept. Do not tighten game_type CHECKs.

BEGIN;

UPDATE casino_settings
SET value = value - ARRAY['pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball'],
    updated_at = now()
WHERE key IN ('enabled_games', 'per_game_limits', 'max_rounds_per_player_per_day', 'provably_fair_enabled')
  AND jsonb_typeof(value) = 'object'
  AND value ?| ARRAY['pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball'];

COMMIT;

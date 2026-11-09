-- Example weekly volume-level bonuses. Fill only if the key is still an empty list.
-- Does not overwrite live amounts an admin already saved.
BEGIN;

INSERT INTO casino_settings (key, value, description) VALUES
    (
        'level_reach_bonuses',
        '[
            {"min_wager_rub": 50000, "bonus_rub": 500},
            {"min_wager_rub": 100000, "bonus_rub": 1000},
            {"min_wager_rub": 200000, "bonus_rub": 2500},
            {"min_wager_rub": 500000, "bonus_rub": 5000}
        ]'::jsonb,
        'One-time weekly balance credit when weekly wager crosses a volume level'
    )
ON CONFLICT (key) DO NOTHING;

UPDATE casino_settings
SET value = '[
    {"min_wager_rub": 50000, "bonus_rub": 500},
    {"min_wager_rub": 100000, "bonus_rub": 1000},
    {"min_wager_rub": 200000, "bonus_rub": 2500},
    {"min_wager_rub": 500000, "bonus_rub": 5000}
]'::jsonb
WHERE key = 'level_reach_bonuses'
  AND value = '[]'::jsonb;

COMMIT;

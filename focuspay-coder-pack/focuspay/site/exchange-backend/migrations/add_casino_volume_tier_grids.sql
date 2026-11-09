-- Настраиваемые сетки кешбека и комиссии по недельному обороту ставок.

BEGIN;

INSERT INTO casino_settings (key, value, description) VALUES
    (
        'cashback_volume_tiers',
        '[
            {"min_wager_rub": 0, "percent": 2},
            {"min_wager_rub": 50000, "percent": 5},
            {"min_wager_rub": 100000, "percent": 7},
            {"min_wager_rub": 200000, "percent": 10},
            {"min_wager_rub": 500000, "percent": 15}
        ]'::jsonb,
        'Сетка кешбека: min недельного оборота ставок → процент от eligible-loss'
    ),
    (
        'commission_volume_tiers',
        '[
            {"min_wager_rub": 0, "active_rate": 15, "complete_rate": 5},
            {"min_wager_rub": 50000, "active_rate": 12, "complete_rate": 4},
            {"min_wager_rub": 100000, "active_rate": 10, "complete_rate": 3},
            {"min_wager_rub": 200000, "active_rate": 8, "complete_rate": 2.5}
        ]'::jsonb,
        'Сетка комиссии: min недельного оборота → ставки до/после отыгрыша депозита'
    )
ON CONFLICT (key) DO NOTHING;

COMMIT;

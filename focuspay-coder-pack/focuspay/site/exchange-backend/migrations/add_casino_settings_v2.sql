-- Новые ключи casino_settings из реестра (задача 2).
-- Повторный прогон не затирает живые значения: только INSERT, конфликт — пропуск.

BEGIN;

INSERT INTO casino_settings (key, value, description) VALUES
    ('max_profit_pct_per_round', '{"percent": 1.0}'::jsonb, 'Макс. выигрыш за раунд (% банка)'),
    ('max_profit_pct_per_round_all', '{"percent": 1.5}'::jsonb, 'Макс. выигрыш всех за раунд (% банка)'),
    ('bankroll_floor_rub', '{"amount": 0.0}'::jsonb, 'Порог банкролла (₽); 0 = выключено'),
    ('liability_amount_rub', '{"amount": 0.0}'::jsonb, 'Потолок обязательств (₽); 0 = не ограничивает'),
    ('per_game_limits', '{}'::jsonb, 'Лимиты по играм; пусто = глобальный min/max'),
    ('bet_step_rub', '{"amount": 10.0}'::jsonb, 'Шаг ставки (₽)'),
    ('max_concurrent_games_per_player', '{"value": 3}'::jsonb, 'Макс. одновременных игр'),
    ('max_rounds_per_player_per_day', '{}'::jsonb, 'Раундов в день по играм; пусто/0 = без лимита'),
    ('pending_invite_ttl_minutes', '{"value": 10}'::jsonb, 'TTL приглашения (мин)'),
    ('move_timeout_minutes', '{"value": 120}'::jsonb, 'Таймаут хода (мин)'),
    ('commission_cap_rub', '{"amount": 0.0}'::jsonb, 'Потолок комиссии (₽); 0 = без потолка'),
    ('commission_min_rub', '{"amount": 0.0}'::jsonb, 'Минимальная комиссия (₽); 0 = без минимума'),
    ('deposit_limit_enabled', '{"enabled": false}'::jsonb, 'Лимит депозита игрока'),
    ('loss_limit_enabled', '{"enabled": false}'::jsonb, 'Лимит проигрыша игрока'),
    ('wager_limit_enabled', '{"enabled": false}'::jsonb, 'Лимит ставок игрока'),
    ('session_limit_enabled', '{"enabled": false}'::jsonb, 'Лимит сессии игрока'),
    ('reality_check_default_minutes', '{"value": 60}'::jsonb, 'Напоминание (мин); 0 = выключено'),
    ('self_exclusion_min_hours', '{"value": 24}'::jsonb, 'Мин. самоисключение (ч)'),
    ('timeout_max_hours', '{"value": 72}'::jsonb, 'Макс. тайм-аут (ч)'),
    ('limit_loosening_delay_hours', '{"value": 24}'::jsonb, 'Задержка ослабления лимита (ч)'),
    ('withdrawal_auto_approve_max_rub', '{"amount": 0.0}'::jsonb, 'Автовывод до (₽); 0 = всё вручную'),
    ('withdrawal_manual_review_min_rub', '{"amount": 0.0}'::jsonb, 'Ручная проверка от (₽); 0 = выкл.'),
    ('withdrawal_daily_limit_rub', '{"amount": 0.0}'::jsonb, 'Дневной лимит вывода (₽); 0 = выкл.'),
    ('withdrawal_hourly_limit_rub', '{"amount": 0.0}'::jsonb, 'Часовой лимит вывода (₽); 0 = выкл.'),
    (
        'provably_fair_enabled',
        '{"pvp_dice": false, "pvp_darts": false, "pvp_bowling": false, "pvp_football": false, "pvp_basketball": false, "baccara": false, "blackjack": false, "raffle": false, "cub": false}'::jsonb,
        'Provably fair по играм; по умолчанию выключено'
    ),
    ('seed_rotation_allowed', '{"enabled": true}'::jsonb, 'Ротация сидов')
ON CONFLICT (key) DO NOTHING;

COMMIT;

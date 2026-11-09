-- Casino integration tables
-- Run: psql -h 127.0.0.1 -p 5434 -U exchange_bot -d exchange_bot -f migrations/add_casino_tables.sql

-- Игры казино (история всех игр)
CREATE TABLE IF NOT EXISTS casino_games (
    id                SERIAL PRIMARY KEY,
    game_id           VARCHAR(64) NOT NULL UNIQUE,
    game_type         VARCHAR(32) NOT NULL CHECK (
        game_type IN ('pvp_dice', 'pvp_darts', 'pvp_bowling', 'pvp_football', 'pvp_basketball',
                      'baccara', 'blackjack', 'raffle')
    ),
    creator_id        BIGINT NOT NULL,
    opponent_id       BIGINT,
    bet_rub           NUMERIC(12, 2) NOT NULL CHECK (bet_rub > 0),
    commission_rub    NUMERIC(12, 2) NOT NULL DEFAULT 0,
    winner_id         BIGINT,
    status            VARCHAR(20) NOT NULL DEFAULT 'waiting' CHECK (
        status IN ('waiting', 'active', 'finished', 'cancelled', 'expired')
    ),
    game_data         JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_casino_games_creator ON casino_games (creator_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_games_opponent ON casino_games (opponent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_games_status ON casino_games (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_games_type ON casino_games (game_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_games_finished ON casino_games (finished_at DESC) WHERE finished_at IS NOT NULL;

COMMENT ON TABLE casino_games IS 'История игр казино (PVP, карточные, розыгрыши)';
COMMENT ON COLUMN casino_games.game_data IS 'JSONB: карты, броски, участники розыгрыша и т.д.';

-- Недельный кешбек игроков (2% от проигранных ставок)
CREATE TABLE IF NOT EXISTS casino_player_cashback (
    id                BIGSERIAL PRIMARY KEY,
    telegram_id       BIGINT NOT NULL,
    week_start        DATE NOT NULL,
    total_bet_rub     NUMERIC(12, 2) NOT NULL DEFAULT 0,
    total_won_rub     NUMERIC(12, 2) NOT NULL DEFAULT 0,
    net_loss_rub      NUMERIC(12, 2) NOT NULL DEFAULT 0,
    cashback_rub      NUMERIC(12, 2) NOT NULL DEFAULT 0,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'accrued', 'skipped')
    ),
    accrued_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (telegram_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_casino_cashback_user_week ON casino_player_cashback (telegram_id, week_start DESC);
CREATE INDEX IF NOT EXISTS idx_casino_cashback_status ON casino_player_cashback (status, week_start DESC);

COMMENT ON TABLE casino_player_cashback IS 'Недельный кешбек 2% от чистых проигрышей игроков казино';
COMMENT ON COLUMN casino_player_cashback.net_loss_rub IS 'Чистый проигрыш за неделю (total_bet - total_won)';

-- Распределение комиссий
CREATE TABLE IF NOT EXISTS casino_commission_ledger (
    id                BIGSERIAL PRIMARY KEY,
    game_id           INTEGER NOT NULL REFERENCES casino_games(id) ON DELETE CASCADE,
    recipient_type    VARCHAR(20) NOT NULL CHECK (
        recipient_type IN ('creator', 'referrer_l1', 'referrer_l2', 'owner')
    ),
    recipient_id      BIGINT,
    amount_rub        NUMERIC(12, 2) NOT NULL CHECK (amount_rub >= 0),
    status            VARCHAR(20) NOT NULL DEFAULT 'accrued' CHECK (
        status IN ('accrued', 'paid', 'cancelled')
    ),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_casino_commission_game ON casino_commission_ledger (game_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_casino_commission_game_recipient_type
    ON casino_commission_ledger (game_id, recipient_type);
CREATE INDEX IF NOT EXISTS idx_casino_commission_recipient ON casino_commission_ledger (recipient_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_commission_type ON casino_commission_ledger (recipient_type, created_at DESC);

COMMENT ON TABLE casino_commission_ledger IS 'Начисления комиссий (создатель, рефералы, владелец)';
COMMENT ON COLUMN casino_commission_ledger.recipient_id IS 'telegram_id получателя (NULL для owner)';

-- Баланс создателя кода
CREATE TABLE IF NOT EXISTS casino_creator_balance (
    telegram_id           BIGINT PRIMARY KEY,
    balance_rub           NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (balance_rub >= 0),
    total_earned_rub      NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (total_earned_rub >= 0),
    total_withdrawn_rub   NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (total_withdrawn_rub >= 0),
    games_count           INTEGER NOT NULL DEFAULT 0,
    last_game_at          TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE casino_creator_balance IS 'Баланс и статистика создателя кода казино';

-- Заявки на вывод создателя
CREATE TABLE IF NOT EXISTS casino_creator_withdrawals (
    id                    SERIAL PRIMARY KEY,
    telegram_id           BIGINT NOT NULL,
    amount_rub            NUMERIC(12, 2) NOT NULL CHECK (amount_rub > 0),
    method                VARCHAR(20) NOT NULL CHECK (method IN ('crypto', 'card', 'sbp')),
    requisites            TEXT NOT NULL,
    crypto                VARCHAR(20),
    network               VARCHAR(20),
    status                VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'approved', 'rejected', 'cancelled')
    ),
    tx_hash               TEXT,
    receipt_file          TEXT,
    reject_reason         TEXT,
    admin_message_id      BIGINT,
    created_by_username   VARCHAR(255),
    processed_by_username VARCHAR(255),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_casino_creator_withdrawals_user ON casino_creator_withdrawals (telegram_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_casino_creator_withdrawals_status ON casino_creator_withdrawals (status, created_at DESC);

COMMENT ON TABLE casino_creator_withdrawals IS 'Заявки на вывод средств создателя кода';

-- Настройки казино
CREATE TABLE IF NOT EXISTS casino_settings (
    key         VARCHAR(64) PRIMARY KEY,
    value       JSONB NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  VARCHAR(255)
);

COMMENT ON TABLE casino_settings IS 'Настройки казино (комиссии, лимиты, включение игр)';

-- Начальные настройки
INSERT INTO casino_settings (key, value, description) VALUES
    ('commission_rate', '{"percent": 15.0}', 'Общая комиссия казино (процент от проигранной ставки)'),
    ('creator_cut_percent', '{"percent": 5.0}', 'Доля создателя кода от общей комиссии'),
    ('referral_l1_percent', '{"percent": 2.0}', 'Доля реферера L1 от общей комиссии'),
    ('referral_l2_percent', '{"percent": 2.0}', 'Доля реферера L2 от общей комиссии'),
    ('min_bet_rub', '{"amount": 10.0}', 'Минимальная ставка (рубли)'),
    ('max_bet_rub', '{"amount": 100000.0}', 'Максимальная ставка (рубли)'),
    ('min_withdrawal_rub', '{"amount": 100.0}', 'Минимальная сумма вывода для создателя'),
    ('enabled_games', '{"pvp_dice": true, "pvp_darts": true, "pvp_bowling": true, "pvp_football": true, "pvp_basketball": true, "baccara": true, "blackjack": true, "raffle": true}', 'Включение/выключение игр'),
    ('creator_telegram_id', '{"telegram_id": null}', 'Telegram ID создателя кода (владелец 5% комиссии)')
ON CONFLICT (key) DO NOTHING;

-- Hold балансов для игр (временная блокировка средств)
CREATE TABLE IF NOT EXISTS casino_balance_holds (
    id              BIGSERIAL PRIMARY KEY,
    hold_id         VARCHAR(128) NOT NULL UNIQUE,
    telegram_id     BIGINT NOT NULL,
    game_id         VARCHAR(64) NOT NULL,
    amount_rub      NUMERIC(12, 2) NOT NULL CHECK (amount_rub > 0),
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'confirmed', 'released', 'expired')
    ),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    confirmed_at    TIMESTAMPTZ,
    released_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_casino_holds_user ON casino_balance_holds (telegram_id, status);
CREATE INDEX IF NOT EXISTS idx_casino_holds_game ON casino_balance_holds (game_id);
CREATE INDEX IF NOT EXISTS idx_casino_holds_status ON casino_balance_holds (status, expires_at);

COMMENT ON TABLE casino_balance_holds IS 'Временные блокировки баланса для активных игр';
COMMENT ON COLUMN casino_balance_holds.hold_id IS 'Уникальный идентификатор холда (casino-{game_id}-{role})';

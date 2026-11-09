-- Wagering lock: депозит зачисляется по номиналу (0% комиссии на входе),
-- но заперт к ВЫВОДУ, пока игрок не наберёт требуемую сумму комиссии казино
-- (по умолчанию 21% депозита) на завершённых играх. Ставки при этом разрешены.
-- Запускать после add_casino_deposit_credits.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS casino_wagering_locks (
    id                       BIGSERIAL PRIMARY KEY,
    deal_id                  INTEGER NOT NULL REFERENCES external_deals(id) ON DELETE RESTRICT,
    telegram_id              BIGINT NOT NULL CHECK (telegram_id > 0),
    deposit_rub              NUMERIC(14, 2) NOT NULL CHECK (deposit_rub > 0),
    required_commission_rub  NUMERIC(14, 2) NOT NULL CHECK (required_commission_rub >= 0),
    unlocked                 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    unlocked_at              TIMESTAMPTZ,
    UNIQUE (deal_id)
);

-- Активные (ещё не отыгранные) локи игрока — горячий путь при расчёте доступного вывода.
CREATE INDEX IF NOT EXISTS idx_casino_wagering_locks_active
    ON casino_wagering_locks (telegram_id)
    WHERE unlocked = FALSE;

COMMENT ON TABLE casino_wagering_locks IS
    'Запертая к выводу сумма депозита; тает по мере накопления комиссии казино с завершённых игр игрока';
COMMENT ON COLUMN casino_wagering_locks.required_commission_rub IS
    'Сумма комиссии казино (в ₽), которую игрок должен набрать на finished-играх с момента депозита, чтобы снять лок';
COMMENT ON COLUMN casino_wagering_locks.unlocked IS
    'TRUE, когда порог отыгрыша достигнут и депозит перестаёт удерживать вывод';

GRANT ALL PRIVILEGES ON TABLE casino_wagering_locks TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE casino_wagering_locks_id_seq TO exchange_bot;

COMMIT;

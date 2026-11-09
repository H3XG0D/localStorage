-- Добавление SLA метрик для операторов: время обработки заявок
-- claimed_at — когда оператор взял заявку в работу
-- operator_completed_at — когда оператор завершил заявку (COMPLETED/PAID)

ALTER TABLE orders
ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS operator_completed_at TIMESTAMPTZ;

-- Заполнить claimed_at из finance_claimed_at где есть
UPDATE orders
SET claimed_at = finance_claimed_at
WHERE finance_claimed_at IS NOT NULL
  AND claimed_at IS NULL;

-- Заполнить operator_completed_at из updated_at для завершённых заявок
UPDATE orders
SET operator_completed_at = updated_at
WHERE status IN ('COMPLETED', 'PAID')
  AND operator_completed_at IS NULL;

-- Индексы для быстрого расчёта SLA
CREATE INDEX IF NOT EXISTS idx_orders_claimed_at ON orders(claimed_at) WHERE claimed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_operator_completed_at ON orders(operator_completed_at) WHERE operator_completed_at IS NOT NULL;

COMMENT ON COLUMN orders.claimed_at IS 'Время когда оператор взял заявку в работу (для SLA time_to_claim)';
COMMENT ON COLUMN orders.operator_completed_at IS 'Время когда оператор завершил заявку (для SLA time_to_complete)';

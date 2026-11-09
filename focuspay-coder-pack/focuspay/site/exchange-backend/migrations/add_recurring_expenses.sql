-- Миграция: добавление таблицы recurring_expenses для отслеживания подписок и периодических расходов
-- Также расширяет manual_expenses для ROI-трекинга и связей с метриками

-- Создание таблицы периодических расходов (подписки)
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('subscription', 'salary', 'marketing', 'other')),
    amount_rub NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    billing_cycle TEXT NOT NULL CHECK (billing_cycle IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'annual')),
    next_billing_date DATE NOT NULL,
    last_billing_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    
    -- ROI трекинг
    expected_return_rub NUMERIC(14, 2),
    actual_return_rub NUMERIC(14, 2),
    roi_percent NUMERIC(8, 2),
    
    -- Связи с метриками для автоматического расчёта ROI
    linked_partner_id INT, -- внешний ключ на promo_campaigns(id), но без REFERENCES для гибкости
    linked_promo_code VARCHAR(64),
    linked_metric_key TEXT, -- произвольная привязка к метрике
    
    comment TEXT,
    created_by_web_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Индексы для производительности
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_next_billing 
    ON recurring_expenses(next_billing_date) 
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_recurring_expenses_category 
    ON recurring_expenses(category, is_active);

CREATE INDEX IF NOT EXISTS idx_recurring_expenses_active 
    ON recurring_expenses(is_active, next_billing_date);

-- Расширение таблицы manual_expenses для связи с recurring и ROI-трекинга
ALTER TABLE manual_expenses 
    ADD COLUMN IF NOT EXISTS linked_recurring_id BIGINT,
    ADD COLUMN IF NOT EXISTS expected_return_rub NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS actual_return_rub NUMERIC(14, 2),
    ADD COLUMN IF NOT EXISTS roi_percent NUMERIC(8, 2),
    ADD COLUMN IF NOT EXISTS linked_partner_id INT,
    ADD COLUMN IF NOT EXISTS linked_promo_code VARCHAR(64);

-- Индекс для связи manual_expenses -> recurring_expenses
CREATE INDEX IF NOT EXISTS idx_manual_expenses_recurring 
    ON manual_expenses(linked_recurring_id) 
    WHERE linked_recurring_id IS NOT NULL;

-- Комментарии для документации схемы
COMMENT ON TABLE recurring_expenses IS 'Периодические расходы и подписки с автоматическим отслеживанием ROI';
COMMENT ON COLUMN recurring_expenses.billing_cycle IS 'Частота оплаты: weekly, biweekly, monthly, quarterly, annual';
COMMENT ON COLUMN recurring_expenses.next_billing_date IS 'Дата следующего платежа (используется для напоминаний)';
COMMENT ON COLUMN recurring_expenses.roi_percent IS 'ROI в процентах: ((actual_return - amount) / amount) * 100';
COMMENT ON COLUMN recurring_expenses.linked_partner_id IS 'Связь с партнёром для автоматического расчёта ROI из оборота';
COMMENT ON COLUMN recurring_expenses.linked_promo_code IS 'Связь с промо-кодом для расчёта ROI из кампании';
COMMENT ON COLUMN recurring_expenses.linked_metric_key IS 'Произвольная связь с метрикой (например, "new_users", "total_orders")';

-- Recurring expenses with billing cycles and ROI tracking
-- Created: 2026-08-21

CREATE TABLE IF NOT EXISTS recurring_expenses (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('subscription', 'salary', 'marketing', 'other')),
    amount_rub NUMERIC(14, 2) NOT NULL CHECK (amount_rub > 0),
    billing_cycle TEXT NOT NULL CHECK (billing_cycle IN ('weekly', 'biweekly', 'monthly', 'quarterly', 'annual')),
    next_billing_date DATE NOT NULL,
    last_billing_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    
    -- ROI tracking
    expected_return_rub NUMERIC(14, 2),
    actual_return_rub NUMERIC(14, 2),
    roi_percent NUMERIC(8, 2),
    
    -- Link to metrics for automatic ROI calculation
    linked_partner_id INT,
    linked_promo_code VARCHAR(64),
    linked_metric_key TEXT,
    
    comment TEXT,
    created_by_web_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recurring_expenses_next_billing 
    ON recurring_expenses(next_billing_date) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_category 
    ON recurring_expenses(category, is_active);
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_active 
    ON recurring_expenses(is_active) WHERE is_active = true;

-- Extend manual_expenses with ROI tracking
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS linked_recurring_id BIGINT REFERENCES recurring_expenses(id);
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS expected_return_rub NUMERIC(14, 2);
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS actual_return_rub NUMERIC(14, 2);
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS roi_percent NUMERIC(8, 2);
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS linked_partner_id INT;
ALTER TABLE manual_expenses ADD COLUMN IF NOT EXISTS linked_promo_code VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_manual_expenses_recurring 
    ON manual_expenses(linked_recurring_id) WHERE linked_recurring_id IS NOT NULL;

-- Расширение manual_expenses для BI-страницы "Финансы":
-- title/comment/expense_date + обратная совместимость с operation_type.

ALTER TABLE manual_expenses
    ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';

ALTER TABLE manual_expenses
    ADD COLUMN IF NOT EXISTS comment TEXT NOT NULL DEFAULT '';

ALTER TABLE manual_expenses
    ADD COLUMN IF NOT EXISTS expense_date DATE NOT NULL DEFAULT CURRENT_DATE;

-- Backfill: старые записи хранили "тип операции" в operation_type.
UPDATE manual_expenses
SET
    title = NULLIF(TRIM(COALESCE(title, '')), ''),
    comment = NULLIF(TRIM(COALESCE(comment, '')), '');

UPDATE manual_expenses
SET title = operation_type
WHERE title IS NULL OR title = '';

-- Для исторических записей выставляем expense_date равным дате созданий,
-- чтобы новая фильтрация совпадала со старым created_at.
UPDATE manual_expenses
SET expense_date = created_at::date;

CREATE INDEX IF NOT EXISTS idx_manual_expenses_category_expense_date
    ON manual_expenses (category, expense_date DESC);


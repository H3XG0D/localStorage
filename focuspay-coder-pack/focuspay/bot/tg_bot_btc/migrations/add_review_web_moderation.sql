-- Веб-модерация отзывов: аудит оператора + file_id скрина для превью.

ALTER TABLE review_submissions
    ADD COLUMN IF NOT EXISTS moderated_by_operator_id INTEGER REFERENCES operator_accounts(id),
    ADD COLUMN IF NOT EXISTS source_photo_file_id VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_review_submissions_operator
    ON review_submissions (moderated_by_operator_id)
    WHERE moderated_by_operator_id IS NOT NULL;

COMMENT ON COLUMN review_submissions.moderated_by_operator_id IS
    'Оператор, одобривший/отклонивший отзыв в веб-панели';
COMMENT ON COLUMN review_submissions.source_photo_file_id IS
    'Telegram file_id скрина для превью в панели';

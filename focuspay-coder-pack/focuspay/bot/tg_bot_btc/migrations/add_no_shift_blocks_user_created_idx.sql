-- Повторные попытки того же клиента за час: быстрый EXISTS по user_id.
CREATE INDEX IF NOT EXISTS idx_no_shift_blocks_user_created
    ON no_shift_requisites_blocks (user_id, created_at DESC);

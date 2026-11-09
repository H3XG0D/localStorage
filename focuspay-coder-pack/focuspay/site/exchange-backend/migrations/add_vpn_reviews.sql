-- VPN reviews share the exchange moderation queue, with their own weekly bonus.

ALTER TABLE review_submissions
    ADD COLUMN IF NOT EXISTS product VARCHAR(16) NOT NULL DEFAULT 'exchange',
    ADD COLUMN IF NOT EXISTS source_photo_path TEXT;

ALTER TABLE review_bonus_claims
    ADD COLUMN IF NOT EXISTS product VARCHAR(16) NOT NULL DEFAULT 'exchange';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'review_submissions_product_chk'
    ) THEN
        ALTER TABLE review_submissions
            ADD CONSTRAINT review_submissions_product_chk
            CHECK (product IN ('exchange', 'vpn'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'review_bonus_claims_product_chk'
    ) THEN
        ALTER TABLE review_bonus_claims
            ADD CONSTRAINT review_bonus_claims_product_chk
            CHECK (product IN ('exchange', 'vpn'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_review_submissions_vpn_published
    ON review_submissions (user_id, moderated_at DESC)
    WHERE product = 'vpn' AND status = 'published';

COMMENT ON COLUMN review_submissions.product IS
    'exchange = отзыв об обмене (бонус раз в сутки); vpn = отзыв о VPN (раз в 7 дней)';
COMMENT ON COLUMN review_submissions.source_photo_path IS
    'Файл скрина VPN на диске. Бот FocusPay не видит сообщения бота VPN, поэтому публикует файл, а не пересылку.';
COMMENT ON COLUMN review_bonus_claims.product IS
    'Чей бонус: суточный лимит обмена не смотрит строки vpn, недельный лимит VPN не смотрит exchange';

-- Reminder kind "review": one row per 7-day window (ends_at = window start).
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relname = 'vpn_notifications'
          AND n.nspname = current_schema()
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%kind%'
    LOOP
        EXECUTE format('ALTER TABLE vpn_notifications DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;

ALTER TABLE vpn_notifications
    ADD CONSTRAINT vpn_notifications_kind_check
    CHECK (kind IN ('soon', 'ended', 'review'));

-- Купон автора FocusPayPartnersBot: скидка на обмен, привязка к Telegram автора.
-- Зеркало: site/exchange-backend/migrations/add_author_promo.sql

ALTER TABLE promo_campaigns
    ADD COLUMN IF NOT EXISTS author_telegram_id BIGINT,
    ADD COLUMN IF NOT EXISTS author_video_id INTEGER,
    ADD COLUMN IF NOT EXISTS issued_for VARCHAR(32);

COMMENT ON COLUMN promo_campaigns.author_telegram_id IS
    'Telegram автора партнёрского бота. Не пусто — купон скидки на обмен, не реферальный партнёр.';
COMMENT ON COLUMN promo_campaigns.author_video_id IS
    'id ролика в SQLite партнёрского бота, за который выдан купон.';
COMMENT ON COLUMN promo_campaigns.issued_for IS
    'first_video — купон за первый принятый ролик; extra — следующий код автора.';

CREATE INDEX IF NOT EXISTS idx_promo_campaigns_author
    ON promo_campaigns (author_telegram_id)
    WHERE author_telegram_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_promo_campaigns_author_first_video
    ON promo_campaigns (author_telegram_id)
    WHERE issued_for = 'first_video' AND author_telegram_id IS NOT NULL;

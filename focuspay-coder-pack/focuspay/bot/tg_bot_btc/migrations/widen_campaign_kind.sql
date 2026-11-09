-- campaign_kind был VARCHAR(16), а значение 'exchange_discount' = 17 символов.
-- Расширяем, чтобы создание скидочных промокодов не падало.
ALTER TABLE promo_campaigns
    ALTER COLUMN campaign_kind TYPE VARCHAR(32);

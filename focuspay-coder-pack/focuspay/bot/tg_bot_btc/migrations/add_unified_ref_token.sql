-- Единая реферальная ссылка: у каждого пользователя всегда есть ref_token.
--
-- Стратегия НЕ разрушающая: существующие токены (bot_users.ref_token и
-- promo_campaigns.ref_token у партнёров) НЕ перезаписываются, чтобы старые
-- ссылки (uref_/invite и ref_/ref) продолжали работать. Единый показываемый
-- токен выбирается в рантайме (services/user_referral_db.get_canonical_ref_token):
-- для партнёра — promo_campaigns.ref_token, иначе — bot_users.ref_token.
--
-- Здесь только backfill: всем пользователям без токена выдаём токен, чтобы
-- ссылка была доступна сразу (в т.ч. при создании аккаунта на сайте).

BEGIN;

-- Backfill недостающих токенов (MD5 → подмножество [a-f0-9] ⊂ [a-z0-9]).
DO $$
DECLARE
    r RECORD;
    new_token TEXT;
BEGIN
    FOR r IN SELECT user_id FROM bot_users WHERE ref_token IS NULL LOOP
        LOOP
            new_token := LOWER(SUBSTRING(
                MD5(random()::text || r.user_id::text || clock_timestamp()::text)
                FROM 1 FOR 18
            ));
            EXIT WHEN NOT EXISTS (
                SELECT 1 FROM bot_users WHERE ref_token = new_token
            );
        END LOOP;
        UPDATE bot_users SET ref_token = new_token WHERE user_id = r.user_id;
    END LOOP;
END $$;

COMMIT;

-- Диагностика (информационно): партнёры, у которых bot_users.ref_token и
-- promo_campaigns.ref_token различаются. Это НЕ ошибка — обе ссылки резолвятся,
-- показывается канонический (promo) токен.
-- SELECT pa.telegram_user_id, bu.ref_token AS user_token, pc.ref_token AS promo_token
-- FROM partner_accounts pa
-- JOIN promo_campaigns pc ON pc.id = pa.promo_campaign_id
-- JOIN bot_users bu ON bu.user_id = pa.telegram_user_id
-- WHERE pa.is_active AND pc.is_active
--   AND bu.ref_token IS DISTINCT FROM pc.ref_token;

-- Полная очистка операционных данных (заявки, балансы, чаты, гости)
-- Сохраняются: web_users (admin), operator_accounts, promo_campaigns, partner_accounts, admin_payroll_roles
BEGIN;

DELETE FROM web_chat_messages;
DELETE FROM web_chat_threads;
DELETE FROM web_guest_sessions;
DELETE FROM web_order_ip_log;

DELETE FROM promo_bonus_usages;
DELETE FROM promo_gift_redemptions;
DELETE FROM promo_attributions;
DELETE FROM user_cashback_ledger;
DELETE FROM user_referral_ledger;
DELETE FROM user_referral_withdrawals;
DELETE FROM user_referral_attributions;
DELETE FROM partner_ledger;

DELETE FROM operator_payroll_ledger;
DELETE FROM operator_payout_requests;
DELETE FROM operator_shift_balances;
DELETE FROM operator_shifts;

DELETE FROM site_reviews;
DELETE FROM order_groups;
DELETE FROM orders;

-- Клиенты бота (кроме telegram id админа)
DELETE FROM bot_users
WHERE user_id NOT IN (
    SELECT telegram_user_id FROM web_users
    WHERE is_admin = TRUE AND telegram_user_id IS NOT NULL
);

-- Лишние web-профили (не админ)
DELETE FROM web_users WHERE is_admin IS NOT TRUE;

COMMIT;

VACUUM (ANALYZE);

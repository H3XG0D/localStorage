-- Безопасная очистка production БД (реальные PAID/COMPLETED не трогаем)
BEGIN;

-- Тестовая заявка из seed
DELETE FROM promo_bonus_usages WHERE order_id = 'TEST0001';
DELETE FROM user_cashback_ledger
WHERE order_id = 'TEST0001'
   OR order_id IN ('hold-TEST0001', 'spend-TEST0001');
DELETE FROM user_referral_ledger WHERE order_id = 'TEST0001';
DELETE FROM partner_ledger WHERE order_id = 'TEST0001';
DELETE FROM orders WHERE order_id = 'TEST0001';

-- Гостевые сессии без активных/успешных заявок
DELETE FROM web_guest_sessions gs
WHERE NOT EXISTS (
    SELECT 1 FROM orders o
    WHERE o.user_id = gs.synthetic_user_id
      AND o.status IN ('CREATED', 'PENDING', 'AWAITING_CHECK', 'COMPLETED', 'PAID')
);

-- Пустые гостевые чаты (без сообщений, без Telegram)
DELETE FROM web_chat_threads t
WHERE t.telegram_user_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM web_chat_messages m WHERE m.thread_id = t.id);

COMMIT;

VACUUM (ANALYZE);

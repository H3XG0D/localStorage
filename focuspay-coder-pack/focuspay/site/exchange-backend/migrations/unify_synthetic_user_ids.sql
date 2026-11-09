-- Единый неймспейс отрицательных synthetic user_id для guest и password-регистрации.
-- Раньше web_guest_user_id_seq и web_client_user_id_seq независимо выдавали -1,-2,…
-- → новый аккаунт мог унаследовать чужие orders/cashback со старого guest id.

CREATE SEQUENCE IF NOT EXISTS web_synthetic_user_id_seq;

DO $$
DECLARE
  guest_lv bigint := 0;
  client_lv bigint := 0;
  max_guest_abs bigint := 0;
  max_client_abs bigint := 0;
  start_at bigint;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'web_guest_user_id_seq') THEN
    SELECT last_value INTO guest_lv FROM web_guest_user_id_seq;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'web_client_user_id_seq') THEN
    SELECT last_value INTO client_lv FROM web_client_user_id_seq;
  END IF;

  SELECT COALESCE(MAX(ABS(synthetic_user_id)), 0) INTO max_guest_abs
  FROM web_guest_sessions
  WHERE synthetic_user_id < 0
    AND ABS(synthetic_user_id) < 3000000000;

  SELECT COALESCE(MAX(ABS(client_user_id)), 0) INTO max_client_abs
  FROM web_users
  WHERE client_user_id IS NOT NULL
    AND client_user_id < 0
    AND ABS(client_user_id) < 3000000000;

  start_at := GREATEST(guest_lv, client_lv, max_guest_abs, max_client_abs, 1);
  PERFORM setval('web_synthetic_user_id_seq', start_at, true);

  -- Legacy sequences держим не ниже канона: любой старый код тоже уйдёт вперёд.
  IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'web_guest_user_id_seq') THEN
    PERFORM setval('web_guest_user_id_seq', start_at, true);
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'web_client_user_id_seq') THEN
    PERFORM setval('web_client_user_id_seq', start_at, true);
  END IF;
END $$;

COMMENT ON SEQUENCE web_synthetic_user_id_seq IS
  'Shared positive counter; app stores synthetic ids as -nextval(). Guest + password.';

DO $$
BEGIN
  BEGIN
    GRANT USAGE, SELECT ON SEQUENCE web_synthetic_user_id_seq TO exchange_bot;
  EXCEPTION WHEN undefined_object THEN
    NULL;
  END;
END $$;

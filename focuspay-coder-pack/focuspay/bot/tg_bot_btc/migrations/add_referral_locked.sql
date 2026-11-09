-- Закрыть повторную привязку реферала (антиабуз вторых аккаунтов)
ALTER TABLE bot_users
    ADD COLUMN IF NOT EXISTS referral_locked BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN bot_users.referral_locked IS
    'TRUE — пользователь уже зашёл без реферала, повторная привязка запрещена';

-- Кто уже пользовался ботом без реферала — закрыть окно
UPDATE bot_users bu
SET referral_locked = TRUE
WHERE referral_locked = FALSE
  AND NOT EXISTS (
      SELECT 1 FROM user_referral_attributions a WHERE a.user_id = bu.user_id
  );

UPDATE bot_users SET pending_ref_token = NULL WHERE pending_ref_token IS NOT NULL;

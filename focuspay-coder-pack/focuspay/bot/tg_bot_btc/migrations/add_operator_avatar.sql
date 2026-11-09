-- Аватар оператора (file_id в хранилище uploads, URL с подписью).
ALTER TABLE operator_accounts
  ADD COLUMN IF NOT EXISTS avatar_file_id VARCHAR(32);

COMMENT ON COLUMN operator_accounts.avatar_file_id IS
  'Идентификатор файла аватара (jpg/png/webp/gif), до 2 МБ';

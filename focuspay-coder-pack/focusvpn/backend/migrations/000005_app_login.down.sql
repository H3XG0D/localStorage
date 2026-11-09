DROP TABLE IF EXISTS app_login_requests;

UPDATE plans SET max_devices = 3, updated_at = now() WHERE code = 'week';

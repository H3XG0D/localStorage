-- Partner cabinet: password change + Google Authenticator (TOTP)
ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS totp_secret TEXT,
    ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN partner_accounts.totp_secret IS 'TOTP secret for partner 2FA';
COMMENT ON COLUMN partner_accounts.totp_enabled IS 'Whether partner 2FA is active';

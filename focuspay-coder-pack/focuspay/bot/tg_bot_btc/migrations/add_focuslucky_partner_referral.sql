-- Opt-in: partner promo clients earn FocusLucky referral tickets
-- for this partner when the buyer has no personal referrer.
ALTER TABLE partner_accounts
    ADD COLUMN IF NOT EXISTS focuslucky_referral_enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN partner_accounts.focuslucky_referral_enabled IS
    'When true, paid deals of promo clients without a personal referrer add FocusLucky referral tickets to this partner.';

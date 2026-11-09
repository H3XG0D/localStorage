# Partner referral links through captcha — 2026-09-14

User-authorized production fix for murder033. Campaign referral tokens were looked up only in bot_users before captcha. Their pending_ref_token was not saved, and successful captcha processing could seal the referral gate without recording the campaign.

Changed only bot/tg_bot_btc/services/user_referral_attribution.py on production. Pending-token validation now also accepts active eligible campaign tokens. Pending-token application falls back to the existing promo resolver only when the personal resolver returns invalid; locked and self outcomes do not enter that fallback. Existing captcha handler consumes the persisted token. No pricing or commission formulas changed.

Validation: regression failed before the fix at campaign-token persistence. After the fix, 36 referral/link/captcha tests passed locally, and the two new regression tests passed against deployed Python code with mocked database access. Production tg-bot.service restarted successfully at 13:26 UTC and was active/running with NRestarts=0. Real Telegram signup was not simulated with a live account.

Code backup on production: /opt/tg_bot_btc/services/user_referral_attribution.py.bak-murder-20260914T132629Z
Deployed SHA-256: a468176671abc67e4dea8623e7b13cb582907ff5bae4e96fc79fceb8fccc49c1

Recovery was limited to campaign PRXORKTA (62). Eligibility required that the earliest start-log entry contained its token within five seconds of first_seen_at, captcha was subsequently passed, and neither personal nor campaign attribution existed. The partner himself was excluded. Recovered 57 promo_attributions, with assigned_at set to the recorded captcha completion time. Existing referral locks were retained; no prior attributions were overwritten.

Recovery used a transaction, table locks against competing attribution/ledger writes, and locked relevant orders. A server-only JSON backup of the campaign, affected users, orders, and prior ledger was saved before writing: /root/focuspay-backups/murder-referral-20260914T132848Z.json (mode 0600).

Of 34 closed orders for the recovered users, ten received a total of 693.02 RUB via the deployed accrue_partner_commission function, using persisted service profit and the campaign's fixed 40% rate. A dry run rolled back before the committed run. Twenty-two orders lack persisted service-profit economics and were deliberately not recalculated using today's pricing. Two orders have nonpositive saved profit. Historical compensation for those 22 orders remains unresolved and requires historical cost evidence; 693.02 RUB is not a claim that all historical losses have been settled.

No commits, pushes, or messages to customers were made. The broader working tree contained unrelated changes and was not deployed.

# Global referral recovery — 2026-09-14

User explicitly requested recovery for everyone after the campaign-captcha fix and murder-only recovery.

The reusable script is bot/tg_bot_btc/scripts/recover_referral_attributions.py. Its default mode is a read-only plan; writes require --apply and the SHA-256 digest of the exact reviewed plan. It backs up affected users, orders, and the plan before applying, locks attribution/ledger tables and affected rows, checks each resulting amount and recipient, and re-plans after commit to verify idempotency. No notifications are sent.

Eligibility for lost links: earliest start log within five seconds of first_seen_at, resolvable personal or active partner token, no existing personal or promo attribution, no self-referral. Passed captcha creates the attribution; unfinished captcha restores pending_ref_token and reopens its gate. Existing attributions are never reassigned. Personal-to-partner dual-write gaps and missing commission ledger entries are also scanned.

Historical economics for missing BUY snapshots uses the repository's existing scripts/reprice_closed_buy_economics.py policy, present since cd08ff3: before 2026-08-17 Moscow, 20% markup; afterward 21% automatic or 22% manual, with recorded operator spread taking precedence. Recorded fees, quantities, rate, and cashback are preserved. Null historical card fee follows the existing policy's 12% convention. These are reconstructed accounting snapshots, not a claim of recovered original market-price records. Original snapshots are in the backup. Stored service-profit snapshots are not repriced.

Committed at 2026-09-14 13:36 UTC:

- 131 additional attributions restored.
- 73 pending tokens restored for unfinished captcha.
- 81 commissions totaling 3692.00 RUB credited via production accrual functions.
- 214 missing BUY economics snapshots reconstructed with provenance tags.
- murder received an additional 624.13 RUB, beyond the earlier 693.02 RUB.
- No missing ordinary-user commissions were present in the initial audit; ordinary-user links were included in recovery.

Production backup: /root/focuspay-backups/all-referrals-20260914T133641Z.json
Receipt: /root/focuspay-backups/all-referrals-20260914T133641Z-receipt.json
Plan digest: 355063589b4c9048e88e86aee066eb2fb2333dd9c66b5218b241f93493a75e26

Fresh post-commit plan: zero eligible missing attributions, zero pending-token fixes, zero calculable missing credits. Remaining exclusions: 214 nonpositive/rounded-zero commissions, 99 orders created before their attribution, two SELL orders with no historical service profit. These are not recorded as paid compensation.

The two SELL orders are OPAB5C4270D2E25864 and OPE366181492A465C2, dated August 5. Historical default source, a nearby ledger entry, and later saved SELL snapshots disagree about settings; no original snapshot or payroll split exists for these two. Asked the user whether to calculate them under current rules or await historical evidence. Do not silently assume an answer.

Payroll split profit was investigated as a fallback. It is a salary base after other deductions, not directly interchangeable with service_profit_rub. It was not substituted into referral calculations.

Validation: five recovery tests plus existing referral tests (16 total) passed; original captcha/link suite previously passed 36 tests, and new captcha regressions also passed against deployed code. All writes committed atomically and post-commit replanning reported zero repeatable mutations. No new bot/service deployment was required for this data recovery; the earlier captcha fix remains deployed. No git commits/pushes or customer messages.

# Миграции PostgreSQL (exchange_bot)

Применяйте **по порядку** на проде. Скрипт `deploy/deploy-partners.sh` запускает подмножество; при ручном деплое сверяйтесь с этим списком.

## Базовые (tg_bot_btc)

1. `create_tables.sql`
2. `add_bot_users.sql`
3. `add_promo_tables.sql` · `add_promo_bonus_usage.sql` · `add_promo_ref_token.sql` · `add_promo_gift_redemptions.sql`
4. `add_merchant_order_id.sql` · `add_sub_token.sql`
5. `add_user_referral.sql` · `add_payin_split_cashback.sql` · `add_referral_discount_spend.sql`
6. `add_payout_tx.sql` · `add_withdrawal_payout_tx.sql` · `add_payment_snapshot.sql`
7. `add_financial_safeguards.sql` · `add_card_fee_pct.sql`
8. `add_campaign_fixed_bonus.sql`
9. `add_web_guest_sessions.sql` · `add_web_order_ip.sql` · `add_web_chat.sql` · `add_chat_images.sql`
10. `add_site_reviews.sql`
11. Операторы: `add_operator_accounts.sql` → shifts → id on orders → features → payout amounts → avatar → payroll
12. `add_owner_stale_alerts.sql`
13. `add_review_bonus_claims.sql`
14. `add_raffle.sql` — FocusLucky monthly raffle

## Exchange (репозиторий `exchange/backend/migrations`)

- `add_web_users.sql`, `telegram_only_web_users.sql`, партнёры, промо, отзывы, security log — см. `deploy/deploy-partners.sh`.

## Проверка на prod

```bash
ssh focuspay 'sudo -u postgres psql -d exchange_bot -c "\dt owner_stale_alerts"'
```

Ошибка «relation does not exist» — применить недостающий файл из списка выше.

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE app_settings IS 'Runtime business settings (tariffs, spreads, bonuses)';

INSERT INTO app_settings (key, value)
VALUES (
    'business',
    '{
        "buy_spread_auto_pct": 20,
        "buy_spread_manual_pct": 20,
        "sell_spread_pct": 5,
        "card_fee_auto_pct": 12,
        "card_fee_manual_pct": 14,
        "sell_profit_factor_pct": 75,
        "user_cashback_base_pct": 5,
        "user_cashback_tier_step_pct": 2,
        "user_cashback_tier_every_n": 5,
        "user_cashback_max_pct": 15,
        "user_referral_pct": 5,
        "review_bonus_text_rub": 50,
        "review_bonus_photo_rub": 100
    }'::jsonb
)
ON CONFLICT (key) DO NOTHING;

GRANT ALL PRIVILEGES ON TABLE app_settings TO exchange_bot;

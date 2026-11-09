-- Режим наценки: on_deal (к сумме) | on_turnover (по обороту)
ALTER TABLE external_exchangers
    ADD COLUMN IF NOT EXISTS markup_mode VARCHAR(16) NOT NULL DEFAULT 'on_deal'
    CHECK (markup_mode IN ('on_deal', 'on_turnover'));

COMMENT ON COLUMN external_exchangers.markup_mode IS
    'on_deal = base + pct%; on_turnover = client pays input, base = input * (1 - pct%)';

ALTER TABLE external_deals
    ADD COLUMN IF NOT EXISTS markup_mode VARCHAR(16);

UPDATE external_deals SET markup_mode = 'on_deal' WHERE markup_mode IS NULL;

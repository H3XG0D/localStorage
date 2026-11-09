-- Расширение типов partner_ledger для hold/spend при обмене (единый баланс)
ALTER TABLE partner_ledger DROP CONSTRAINT IF EXISTS partner_ledger_type_check;
ALTER TABLE partner_ledger ADD CONSTRAINT partner_ledger_type_check
    CHECK (type IN ('accrual', 'payout', 'adjustment', 'hold', 'spend'));

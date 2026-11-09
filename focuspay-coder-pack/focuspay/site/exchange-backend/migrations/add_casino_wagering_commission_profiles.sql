-- Два профиля комиссии казино: до и после выполнения wagering-условий.
-- Значения фиксируются в pricing_snapshot при commit исхода и не меняют историю игр.

BEGIN;

INSERT INTO casino_settings (key, value, description) VALUES
    ('wagering_percent', '{"percent": 21.0}', 'Требуемый объём ставок после депозита, процент от номинала'),
    ('commission_rate_wagering_active', '{"percent": 15.0}', 'Комиссия игр при незавершённом wagering-условии'),
    ('commission_rate_wagering_complete', '{"percent": 5.0}', 'Комиссия игр после выполнения всех wagering-условий'),
    ('creator_cut_percent_wagering_active', '{"percent": 3.0}', 'Доля создателя при комиссии 15%'),
    ('referral_l1_percent_wagering_active', '{"percent": 2.0}', 'Доля реферера L1 при комиссии 15%'),
    ('referral_l2_percent_wagering_active', '{"percent": 2.0}', 'Доля реферера L2 при комиссии 15%'),
    ('creator_cut_percent_wagering_complete', '{"percent": 1.0}', 'Доля создателя при комиссии 5%'),
    ('referral_l1_percent_wagering_complete', '{"percent": 0.5}', 'Доля реферера L1 при комиссии 5%'),
    ('referral_l2_percent_wagering_complete', '{"percent": 0.5}', 'Доля реферера L2 при комиссии 5%')
ON CONFLICT (key) DO NOTHING;

COMMIT;

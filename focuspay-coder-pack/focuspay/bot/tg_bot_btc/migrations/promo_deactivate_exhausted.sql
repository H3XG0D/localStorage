-- Промокоды с исчерпанным лимитом — помечаем неактивными
UPDATE promo_campaigns pc
SET is_active = FALSE, updated_at = now()
WHERE pc.is_active = TRUE
  AND pc.campaign_kind = 'fixed_rub'
  AND (
      SELECT COUNT(*)::int FROM promo_gift_redemptions pgr
      WHERE pgr.promo_code = pc.code
  ) >= pc.max_activations;

UPDATE promo_campaigns pc
SET is_active = FALSE, updated_at = now()
WHERE pc.is_active = TRUE
  AND pc.campaign_kind = 'partner'
  AND (
      SELECT COUNT(*)::int FROM promo_attributions pa
      WHERE pa.promo_code = pc.code
  ) >= pc.max_activations;

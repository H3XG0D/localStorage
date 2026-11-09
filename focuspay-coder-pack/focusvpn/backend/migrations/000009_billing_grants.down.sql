DROP INDEX IF EXISTS idx_billing_events_created;
DROP INDEX IF EXISTS uq_billing_events_one_trial;

ALTER TABLE billing_events
    DROP COLUMN IF EXISTS ends_at,
    DROP COLUMN IF EXISTS amount_kopecks,
    DROP COLUMN IF EXISTS plan_code,
    DROP COLUMN IF EXISTS kind;

DELETE FROM plans p
WHERE p.code IN ('month', 'q3', 'trial')
  AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.plan_id = p.id);

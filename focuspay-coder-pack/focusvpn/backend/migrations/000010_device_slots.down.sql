DELETE FROM billing_events WHERE kind = 'device';

ALTER TABLE billing_events DROP CONSTRAINT IF EXISTS billing_events_kind_check;
ALTER TABLE billing_events
  ADD CONSTRAINT billing_events_kind_check CHECK (kind IN ('paid', 'trial'));

UPDATE plans SET max_devices = 3, updated_at = now() WHERE code IN ('month', 'q3');

-- Extra device seats are billing events (kind = device), not extra subscription days.
-- Sellable plans are one seat; further phones are purchased separately.

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
    WHERE con.conrelid = 'billing_events'::regclass
      AND con.contype = 'c'
      AND att.attname = 'kind'
  LOOP
    EXECUTE format('ALTER TABLE billing_events DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE billing_events
  ADD CONSTRAINT billing_events_kind_check CHECK (kind IN ('paid', 'trial', 'device'));

UPDATE plans SET max_devices = 1, updated_at = now()
WHERE code IN ('week', 'month', 'q3', 'trial');

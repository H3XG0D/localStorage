-- Extra device seats are purchases (kind = device). They spend the balance and
-- do not extend the VPN subscription.

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
    WHERE con.conrelid = 'vpn_purchases'::regclass
      AND con.contype = 'c'
      AND att.attname = 'kind'
  LOOP
    EXECUTE format('ALTER TABLE vpn_purchases DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;

ALTER TABLE vpn_purchases
  ADD CONSTRAINT vpn_purchases_kind_check CHECK (kind IN ('paid', 'trial', 'device'));

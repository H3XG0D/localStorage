-- Solo house dice: one human vs N visual house bots. Shared 2–6 lobby is no longer the default.
BEGIN;

ALTER TABLE casino_house_tables DROP CONSTRAINT IF EXISTS casino_house_tables_max_seats_check;
ALTER TABLE casino_house_tables
    ADD CONSTRAINT casino_house_tables_max_seats_check CHECK (max_seats BETWEEN 1 AND 6);

COMMENT ON TABLE casino_house_tables IS
    'Web cub vs house. Solo tables use max_seats=1; each human seat settles with calculate_house_settlement. Not V2 pot.';

COMMIT;

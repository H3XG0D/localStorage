-- Снимок наличия реквизитов из ответа стороннего бота на /reki.
-- Только агрегат по коридорам сумм: номеров карт здесь нет и быть не должно.
-- Каждый опрос переписывает обе таблицы целиком в одной транзакции.

CREATE TABLE IF NOT EXISTS reki_snapshot_meta (
    sub_token   TEXT PRIMARY KEY,
    count       INT NOT NULL DEFAULT 0,
    total_rub   NUMERIC(14, 2) NOT NULL DEFAULT 0,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reki_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    sub_token     TEXT NOT NULL,
    min_rub       NUMERIC(14, 2) NOT NULL,
    max_rub       NUMERIC(14, 2) NOT NULL,
    available_rub NUMERIC(14, 2) NOT NULL,
    snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS reki_snapshots_token_idx
    ON reki_snapshots (sub_token, min_rub);

GRANT ALL PRIVILEGES ON TABLE reki_snapshots TO exchange_bot;
GRANT ALL PRIVILEGES ON TABLE reki_snapshot_meta TO exchange_bot;
GRANT USAGE, SELECT ON SEQUENCE reki_snapshots_id_seq TO exchange_bot;

COMMENT ON TABLE reki_snapshots IS
    'Коридоры свободных сумм из /reki. Подсказка по наличию, не источник реквизитов.';
COMMENT ON TABLE reki_snapshot_meta IS
    'Шапка секции /reki: число активных реквизитов и общий свободный остаток.';

"""Персистентное состояние signer: идемпотентность, суточные лимиты, anti-replay.

SQLite, а не память: после рестарта сервиса нельзя потерять знание о том, что
request_id уже отправлен — иначе основной сервер повторит запрос и монеты
уйдут дважды.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

STATUS_SENDING = "sending"
STATUS_SENT = "sent"
STATUS_REJECTED = "rejected"
STATUS_UNKNOWN = "unknown"


def _db_path() -> Path:
    return Path(settings.audit_path).parent / "signer.sqlite3"


def init() -> None:
    global _conn
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=FULL")
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payouts (
            request_id TEXT PRIMARY KEY,
            coin       TEXT NOT NULL,
            address    TEXT NOT NULL,
            amount     REAL NOT NULL,
            status     TEXT NOT NULL,
            txid       TEXT,
            reason     TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payouts_coin_created ON payouts (coin, created_at)"
    )
    cols = {r["name"] for r in _conn.execute("PRAGMA table_info(payouts)")}
    if "fee" not in cols:
        _conn.execute("ALTER TABLE payouts ADD COLUMN fee REAL")
    if "vsize" not in cols:
        _conn.execute("ALTER TABLE payouts ADD COLUMN vsize INTEGER")
    _ensure_deposit_addresses(_conn)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trusted_topups (
            txid     TEXT PRIMARY KEY,
            coin     TEXT NOT NULL,
            amount   REAL NOT NULL,
            note     TEXT,
            added_at INTEGER NOT NULL
        )
        """
    )
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_sigs (
            sig TEXT PRIMARY KEY,
            at  INTEGER NOT NULL
        )
        """
    )
    try:
        restored = restore_empty_tables_from_backup()
    except Exception:
        restored = {"deposits": 0, "payouts": 0}
    if restored["deposits"] or restored["payouts"]:
        import logging

        logging.getLogger("focuspay-signer").info(
            "restored signer state from backup deposits=%s payouts=%s",
            restored["deposits"],
            restored["payouts"],
        )


def _db() -> sqlite3.Connection:
    if _conn is None:
        init()
    assert _conn is not None
    return _conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "request_id": row["request_id"],
        "status": row["status"],
        "txid": row["txid"],
        "coin": row["coin"],
        "amount": row["amount"],
        "reason": row["reason"],
        "fee": row["fee"],
        "vsize": row["vsize"],
        "at": row["created_at"],
    }


def set_fee(request_id: str, fee: float, vsize: int | None) -> None:
    with _lock:
        _db().execute(
            "UPDATE payouts SET fee = ?, vsize = ?, updated_at = ? WHERE request_id = ?",
            (fee, vsize, int(time.time()), request_id),
        )


def get(request_id: str) -> dict[str, Any] | None:
    with _lock:
        cur = _db().execute(
            "SELECT * FROM payouts WHERE request_id = ?", (request_id,)
        )
        return row_to_dict(cur.fetchone())


def reserve(
    request_id: str, coin: str, address: str, amount: float
) -> tuple[bool, dict[str, Any] | None]:
    """(True, None) — заняли слот; (False, existing) — такой request_id уже был.

    Резерв пишется ДО отправки: падение между broadcast и записью не должно
    приводить к повторной отправке.
    """
    now = int(time.time())
    with _lock:
        db = _db()
        try:
            db.execute(
                """
                INSERT INTO payouts (
                    request_id, coin, address, amount, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, coin, address, amount, STATUS_SENDING, now, now),
            )
            return True, None
        except sqlite3.IntegrityError:
            cur = db.execute(
                "SELECT * FROM payouts WHERE request_id = ?", (request_id,)
            )
            return False, row_to_dict(cur.fetchone())


def finish(request_id: str, status: str, *, txid: str = "", reason: str = "") -> None:
    with _lock:
        _db().execute(
            """
            UPDATE payouts
            SET status = ?, txid = ?, reason = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (status, txid or None, reason or None, int(time.time()), request_id),
        )


def daily_total(coin: str) -> float:
    """Сумма за последние 24 часа по всему, что могло уйти в сеть."""
    since = int(time.time()) - 86_400
    with _lock:
        cur = _db().execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM payouts
            WHERE coin = ? AND created_at >= ? AND status IN (?, ?, ?)
            """,
            (coin.lower(), since, STATUS_SENDING, STATUS_SENT, STATUS_UNKNOWN),
        )
        return float(cur.fetchone()["total"] or 0)


def add_trusted_topup(coin: str, txid: str, amount: float, note: str = "") -> bool:
    """False — этот txid уже отмечен."""
    with _lock:
        try:
            _db().execute(
                """
                INSERT INTO trusted_topups (txid, coin, amount, note, added_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (txid.lower(), coin.lower(), float(amount), note or None, int(time.time())),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def trusted_topups(coin: str, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        cur = _db().execute(
            """
            SELECT txid, coin, amount, note, added_at FROM trusted_topups
            WHERE coin = ? ORDER BY added_at DESC LIMIT ?
            """,
            (coin.lower(), int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]


def fast_spend_txids(coin: str) -> set[str]:
    """Неподтверждённые выходы этих транзакций можно тратить: доверенные пополнения и наши выплаты."""
    with _lock:
        db = _db()
        topups = db.execute(
            "SELECT txid FROM trusted_topups WHERE coin = ?", (coin.lower(),)
        ).fetchall()
        sent = db.execute(
            """
            SELECT txid FROM payouts
            WHERE coin = ? AND txid IS NOT NULL AND status = ? AND created_at >= ?
            """,
            (coin.lower(), STATUS_SENT, int(time.time()) - 7 * 86_400),
        ).fetchall()
    return {str(r["txid"]).lower() for r in topups} | {str(r["txid"]).lower() for r in sent}


_DEPOSIT_DDL = """
CREATE TABLE deposit_addresses (
    coin       TEXT NOT NULL,
    address    TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    retired_at INTEGER,
    PRIMARY KEY (coin, address)
)
"""

_DEPOSIT_CURRENT_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_deposit_one_current
ON deposit_addresses (coin) WHERE retired_at IS NULL
"""


def _ensure_deposit_addresses(db: sqlite3.Connection) -> None:
    """Один текущий адрес на монету. Старые строки остаются и продолжают принимать."""
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deposit_addresses'"
    ).fetchone()
    if not exists:
        db.execute(_DEPOSIT_DDL)
        db.execute(_DEPOSIT_CURRENT_INDEX)
        return
    cols = {r["name"] for r in db.execute("PRAGMA table_info(deposit_addresses)")}
    if "retired_at" not in cols:
        db.execute("ALTER TABLE deposit_addresses RENAME TO deposit_addresses_legacy")
        db.execute(_DEPOSIT_DDL)
        db.execute(
            """
            INSERT INTO deposit_addresses (coin, address, created_at, retired_at)
            SELECT coin, address, created_at, NULL FROM deposit_addresses_legacy
            """
        )
        db.execute("DROP TABLE deposit_addresses_legacy")
    _collapse_extra_current(db)
    db.execute(_DEPOSIT_CURRENT_INDEX)


def _collapse_extra_current(db: sqlite3.Connection) -> None:
    """Если текущих несколько, оставляет самый новый. Остальные помечает сменёнными."""
    rows = db.execute(
        """
        SELECT coin, address, created_at
        FROM deposit_addresses
        WHERE retired_at IS NULL
        ORDER BY coin ASC, created_at DESC, address DESC
        """
    ).fetchall()
    seen: set[str] = set()
    now = int(time.time())
    for row in rows:
        coin = str(row["coin"])
        if coin in seen:
            db.execute(
                """
                UPDATE deposit_addresses SET retired_at = ?
                WHERE coin = ? AND address = ?
                """,
                (now, coin, row["address"]),
            )
        else:
            seen.add(coin)


def _current_unlocked(db: sqlite3.Connection, coin: str) -> str | None:
    row = db.execute(
        """
        SELECT address FROM deposit_addresses
        WHERE coin = ? AND retired_at IS NULL
        ORDER BY created_at DESC, address DESC
        LIMIT 1
        """,
        (coin,),
    ).fetchone()
    return str(row["address"]) if row else None


def deposit_address(coin: str) -> str | None:
    with _lock:
        return _current_unlocked(_db(), (coin or "").lower())


def list_deposit_addresses(coin: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        db = _db()
        if coin:
            rows = db.execute(
                """
                SELECT coin, address, retired_at
                FROM deposit_addresses
                WHERE coin = ?
                ORDER BY (retired_at IS NULL) DESC, created_at DESC
                """,
                (coin.lower(),),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT coin, address, retired_at
                FROM deposit_addresses
                ORDER BY coin ASC, (retired_at IS NULL) DESC, created_at DESC
                """
            ).fetchall()
    return [
        {"coin": row["coin"], "address": row["address"], "current": row["retired_at"] is None}
        for row in rows
    ]


def install_deposit_address(coin: str, address: str, *, only_if_empty: bool = False) -> str:
    """Делает address текущим. Прежний текущий остаётся в таблице."""
    name = (coin or "").strip().lower()
    addr = (address or "").strip()
    if name not in ("btc", "ltc") or len(addr) < 10:
        raise ValueError("bad_deposit_address")
    now = int(time.time())
    with _lock:
        db = _db()
        db.execute("BEGIN IMMEDIATE")
        try:
            current = _current_unlocked(db, name)
            if current == addr or (only_if_empty and current):
                db.execute("COMMIT")
                return current or addr
            if current:
                db.execute(
                    """
                    UPDATE deposit_addresses SET retired_at = ?
                    WHERE coin = ? AND retired_at IS NULL
                    """,
                    (now, name),
                )
            db.execute(
                """
                INSERT INTO deposit_addresses (coin, address, created_at, retired_at)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT (coin, address) DO UPDATE SET retired_at = NULL
                """,
                (name, addr, now),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    _request_wallet_backup()
    return addr


def save_deposit_address(coin: str, address: str) -> str:
    """Первый адрес монеты остаётся текущим, пока его явно не сменят."""
    return install_deposit_address(coin, address, only_if_empty=True)


def _request_wallet_backup() -> None:
    """Сигнал root-таймеру снять backupwallet. Сам подписант ключи не копирует."""
    try:
        path = _db_path().parent / "wallet-backup.requested"
        path.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass


def _copy_deposit_rows(src: sqlite3.Connection, live: sqlite3.Connection) -> int:
    """Копирует историю адресов. Текущим остаётся один, самый новый несменённый."""
    cols = {r["name"] for r in src.execute("PRAGMA table_info(deposit_addresses)")}
    if "retired_at" in cols:
        rows = src.execute(
            "SELECT coin, address, created_at, retired_at FROM deposit_addresses"
        ).fetchall()
        payload = [
            (r["coin"], r["address"], r["created_at"], r["retired_at"]) for r in rows
        ]
    else:
        rows = src.execute(
            "SELECT coin, address, created_at FROM deposit_addresses"
        ).fetchall()
        payload = [(r["coin"], r["address"], r["created_at"], None) for r in rows]
    live.execute("DROP INDEX IF EXISTS idx_deposit_one_current")
    try:
        live.executemany(
            """
            INSERT OR IGNORE INTO deposit_addresses (coin, address, created_at, retired_at)
            VALUES (?, ?, ?, ?)
            """,
            payload,
        )
        _collapse_extra_current(live)
    finally:
        live.execute(_DEPOSIT_CURRENT_INDEX)
    return len(rows)


def restore_empty_tables_from_backup(backup_root: Path | None = None) -> dict[str, int]:
    """Если живые таблицы пустые, берёт строки из самой свежей копии sqlite.

    Живую базу с уже записанными выплатами не затираем: старая копия
    забыла бы свежие request_id, и выплата могла уйти второй раз.
    """
    root = backup_root if backup_root is not None else Path("/var/backups/focuspay-wallets")
    backup = _newest_backup_sqlite(root)
    if backup is None:
        return {"deposits": 0, "payouts": 0}
    live = _db()
    live_deposits = int(live.execute("SELECT COUNT(*) FROM deposit_addresses").fetchone()[0])
    live_payouts = int(live.execute("SELECT COUNT(*) FROM payouts").fetchone()[0])
    if live_deposits and live_payouts:
        return {"deposits": 0, "payouts": 0}
    src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    copied = {"deposits": 0, "payouts": 0}
    try:
        if live_deposits == 0 and _table_exists(src, "deposit_addresses"):
            copied["deposits"] = _copy_deposit_rows(src, live)
        if live_payouts == 0 and _table_exists(src, "payouts"):
            rows = src.execute("SELECT * FROM payouts").fetchall()
            for row in rows:
                keys = row.keys()
                cols = ", ".join(keys)
                marks = ", ".join("?" for _ in keys)
                live.execute(
                    f"INSERT OR IGNORE INTO payouts ({cols}) VALUES ({marks})",
                    tuple(row[key] for key in keys),
                )
            copied["payouts"] = len(rows)
    finally:
        src.close()
    return copied


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _newest_backup_sqlite(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    copies = [path for path in root.glob("*/signer.sqlite3") if path.is_file()]
    if not copies:
        return None
    return max(copies, key=lambda path: path.stat().st_mtime)


def remember_signature(sig: str, ttl_sec: int = 600) -> bool:
    """False — подпись уже предъявляли (replay)."""
    now = int(time.time())
    with _lock:
        db = _db()
        db.execute("DELETE FROM seen_sigs WHERE at < ?", (now - ttl_sec,))
        try:
            db.execute("INSERT INTO seen_sigs (sig, at) VALUES (?, ?)", (sig, now))
            return True
        except sqlite3.IntegrityError:
            return False

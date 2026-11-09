"""История адресов проекта. Текущий можно сменить, старый остаётся."""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("project_wallet_archive")

SOURCES = ("hot_wallet", "sell_deposit")
COINS = ("btc", "ltc")


def _clean(coin: str, address: str, source: str) -> tuple[str, str, str] | None:
    name = (coin or "").strip().lower()
    addr = (address or "").strip()
    origin = (source or "").strip().lower()
    if name not in COINS or origin not in SOURCES or len(addr) < 10:
        return None
    return name, addr, origin


async def remember_seen_addresses(conn, items: Iterable[tuple[str, str, str]]) -> int:
    """Дописывает адреса. Чужой текущий той же монеты и источника помечает сменённым."""
    written = 0
    for raw in items:
        if len(raw) != 3:
            continue
        cleaned = _clean(raw[0], raw[1], raw[2])
        if cleaned is None:
            continue
        coin, address, source = cleaned
        await conn.execute(
            """
            UPDATE project_wallet_addresses
            SET retired_at = now()
            WHERE coin = $1 AND source = $2 AND address <> $3 AND retired_at IS NULL
            """,
            coin,
            source,
            address,
        )
        await conn.execute(
            """
            INSERT INTO project_wallet_addresses (coin, address, source)
            VALUES ($1, $2, $3)
            ON CONFLICT (coin, source, address) DO UPDATE
            SET retired_at = NULL
            """,
            coin,
            address,
            source,
        )
        written += 1
    return written


async def list_project_addresses(conn) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT coin, address, source, first_seen_at, retired_at
        FROM project_wallet_addresses
        ORDER BY retired_at NULLS FIRST, first_seen_at DESC, id DESC
        """
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        seen = row["first_seen_at"]
        retired = row["retired_at"]
        out.append(
            {
                "coin": row["coin"],
                "address": row["address"],
                "source": row["source"],
                "current": retired is None,
                "first_seen_at": seen.isoformat() if seen else None,
                "retired_at": retired.isoformat() if retired else None,
            }
        )
    return out


def addresses_from_signer_payload(payload: dict | None) -> list[str]:
    """Все адреса горячего кошелька, которые подписант ещё помнит.

    Старый ответ без `known` — только текущие.
    """
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    known = payload.get("known")
    if isinstance(known, list):
        for row in known:
            if isinstance(row, dict) and row.get("address"):
                found.append(str(row["address"]))
    if found:
        return found
    raw = payload.get("addresses")
    if isinstance(raw, dict):
        return [str(addr) for addr in raw.values() if addr]
    return []


async def remember_retired_addresses(conn, items: Iterable[tuple[str, str, str]]) -> int:
    """Дописывает уже сменённый адрес, не возвращая его в текущие."""
    written = 0
    for raw in items:
        if len(raw) != 3:
            continue
        cleaned = _clean(raw[0], raw[1], raw[2])
        if cleaned is None:
            continue
        coin, address, source = cleaned
        await conn.execute(
            """
            INSERT INTO project_wallet_addresses (coin, address, source, retired_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (coin, source, address) DO NOTHING
            """,
            coin,
            address,
            source,
        )
        written += 1
    return written


async def record_live_project_addresses(
    conn,
    signer_addresses: dict | None,
    known: list | None = None,
) -> None:
    """Текущие адреса подписанта и приёма продаж. Ошибка таблицы не роняет опрос.

    Сменённые из `known` дописываются как история и не становятся снова текущими.
    """
    from runtime_settings import sell_deposit_address

    items: list[tuple[str, str, str]] = []
    retired: list[tuple[str, str, str]] = []
    raw = signer_addresses if isinstance(signer_addresses, dict) else {}
    for coin, address in raw.items():
        if address:
            items.append((str(coin), str(address), "hot_wallet"))
    for row in known or []:
        if not isinstance(row, dict) or not row.get("address"):
            continue
        item = (str(row.get("coin") or ""), str(row.get("address") or ""), "hot_wallet")
        if row.get("current"):
            items.append(item)
        else:
            retired.append(item)
    sell = sell_deposit_address("btc")
    if sell:
        items.append(("btc", sell, "sell_deposit"))
    if not items and not retired:
        return
    try:
        if retired:
            await remember_retired_addresses(conn, retired)
        if items:
            await remember_seen_addresses(conn, items)
    except Exception:
        logger.warning("project wallet address archive skipped", exc_info=True)

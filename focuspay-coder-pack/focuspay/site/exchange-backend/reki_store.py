"""Чтение снимка /reki. Пишет его бот, бэкенд только читает."""
from __future__ import annotations

import logging

from reki_snapshot import RekiBand, RekiSection, RekiSnapshot

logger = logging.getLogger("reki_store")


async def load_reki_snapshot(conn) -> RekiSnapshot | None:
    try:
        meta = await conn.fetch(
            "SELECT sub_token, count, total_rub, snapshot_at FROM reki_snapshot_meta"
        )
        rows = await conn.fetch(
            """
            SELECT sub_token, min_rub, max_rub, available_rub
            FROM reki_snapshots
            ORDER BY sub_token, min_rub
            """
        )
    except Exception:
        logger.warning("reki snapshot read failed", exc_info=True)
        return None
    if not meta:
        return None

    bands: dict[str, list[RekiBand]] = {}
    for row in rows:
        bands.setdefault(str(row["sub_token"]), []).append(
            RekiBand(
                min_rub=row["min_rub"],
                max_rub=row["max_rub"],
                available_rub=row["available_rub"],
            )
        )
    sections: dict[str, RekiSection] = {}
    taken_at = None
    for row in meta:
        token = str(row["sub_token"])
        sections[token] = RekiSection(
            sub_token=token,
            count=int(row["count"] or 0),
            total_rub=row["total_rub"],
            bands=tuple(bands.get(token, ())),
        )
        stamp = row["snapshot_at"]
        if stamp is not None and (taken_at is None or stamp > taken_at):
            taken_at = stamp
    return RekiSnapshot(sections=sections, taken_at=taken_at)

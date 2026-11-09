"""Operator-recorded crypto wallet payouts (/ops/promo)."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from db import get_pool


def _bot_payout_utils():
    import os
    import sys

    root = os.environ.get("TG_BOT_PATH", "/opt/tg_bot_btc")
    if root not in sys.path:
        sys.path.insert(0, root)
    from services.buy_payout import build_explorer_url, normalize_tx_hash

    return normalize_tx_hash, build_explorer_url


def _normalize_tx_hash(raw: str) -> str | None:
    normalize_tx_hash, _ = _bot_payout_utils()
    return normalize_tx_hash(raw)


def _explorer_url(crypto: str, tx_hash: str) -> str:
    _, build_explorer_url = _bot_payout_utils()
    return build_explorer_url((crypto or "ltc").lower(), tx_hash)


def _issuer_label(op_id: int | None, username: str | None, display_name: str | None) -> str:
    if not op_id:
        return "Админ"
    display = (display_name or "").strip()
    user = (username or "").strip()
    if display and user:
        return f"{display} (@{user})"
    if display:
        return display
    if user:
        return f"@{user}"
    return f"#{op_id}"


def _recipient_label(row: dict) -> str:
    name = (row.get("recipient_name") or "").strip()
    username = (row.get("user_username") or "").strip()
    if name and username:
        return f"{name} (@{username})"
    if name:
        return name
    if username:
        return f"@{username}"
    uid = row.get("user_id")
    return f"ID {uid}" if uid else name or "—"


def _payout_row_out(row) -> dict:
    r = dict(row)
    crypto = (r.get("crypto") or "ltc").lower()
    tx = (r.get("payout_tx_hash") or "").strip()
    op_id = r.get("issued_by_operator_id")
    issuer_username = (r.get("issuer_username") or "").strip()
    issuer_display = (r.get("issuer_display_name") or "").strip()
    created = r.get("created_at")
    return {
        "id": int(r["id"]),
        "recipient_name": r.get("recipient_name") or "",
        "recipient_label": _recipient_label(r),
        "user_id": int(r["user_id"]) if r.get("user_id") else None,
        "username": r.get("user_username"),
        "crypto": crypto,
        "amount_rub": float(r.get("amount_rub") or 0),
        "wallet_address": r.get("wallet_address") or "",
        "payout_tx_hash": tx,
        "explorer_url": _explorer_url(crypto, tx) if tx else None,
        "label": r.get("label"),
        "raffle_winner_id": int(r["raffle_winner_id"]) if r.get("raffle_winner_id") else None,
        "issued_by_operator_id": int(op_id) if op_id else None,
        "issued_by_operator": {
            "id": int(op_id),
            "username": issuer_username or None,
            "display_name": issuer_display or None,
            "label": _issuer_label(op_id, issuer_username, issuer_display),
        }
        if op_id
        else None,
        "issuer_label": _issuer_label(op_id, issuer_username, issuer_display),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


_PAYOUTS_FROM = """
    FROM operator_wallet_payouts owp
    LEFT JOIN bot_users bu ON bu.user_id = owp.user_id
    LEFT JOIN operator_accounts oa ON oa.id = owp.issued_by_operator_id
"""


def _parse_issued_by_filter(issued_by: str, op_id: int) -> tuple[str | None, object]:
    raw = (issued_by or "all").strip().lower()
    if raw in ("all", ""):
        return None, None
    if raw == "mine":
        return "owp.issued_by_operator_id = ${n}", op_id
    try:
        oid = int(raw)
        if oid > 0:
            return "owp.issued_by_operator_id = ${n}", oid
    except ValueError:
        pass
    raise ValueError("Invalid issued_by filter")


def _build_payout_filters(
    *,
    op_id: int,
    issued_by: str,
    q: str | None,
    amount_rub: float | None,
    crypto: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    ib_clause, ib_val = _parse_issued_by_filter(issued_by, op_id)
    if ib_clause:
        clause = ib_clause.replace("${n}", f"${len(params) + 1}")
        clauses.append(clause)
        if ib_val is not None:
            params.append(ib_val)

    crypto_norm = (crypto or "").strip().lower()
    if crypto_norm and crypto_norm != "all":
        idx = len(params) + 1
        clauses.append(f"owp.crypto = ${idx}")
        params.append(crypto_norm)

    if amount_rub is not None and amount_rub > 0:
        idx = len(params) + 1
        clauses.append(f"owp.amount_rub = ${idx}")
        params.append(amount_rub)

    q_norm = (q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        idx = len(params) + 1
        clauses.append(
            f"(owp.recipient_name ILIKE ${idx} OR owp.wallet_address ILIKE ${idx} "
            f"OR owp.payout_tx_hash ILIKE ${idx} OR COALESCE(owp.label, '') ILIKE ${idx} "
            f"OR bu.username ILIKE ${idx} OR owp.user_id::text ILIKE ${idx + 1})"
        )
        params.extend([like, f"{q_norm}%"])

    if date_from:
        idx = len(params) + 1
        clauses.append(f"owp.created_at >= ${idx}")
        params.append(datetime.combine(date_from, time.min))
    if date_to:
        idx = len(params) + 1
        clauses.append(f"owp.created_at < ${idx}")
        params.append(datetime.combine(date_to, time.max))

    return clauses, params


async def list_wallet_payouts(
    *,
    op_id: int,
    issued_by: str = "all",
    q: str | None = None,
    amount_rub: float | None = None,
    crypto: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    clauses, extra_params = _build_payout_filters(
        op_id=op_id,
        issued_by=issued_by,
        q=q,
        amount_rub=amount_rub,
        crypto=crypto,
        date_from=date_from,
        date_to=date_to,
    )
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        summary_row = await conn.fetchrow(
            f"""
            SELECT COUNT(*)::int AS total_all,
                   COALESCE(SUM(amount_rub), 0)::float AS total_rub
            {_PAYOUTS_FROM}
            """
        )
        issuer_rows = await conn.fetch(
            f"""
            SELECT owp.issued_by_operator_id,
                   oa.username AS issuer_username,
                   oa.display_name AS issuer_display_name,
                   COUNT(*)::int AS payout_count
            {_PAYOUTS_FROM}
            GROUP BY owp.issued_by_operator_id, oa.username, oa.display_name
            ORDER BY payout_count DESC, oa.username NULLS LAST
            """
        )
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*)::int AS cnt {_PAYOUTS_FROM} {where_sql}",
            *extra_params,
        )
        rows = await conn.fetch(
            f"""
            SELECT owp.*, bu.username AS user_username, bu.first_name AS user_first_name,
                   oa.username AS issuer_username, oa.display_name AS issuer_display_name
            {_PAYOUTS_FROM}
            {where_sql}
            ORDER BY owp.created_at DESC
            LIMIT 500
            """,
            *extra_params,
        )

    issuers = [
        {
            "id": int(r["issued_by_operator_id"]) if r["issued_by_operator_id"] else None,
            "label": _issuer_label(
                r["issued_by_operator_id"],
                r["issuer_username"],
                r["issuer_display_name"],
            ),
            "count": int(r["payout_count"] or 0),
        }
        for r in issuer_rows
    ]
    payouts = [_payout_row_out(r) for r in rows]
    total_all = int(summary_row["total_all"] or 0) if summary_row else 0
    return {
        "payouts": payouts,
        "total": int(count_row["cnt"] or 0) if count_row else len(payouts),
        "total_all": total_all,
        "summary": {
            "total_rub": float(summary_row["total_rub"] or 0) if summary_row else 0.0,
        },
        "issuers": issuers,
    }


async def _find_pending_raffle_winner(
    conn,
    *,
    user_id: int | None,
    amount_rub: float,
    raffle_winner_id: int | None,
) -> dict | None:
    if raffle_winner_id:
        row = await conn.fetchrow(
            """
            SELECT w.*, bu.username, bu.first_name
            FROM raffle_winners w
            LEFT JOIN bot_users bu ON bu.user_id = w.user_id
            WHERE w.id = $1 AND w.payout_method = 'ltc' AND w.status = 'pending'
            """,
            raffle_winner_id,
        )
        return dict(row) if row else None

    if not user_id:
        return None
    row = await conn.fetchrow(
        """
        SELECT w.*, bu.username, bu.first_name
        FROM raffle_winners w
        JOIN raffle_campaigns c ON c.id = w.campaign_id
        LEFT JOIN bot_users bu ON bu.user_id = w.user_id
        WHERE w.user_id = $1
          AND w.payout_method = 'ltc'
          AND w.status = 'pending'
          AND c.status = 'drawn'
          AND ABS(w.prize_rub - $2) < 0.01
        ORDER BY w.place ASC
        LIMIT 1
        """,
        user_id,
        amount_rub,
    )
    return dict(row) if row else None


async def create_wallet_payout(
    *,
    operator_id: int,
    recipient_name: str,
    wallet_address: str,
    tx_hash_raw: str,
    amount_rub: float,
    crypto: str = "ltc",
    label: str | None = None,
    recipient: str | None = None,
    raffle_winner_id: int | None = None,
) -> tuple[dict | None, str | None]:
    normalized = _normalize_tx_hash(tx_hash_raw)
    if not normalized:
        return None, "invalid_tx"

    name = (recipient_name or "").strip()
    wallet = (wallet_address or "").strip()
    if not name:
        return None, "missing_name"
    if not wallet:
        return None, "missing_wallet"

    crypto_norm = (crypto or "ltc").strip().lower()
    if crypto_norm not in ("ltc", "btc", "usdt"):
        crypto_norm = "ltc"

    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        raw_recipient = (recipient or "").strip()
        if raw_recipient:
            from telegram_user_lookup import resolve_single_recipient

            hit = await resolve_single_recipient(conn, raw_recipient)
            if hit:
                user_id = int(hit["user_id"])
                username = hit.get("username")
                first_name = hit.get("first_name")

        async with conn.transaction():
            dup = await conn.fetchval(
                "SELECT 1 FROM operator_wallet_payouts WHERE payout_tx_hash = $1",
                normalized,
            )
            if dup:
                return None, "duplicate_tx"

            rw = await _find_pending_raffle_winner(
                conn,
                user_id=user_id,
                amount_rub=amount_rub,
                raffle_winner_id=raffle_winner_id,
            )
            rw_id = int(rw["id"]) if rw else None
            if rw and not user_id:
                user_id = int(rw["user_id"])
                username = rw.get("username")
                first_name = rw.get("first_name")

            row = await conn.fetchrow(
                """
                INSERT INTO operator_wallet_payouts (
                    recipient_name, user_id, crypto, amount_rub, wallet_address,
                    payout_tx_hash, label, issued_by_operator_id, raffle_winner_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                name,
                user_id,
                crypto_norm,
                amount_rub,
                wallet,
                normalized,
                (label or "").strip() or None,
                operator_id,
                rw_id,
            )
            payout_id = int(row["id"])

            if rw_id:
                await conn.execute(
                    """
                    UPDATE raffle_winners
                    SET status = 'paid',
                        paid_at = now(),
                        payout_tx_hash = $2,
                        payout_wallet = $3,
                        paid_by_operator_id = $4,
                        operator_wallet_payout_id = $5,
                        payout_note = COALESCE($6, payout_note)
                    WHERE id = $1 AND status = 'pending'
                    """,
                    rw_id,
                    normalized,
                    wallet,
                    operator_id,
                    payout_id,
                    (label or "").strip() or None,
                )

    async with pool.acquire() as conn:
        op_row = await conn.fetchrow(
            "SELECT username, display_name FROM operator_accounts WHERE id = $1",
            operator_id,
        )
    out_row = dict(row)
    out_row["user_username"] = username
    out_row["user_first_name"] = first_name
    if op_row:
        out_row["issuer_username"] = op_row["username"]
        out_row["issuer_display_name"] = op_row["display_name"]
    return _payout_row_out(out_row), None


async def mark_balance_raffle_winner_paid(
    conn,
    *,
    user_id: int,
    amount_rub: float,
    operator_id: int,
    label: str,
    raffle_winner_id: int | None = None,
) -> int | None:
    """Закрыть pending balance-победителя FocusLucky после выдачи скидки."""
    if raffle_winner_id:
        row = await conn.fetchrow(
            """
            SELECT id FROM raffle_winners
            WHERE id = $1 AND payout_method = 'balance' AND status = 'pending'
            """,
            raffle_winner_id,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT w.id FROM raffle_winners w
            JOIN raffle_campaigns c ON c.id = w.campaign_id
            WHERE w.user_id = $1
              AND w.payout_method = 'balance'
              AND w.status = 'pending'
              AND c.status = 'drawn'
              AND ABS(w.prize_rub - $2) < 0.01
            ORDER BY w.place ASC
            LIMIT 1
            """,
            user_id,
            amount_rub,
        )
    if not row:
        return None
    rw_id = int(row["id"])
    note = (label or "").strip() or "FocusLucky"
    await conn.execute(
        """
        UPDATE raffle_winners
        SET status = 'paid',
            paid_at = now(),
            paid_by_operator_id = $2,
            payout_note = $3
        WHERE id = $1 AND status = 'pending'
        """,
        rw_id,
        operator_id,
        note,
    )
    return rw_id


async def list_pending_raffle_ltc_winners() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow(
            """
            SELECT id FROM raffle_campaigns
            WHERE status = 'drawn'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        if not camp:
            return []
        rows = await conn.fetch(
            """
            SELECT w.id, w.place, w.user_id, w.prize_rub, w.winning_ticket_no,
                   bu.username, bu.first_name
            FROM raffle_winners w
            LEFT JOIN bot_users bu ON bu.user_id = w.user_id
            WHERE w.campaign_id = $1
              AND w.payout_method = 'ltc'
              AND w.status = 'pending'
            ORDER BY w.place ASC
            """,
            int(camp["id"]),
        )

    out = []
    for r in rows:
        rd = dict(r)
        username = (rd.get("username") or "").strip()
        first = (rd.get("first_name") or "").strip()
        if first:
            display_name = first
        elif username:
            display_name = f"@{username}"
        else:
            display_name = f"ID {rd['user_id']}"
        out.append(
            {
                "raffle_winner_id": int(rd["id"]),
                "place": int(rd["place"]),
                "user_id": int(rd["user_id"]),
                "username": username or None,
                "recipient_name": display_name,
                "amount_rub": float(rd["prize_rub"]),
                "winning_ticket_no": int(rd["winning_ticket_no"]),
            }
        )
    return out


async def list_pending_raffle_balance_winners() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow(
            """
            SELECT id FROM raffle_campaigns
            WHERE status = 'drawn'
            ORDER BY id DESC
            LIMIT 1
            """
        )
        if not camp:
            return []
        rows = await conn.fetch(
            """
            SELECT w.id, w.place, w.user_id, w.prize_rub, w.winning_ticket_no,
                   bu.username, bu.first_name
            FROM raffle_winners w
            LEFT JOIN bot_users bu ON bu.user_id = w.user_id
            WHERE w.campaign_id = $1
              AND w.payout_method = 'balance'
              AND w.status = 'pending'
            ORDER BY w.place ASC
            """,
            int(camp["id"]),
        )

    out = []
    for r in rows:
        rd = dict(r)
        username = (rd.get("username") or "").strip()
        first = (rd.get("first_name") or "").strip()
        if first:
            display_name = first
        elif username:
            display_name = f"@{username}"
        else:
            display_name = f"ID {rd['user_id']}"
        out.append(
            {
                "raffle_winner_id": int(rd["id"]),
                "place": int(rd["place"]),
                "user_id": int(rd["user_id"]),
                "username": username or None,
                "recipient_name": display_name,
                "amount_rub": float(rd["prize_rub"]),
                "winning_ticket_no": int(rd["winning_ticket_no"]),
            }
        )
    return out


async def sum_wallet_payout_rub(
    *,
    days: int | None = None,
    date_obj: date | None = None,
) -> float:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if date_obj is not None:
            val = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM operator_wallet_payouts
                WHERE created_at::date = $1
                """,
                date_obj,
            )
        elif days is not None:
            val = await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount_rub), 0)::float
                FROM operator_wallet_payouts
                WHERE created_at >= now() - ($1 * interval '1 day')
                """,
                days,
            )
        else:
            val = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_rub), 0)::float FROM operator_wallet_payouts"
            )
    return float(val or 0)

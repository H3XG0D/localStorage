"""Чат покупатель ↔ админ на сайте."""
import logging
import uuid
from fastapi import HTTPException

from chat_attachments import attachment_public_url
from chat_buyer_snapshot import buyer_snapshot, guest_snapshot
from db import get_pool
from guest_sessions import get_or_create_guest_user_id

logger = logging.getLogger("chat_service")

MAX_BODY_LEN = 2000

_LAST_SENDER_SQL = """
(SELECT sender_role FROM web_chat_messages m
 WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1)
"""

_NEEDS_REPLY_SQL = f"COALESCE({_LAST_SENDER_SQL}, '') IN ('buyer', 'exchanger')"


def _needs_reply(last_sender: str | None) -> bool:
    return (last_sender or "") in ("buyer", "exchanger")


def _support_exclude_clause(exclude: list[int], params: list) -> str:
    if not exclude:
        return ""
    params.append(exclude)
    return f"(t.telegram_user_id IS NULL OR NOT (t.telegram_user_id = ANY(${len(params)}::bigint[])))"


def _normalize_body(body: str | None, *, allow_empty: bool = False) -> str:
    text = (body or "").strip()
    if not text and not allow_empty:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым")
    if len(text) > MAX_BODY_LEN:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_BODY_LEN} символов")
    return text


def _msg_row(r) -> dict:
    msg_type = r.get("message_type") or "text"
    attachment_id = r.get("attachment_id")
    out = {
        "id": r["id"],
        "sender_role": r["sender_role"],
        "message_type": msg_type,
        "body": r.get("body") or "",
        "attachment_id": attachment_id,
        "attachment_filename": r.get("attachment_filename"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }
    if attachment_id and msg_type in ("image", "video", "document", "audio"):
        url = attachment_public_url(attachment_id)
        if msg_type == "image":
            out["image_url"] = url
            out["admin_image_url"] = url
        elif msg_type == "video":
            out["video_url"] = url
        elif msg_type == "document":
            out["file_url"] = url
        elif msg_type == "audio":
            out["audio_url"] = url
    if msg_type == "sticker":
        out["sticker_file_id"] = r.get("sticker_file_id")
        out["sticker_emoji"] = r.get("sticker_emoji")
        out["sticker_set_name"] = r.get("sticker_set_name")
    return out


def _preview_body(r) -> str:
    msg_type = r.get("message_type") or "text"
    cap = (r.get("body") or "").strip()
    icons = {
        "image": "📷",
        "video": "🎬",
        "document": "📄",
        "audio": "🎤",
    }
    if msg_type in icons:
        label = {"image": "Фото", "video": "Видео", "document": "Файл", "audio": "Аудио"}[msg_type]
        return f"{icons[msg_type]} {cap}" if cap else f"{icons[msg_type]} {label}"
    if msg_type == "sticker":
        emoji = (r.get("sticker_emoji") or cap or "🎭").strip()
        return f"🎭 {emoji}"
    return (r.get("body") or "")[:120]


def _thread_summary(r) -> dict:
    return {
        "id": r["id"],
        "order_id": r.get("order_id"),
        "telegram_user_id": r.get("telegram_user_id"),
        "telegram_dm_chat_id": r.get("telegram_dm_chat_id"),
        "business_connection_id": r.get("business_connection_id"),
        "external_exchanger_id": r.get("external_exchanger_id"),
        "source": r.get("source") or "web",
        "admin_unread": int(r.get("admin_unread") or 0),
        "last_message_at": r["last_message_at"].isoformat()
        if r.get("last_message_at")
        else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


async def exchanger_snapshot(conn, exchanger_id: int) -> dict:
    row = await conn.fetchrow(
        """
        SELECT e.id, e.name,
            (SELECT username FROM external_exchanger_accounts
             WHERE external_exchanger_id = e.id
             ORDER BY id LIMIT 1) AS username
        FROM external_exchangers e
        WHERE e.id = $1
        """,
        exchanger_id,
    )
    active_rows = await conn.fetch(
        """
        SELECT id FROM external_deals
        WHERE exchanger_id = $1
          AND status IN ('awaiting_receipt', 'pending')
        ORDER BY created_at DESC
        """,
        exchanger_id,
    )
    active_deal_ids = [int(r["id"]) for r in active_rows]
    if not row:
        return {
            "exchanger_id": exchanger_id,
            "name": f"Партнёр #{exchanger_id}",
            "display_name": f"Партнёр #{exchanger_id}",
            "username": None,
            "active_deal_id": active_deal_ids[0] if active_deal_ids else None,
            "active_deal_ids": active_deal_ids,
            "active_deal_count": len(active_deal_ids),
        }
    name = str(row["name"] or f"Партнёр #{exchanger_id}")
    return {
        "exchanger_id": int(row["id"]),
        "name": name,
        "display_name": name,
        "username": row.get("username"),
        "active_deal_id": active_deal_ids[0] if active_deal_ids else None,
        "active_deal_ids": active_deal_ids,
        "active_deal_count": len(active_deal_ids),
    }


async def _enrich_thread(
    conn,
    r,
    *,
    last_body: str | None = None,
    last_sender: str | None = None,
) -> dict:
    s = _thread_summary(r)
    if last_body is not None:
        s["last_body"] = last_body
    if last_sender is not None:
        s["last_sender"] = last_sender
        s["needs_reply"] = _needs_reply(last_sender)
    ex_id = r.get("external_exchanger_id")
    if ex_id:
        s["exchanger"] = await exchanger_snapshot(conn, int(ex_id))
    else:
        uid = r.get("telegram_user_id")
        if uid:
            s["buyer"] = await buyer_snapshot(conn, int(uid))
        else:
            s["buyer"] = guest_snapshot(r.get("session_token"))
    return s


async def _touch_bot_user(conn, telegram_user_id: int) -> None:
    await conn.execute(
        """
        INSERT INTO bot_users (user_id, first_seen_at, last_seen_at)
        VALUES ($1, now(), now())
        ON CONFLICT (user_id) DO UPDATE SET last_seen_at = now()
        """,
        telegram_user_id,
    )


async def merge_guest_chat_to_telegram(session_token: str, telegram_user_id: int) -> None:
    try:
        token = uuid.UUID(session_token.strip())
    except ValueError:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        guest = await conn.fetchrow(
            "SELECT id FROM web_chat_threads WHERE session_token = $1", token
        )
        if not guest:
            return
        existing = await conn.fetchrow(
            """
            SELECT id FROM web_chat_threads
            WHERE telegram_user_id = $1
            ORDER BY last_message_at DESC NULLS LAST
            LIMIT 1
            """,
            telegram_user_id,
        )
        if existing and existing["id"] != guest["id"]:
            await _merge_threads_conn(conn, keep_id=existing["id"], drop_id=guest["id"])
        else:
            await conn.execute(
                """
                UPDATE web_chat_threads
                SET telegram_user_id = $1,
                    session_token = NULL,
                    source = CASE
                        WHEN source = 'telegram' THEN 'both'
                        ELSE COALESCE(NULLIF(source, ''), 'web')
                    END,
                    updated_at = now()
                WHERE id = $2
                """,
                telegram_user_id,
                guest["id"],
            )


def _parse_session_token(session_token: str | None) -> uuid.UUID | None:
    if not session_token:
        return None
    try:
        return uuid.UUID(session_token.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guest session")


async def _merge_threads_conn(conn, *, keep_id: int, drop_id: int) -> None:
    if keep_id == drop_id:
        return
    drop = await conn.fetchrow(
        "SELECT * FROM web_chat_threads WHERE id = $1", drop_id
    )
    if not drop:
        return
    keep = await conn.fetchrow(
        "SELECT source FROM web_chat_threads WHERE id = $1", keep_id
    )
    keep_src = (keep.get("source") if keep else None) or "web"
    drop_src = drop.get("source") or "web"
    sources = {keep_src, drop_src}
    if "both" in sources or sources == {"web", "telegram"}:
        merged_source = "both"
    elif "telegram" in sources:
        merged_source = "telegram"
    else:
        merged_source = keep_src
    await conn.execute(
        "UPDATE web_chat_messages SET thread_id = $1 WHERE thread_id = $2",
        keep_id,
        drop_id,
    )
    await conn.execute(
        """
        UPDATE web_chat_threads SET
            admin_unread = admin_unread + $2,
            last_message_at = GREATEST(
                last_message_at,
                $3::timestamptz
            ),
            order_id = COALESCE(order_id, $4),
            telegram_dm_chat_id = COALESCE(telegram_dm_chat_id, $5),
            business_connection_id = COALESCE(business_connection_id, $6),
            source = $7,
            updated_at = now()
        WHERE id = $1
        """,
        keep_id,
        int(drop.get("admin_unread") or 0),
        drop.get("last_message_at"),
        drop.get("order_id"),
        drop.get("telegram_dm_chat_id"),
        drop.get("business_connection_id"),
        merged_source,
    )
    await conn.execute("DELETE FROM web_chat_threads WHERE id = $1", drop_id)


async def _find_thread_row(
    conn,
    *,
    token_uuid: uuid.UUID | None,
    telegram_user_id: int | None,
):
    row = None
    if telegram_user_id:
        row = await conn.fetchrow(
            """
            SELECT * FROM web_chat_threads
            WHERE telegram_user_id = $1
            ORDER BY last_message_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            telegram_user_id,
        )
    if not row and token_uuid:
        row = await conn.fetchrow(
            "SELECT * FROM web_chat_threads WHERE session_token = $1", token_uuid
        )
    return row


async def get_thread(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    order_id: str | None = None,
) -> dict | None:
    pool = await get_pool()
    token_uuid = _parse_session_token(session_token)
    async with pool.acquire() as conn:
        row = await _find_thread_row(
            conn, token_uuid=token_uuid, telegram_user_id=telegram_user_id
        )
        if not row and order_id:
            # Тред, инициированный оператором: у покупателя ещё нет треда,
            # привязанного к его identity — ищем по order_id с проверкой владения.
            row = await _find_thread_by_order_for_buyer(
                conn,
                order_id=order_id,
                session_token=session_token,
                telegram_user_id=telegram_user_id,
            )
        if not row:
            return None
        if order_id and not row.get("order_id"):
            await conn.execute(
                "UPDATE web_chat_threads SET order_id = $1, updated_at = now() WHERE id = $2",
                order_id,
                row["id"],
            )
            row = await conn.fetchrow(
                "SELECT * FROM web_chat_threads WHERE id = $1", row["id"]
            )
    return _thread_summary(row)


async def _find_thread_by_order_for_buyer(
    conn,
    *,
    order_id: str,
    session_token: str | None,
    telegram_user_id: int | None,
):
    """Найти тред по order_id, убедившись что заявка принадлежит покупателю."""
    try:
        order = await conn.fetchrow(
            "SELECT order_id, user_id FROM orders WHERE order_id = $1", order_id
        )
    except Exception:
        return None
    if not order:
        return None
    owner_id = order.get("user_id")
    allowed = False
    if telegram_user_id and owner_id is not None:
        try:
            allowed = int(owner_id) == int(telegram_user_id)
        except (TypeError, ValueError):
            allowed = False
    if not allowed and session_token:
        try:
            from guest_sessions import get_or_create_guest_user_id

            guest_id = await get_or_create_guest_user_id(session_token)
            allowed = owner_id is not None and int(owner_id) == int(guest_id)
        except Exception:
            allowed = False
    if not allowed:
        return None
    return await conn.fetchrow(
        "SELECT * FROM web_chat_threads WHERE order_id = $1 ORDER BY id DESC LIMIT 1",
        order_id,
    )


async def admin_initiate_thread(
    *,
    order_id: str,
    body: str,
    admin_user_id: int | None = None,
) -> dict:
    """Оператор пишет первым: найти/создать тред по заявке и отправить сообщение.

    Повторный вызов по той же заявке пишет в тот же тред (без дублей).
    Уведомление покупателю уходит через существующий триггер
    trg_web_chat_buyer_notify (sender_role='admin', thread.order_id задан).
    """
    from chat_telegram_bridge import mirror_admin_text_to_telegram
    from exchanger_chat_escalation import clear_exchanger_escalation

    text = _normalize_body(body)
    oid = (order_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="order_id required")
    pool = await get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT order_id, user_id FROM orders WHERE order_id = $1", oid
        )
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        owner_id = order.get("user_id")
        tg_id: int | None = None
        try:
            tg_id = int(owner_id) if owner_id is not None and int(owner_id) > 0 else None
        except (TypeError, ValueError):
            tg_id = None

        row = await conn.fetchrow(
            "SELECT * FROM web_chat_threads WHERE order_id = $1 ORDER BY id DESC LIMIT 1",
            oid,
        )
        if not row and tg_id:
            row = await conn.fetchrow(
                """
                SELECT * FROM web_chat_threads
                WHERE telegram_user_id = $1
                ORDER BY last_message_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                tg_id,
            )
            if row and not row.get("order_id"):
                await conn.execute(
                    "UPDATE web_chat_threads SET order_id = $1, updated_at = now() WHERE id = $2",
                    oid,
                    row["id"],
                )
                row = await conn.fetchrow(
                    "SELECT * FROM web_chat_threads WHERE id = $1", row["id"]
                )
        if not row:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_threads (telegram_user_id, order_id, source)
                VALUES ($1, $2, 'web')
                RETURNING *
                """,
                tg_id,
                oid,
            )
        thread_id = int(row["id"])
        msg_row = await _insert_message(
            conn,
            thread_id=thread_id,
            sender_role="admin",
            body=text,
            message_type="text",
            admin_user_id=admin_user_id,
        )
    await clear_exchanger_escalation(thread_id)
    logger.info("admin chat initiate order=%s thread=%s admin=%s", oid, thread_id, admin_user_id)
    msg = _msg_row(msg_row)
    thread_row = await get_thread_for_outbound(thread_id)
    if thread_row:
        await mirror_admin_text_to_telegram(thread_row, text)
    return {"thread": _thread_summary(row), "message": msg}


async def get_or_create_thread(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    order_id: str | None = None,
) -> dict:
    pool = await get_pool()
    token_uuid = _parse_session_token(session_token)

    async with pool.acquire() as conn:
        row = await _find_thread_row(
            conn, token_uuid=token_uuid, telegram_user_id=telegram_user_id
        )
        if row:
            if order_id and not row.get("order_id"):
                await conn.execute(
                    "UPDATE web_chat_threads SET order_id = $1, updated_at = now() WHERE id = $2",
                    order_id,
                    row["id"],
                )
                row = await conn.fetchrow(
                    "SELECT * FROM web_chat_threads WHERE id = $1", row["id"]
                )
            return _thread_summary(row)

        row = await conn.fetchrow(
            """
            INSERT INTO web_chat_threads (session_token, telegram_user_id, order_id, source)
            VALUES ($1, $2, $3, 'web')
            ON CONFLICT (telegram_user_id) WHERE telegram_user_id IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            token_uuid,
            telegram_user_id,
            order_id,
        )
        if not row and telegram_user_id:
            row = await conn.fetchrow(
                """
                SELECT * FROM web_chat_threads
                WHERE telegram_user_id = $1
                LIMIT 1
                """,
                telegram_user_id,
            )
        if not row:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_threads (session_token, telegram_user_id, order_id, source)
                VALUES ($1, $2, $3, 'web')
                RETURNING *
                """,
                token_uuid,
                telegram_user_id,
                order_id,
            )
    return _thread_summary(row)


async def upsert_business_connection(
    *,
    connection_id: str,
    user_id: int,
    is_enabled: bool = True,
    user_chat_id: int | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO telegram_business_connections (
                connection_id, user_id, user_chat_id, is_enabled, updated_at
            )
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (connection_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                user_chat_id = COALESCE(EXCLUDED.user_chat_id, telegram_business_connections.user_chat_id),
                is_enabled = EXCLUDED.is_enabled,
                updated_at = now()
            """,
            connection_id,
            user_id,
            user_chat_id,
            is_enabled,
        )


async def _get_or_create_telegram_thread(
    conn,
    *,
    telegram_user_id: int,
    telegram_dm_chat_id: int,
    business_connection_id: str,
) -> dict:
    row = await conn.fetchrow(
        """
        SELECT * FROM web_chat_threads
        WHERE telegram_user_id = $1
        ORDER BY last_message_at DESC NULLS LAST, id DESC
        LIMIT 1
        """,
        telegram_user_id,
    )
    if row:
        new_source = "both" if (row.get("source") or "web") == "web" else row.get("source")
        row = await conn.fetchrow(
            """
            UPDATE web_chat_threads SET
                telegram_dm_chat_id = $2,
                business_connection_id = $3,
                source = $4,
                updated_at = now()
            WHERE id = $1
            RETURNING *
            """,
            row["id"],
            telegram_dm_chat_id,
            business_connection_id,
            new_source or "telegram",
        )
        return _thread_summary(row)

    row = await conn.fetchrow(
        """
        INSERT INTO web_chat_threads (
            telegram_user_id, telegram_dm_chat_id, business_connection_id, source
        )
        VALUES ($1, $2, $3, 'telegram')
        RETURNING *
        """,
        telegram_user_id,
        telegram_dm_chat_id,
        business_connection_id,
    )
    return _thread_summary(row)


async def _mark_thread_web_source(conn, thread_id: int) -> None:
    await conn.execute(
        """
        UPDATE web_chat_threads SET source = CASE
            WHEN source = 'telegram' THEN 'both'
            ELSE 'web'
        END,
        updated_at = now()
        WHERE id = $1 AND source IS DISTINCT FROM 'both'
        """,
        thread_id,
    )


async def resolve_buyer_ids(
    guest_session: str | None,
    telegram_user_id: int | None,
) -> tuple[int | None, str | None]:
    """telegram_user_id для треда, guest_session строка."""
    if telegram_user_id:
        return telegram_user_id, guest_session
    if guest_session:
        await get_or_create_guest_user_id(guest_session)
        return None, guest_session
    raise HTTPException(
        status_code=401,
        detail="Provide X-Guest-Session or log in with Telegram",
    )


async def list_messages(
    thread_id: int,
    *,
    after_id: int = 0,
    limit: int = 100,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM web_chat_messages
            WHERE thread_id = $1 AND id > $2
            ORDER BY id ASC
            LIMIT $3
            """,
            thread_id,
            after_id,
            min(limit, 200),
        )
    return [_msg_row(r) for r in rows]


async def list_messages_window(
    thread_id: int,
    *,
    before_id: int = 0,
    after_id: int = 0,
    limit: int = 100,
) -> dict:
    """Загрузка окна сообщений: начальная (последние N), старые (before_id), новые (after_id)."""
    cap = min(limit, 200)
    pool = await get_pool()
    async with pool.acquire() as conn:
        if after_id > 0:
            rows = await conn.fetch(
                """
                SELECT * FROM web_chat_messages
                WHERE thread_id = $1 AND id > $2
                ORDER BY id ASC
                LIMIT $3
                """,
                thread_id,
                after_id,
                cap,
            )
            messages = [_msg_row(r) for r in rows]
            return {
                "messages": messages,
                "has_more_older": False,
                "oldest_id": messages[0]["id"] if messages else None,
            }

        if before_id > 0:
            rows = await conn.fetch(
                """
                SELECT * FROM web_chat_messages
                WHERE thread_id = $1 AND id < $2
                ORDER BY id DESC
                LIMIT $3
                """,
                thread_id,
                before_id,
                cap,
            )
            rows = list(reversed(rows))
            older_count = await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM web_chat_messages
                WHERE thread_id = $1 AND id < $2
                """,
                thread_id,
                rows[0]["id"] if rows else before_id,
            )
            messages = [_msg_row(r) for r in rows]
            return {
                "messages": messages,
                "has_more_older": int(older_count or 0) > 0,
                "oldest_id": messages[0]["id"] if messages else None,
            }

        rows = await conn.fetch(
            """
            SELECT * FROM web_chat_messages
            WHERE thread_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            thread_id,
            cap,
        )
        rows = list(reversed(rows))
        if rows:
            older_count = await conn.fetchval(
                """
                SELECT COUNT(*)::int FROM web_chat_messages
                WHERE thread_id = $1 AND id < $2
                """,
                thread_id,
                rows[0]["id"],
            )
            has_more = int(older_count or 0) > 0
        else:
            has_more = False
        messages = [_msg_row(r) for r in rows]
        return {
            "messages": messages,
            "has_more_older": has_more,
            "oldest_id": messages[0]["id"] if messages else None,
        }


async def _insert_message(
    conn,
    *,
    thread_id: int,
    sender_role: str,
    body: str,
    message_type: str = "text",
    attachment_id: str | None = None,
    attachment_filename: str | None = None,
    admin_user_id: int | None = None,
    telegram_message_id: int | None = None,
    sticker_file_id: str | None = None,
    sticker_emoji: str | None = None,
    sticker_set_name: str | None = None,
) -> dict:
    with_sticker = bool(
        sticker_file_id or sticker_emoji or sticker_set_name or message_type == "sticker"
    )
    if sender_role in ("buyer", "exchanger"):
        if with_sticker:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_messages (
                    thread_id, sender_role, body, message_type, attachment_id,
                    attachment_filename, telegram_message_id, read_by_admin, read_by_buyer,
                    sticker_file_id, sticker_emoji, sticker_set_name
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, TRUE, $8, $9, $10)
                RETURNING *
                """,
                thread_id,
                sender_role,
                body,
                message_type,
                attachment_id,
                attachment_filename,
                telegram_message_id,
                sticker_file_id,
                sticker_emoji,
                sticker_set_name,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_messages (
                    thread_id, sender_role, body, message_type, attachment_id,
                    attachment_filename, telegram_message_id, read_by_admin, read_by_buyer
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE, TRUE)
                RETURNING *
                """,
                thread_id,
                sender_role,
                body,
                message_type,
                attachment_id,
                attachment_filename,
                telegram_message_id,
            )
        await conn.execute(
            """
            UPDATE web_chat_threads SET
                admin_unread = admin_unread + 1,
                last_message_at = now(),
                updated_at = now()
            WHERE id = $1
            """,
            thread_id,
        )
    else:
        if with_sticker:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_messages (
                    thread_id, sender_role, body, message_type, attachment_id,
                    attachment_filename, admin_user_id, telegram_message_id,
                    read_by_admin, read_by_buyer,
                    sticker_file_id, sticker_emoji, sticker_set_name
                )
                VALUES ($1, 'admin', $2, $3, $4, $5, $6, $7, TRUE, FALSE, $8, $9, $10)
                RETURNING *
                """,
                thread_id,
                body,
                message_type,
                attachment_id,
                attachment_filename,
                admin_user_id,
                telegram_message_id,
                sticker_file_id,
                sticker_emoji,
                sticker_set_name,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO web_chat_messages (
                    thread_id, sender_role, body, message_type, attachment_id,
                    attachment_filename, admin_user_id, telegram_message_id,
                    read_by_admin, read_by_buyer
                )
                VALUES ($1, 'admin', $2, $3, $4, $5, $6, $7, TRUE, FALSE)
                RETURNING *
                """,
                thread_id,
                body,
                message_type,
                attachment_id,
                attachment_filename,
                admin_user_id,
                telegram_message_id,
            )
        await conn.execute(
            """
            UPDATE web_chat_threads SET
                admin_unread = 0,
                last_message_at = now(),
                updated_at = now()
            WHERE id = $1
            """,
            thread_id,
        )
        await conn.execute(
            """
            UPDATE web_chat_messages SET read_by_admin = TRUE
            WHERE thread_id = $1
              AND sender_role IN ('buyer', 'exchanger')
              AND read_by_admin = FALSE
            """,
            thread_id,
        )
    return row


async def _insert_telegram_sticker(
    conn,
    *,
    thread_id: int,
    sender_role: str,
    message_id: int,
    attachment_id: str | None,
    sticker_file_id: str | None,
    sticker_emoji: str | None,
    sticker_set_name: str | None,
) -> dict:
    emoji = (sticker_emoji or "").strip()[:32]
    return await _insert_message(
        conn,
        thread_id=thread_id,
        sender_role=sender_role,
        body=emoji or "🎭",
        message_type="sticker",
        attachment_id=attachment_id,
        telegram_message_id=message_id,
        sticker_file_id=(sticker_file_id or "").strip() or None,
        sticker_emoji=emoji or None,
        sticker_set_name=(sticker_set_name or "").strip() or None,
    )


async def buyer_send_message(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    body: str,
    order_id: str | None = None,
) -> dict:
    text = _normalize_body(body)
    thread = await get_or_create_thread(
        session_token=session_token,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _insert_message(
            conn,
            thread_id=thread["id"],
            sender_role="buyer",
            body=text,
            message_type="text",
        )
        await _mark_thread_web_source(conn, thread["id"])
    from chat_auto_reply import maybe_reply_che_kogo

    await maybe_reply_che_kogo(thread["id"], text)
    return _msg_row(row)


async def buyer_send_from_telegram(
    *,
    connection_id: str,
    chat_id: int,
    user_id: int,
    message_id: int,
    body: str | None = None,
    attachment_id: str | None = None,
    caption: str | None = None,
    message_type: str = "image",
    attachment_filename: str | None = None,
    sticker_file_id: str | None = None,
    sticker_emoji: str | None = None,
    sticker_set_name: str | None = None,
) -> dict | None:
    """Входящее из лички @focus_operator (Telegram Business). None если дубликат."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            """
            SELECT id FROM web_chat_messages
            WHERE telegram_message_id = $1
            LIMIT 1
            """,
            message_id,
        )
        if existing:
            return None

        await _touch_bot_user(conn, user_id)

        thread = await _get_or_create_telegram_thread(
            conn,
            telegram_user_id=user_id,
            telegram_dm_chat_id=chat_id,
            business_connection_id=connection_id,
        )

        if sticker_file_id or message_type == "sticker":
            text = ""
            row = await _insert_telegram_sticker(
                conn,
                thread_id=thread["id"],
                sender_role="buyer",
                message_id=message_id,
                attachment_id=attachment_id,
                sticker_file_id=sticker_file_id,
                sticker_emoji=sticker_emoji,
                sticker_set_name=sticker_set_name,
            )
        elif attachment_id:
            text = _normalize_body(caption, allow_empty=True)
            mt = message_type if message_type in ("image", "video", "document", "audio") else "image"
            row = await _insert_message(
                conn,
                thread_id=thread["id"],
                sender_role="buyer",
                body=text,
                message_type=mt,
                attachment_id=attachment_id,
                attachment_filename=attachment_filename,
                telegram_message_id=message_id,
            )
        else:
            text = _normalize_body(body)
            row = await _insert_message(
                conn,
                thread_id=thread["id"],
                sender_role="buyer",
                body=text,
                message_type="text",
                telegram_message_id=message_id,
            )
    logger.info(
        "telegram inbound chat thread=%s user=%s msg=%s",
        thread["id"],
        user_id,
        message_id,
    )
    from chat_auto_reply import maybe_reply_che_kogo

    await maybe_reply_che_kogo(thread["id"], text)
    return _msg_row(row)


async def admin_send_from_telegram(
    *,
    connection_id: str,
    chat_id: int,
    user_id: int,
    message_id: int,
    body: str | None = None,
    attachment_id: str | None = None,
    caption: str | None = None,
    message_type: str = "image",
    attachment_filename: str | None = None,
    sticker_file_id: str | None = None,
    sticker_emoji: str | None = None,
    sticker_set_name: str | None = None,
) -> dict | None:
    """Исходящее оператора из Telegram Business → запись в чат. None если дубликат."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            """
            SELECT id FROM web_chat_messages
            WHERE telegram_message_id = $1
            LIMIT 1
            """,
            message_id,
        )
        if existing:
            return None

        thread = await conn.fetchrow(
            """
            SELECT * FROM web_chat_threads
            WHERE telegram_dm_chat_id = $1
              AND (business_connection_id = $2 OR business_connection_id IS NULL)
            ORDER BY last_message_at DESC NULLS LAST
            LIMIT 1
            """,
            chat_id,
            connection_id,
        )
        if not thread:
            logger.debug(
                "admin telegram outbound: thread not found chat=%s conn=%s",
                chat_id,
                connection_id,
            )
            return None

        thread_id = int(thread["id"])
        if sticker_file_id or message_type == "sticker":
            row = await _insert_telegram_sticker(
                conn,
                thread_id=thread_id,
                sender_role="admin",
                message_id=message_id,
                attachment_id=attachment_id,
                sticker_file_id=sticker_file_id,
                sticker_emoji=sticker_emoji,
                sticker_set_name=sticker_set_name,
            )
        elif attachment_id:
            text = _normalize_body(caption, allow_empty=True)
            mt = (
                message_type
                if message_type in ("image", "video", "document", "audio")
                else "image"
            )
            row = await _insert_message(
                conn,
                thread_id=thread_id,
                sender_role="admin",
                body=text,
                message_type=mt,
                attachment_id=attachment_id,
                attachment_filename=attachment_filename,
                telegram_message_id=message_id,
            )
        else:
            text = _normalize_body(body)
            row = await _insert_message(
                conn,
                thread_id=thread_id,
                sender_role="admin",
                body=text,
                message_type="text",
                telegram_message_id=message_id,
            )

    from exchanger_chat_escalation import clear_exchanger_escalation

    await clear_exchanger_escalation(thread_id)
    logger.info(
        "telegram admin outbound thread=%s user=%s msg=%s",
        thread_id,
        user_id,
        message_id,
    )
    return _msg_row(row)


async def admin_unread_count() -> int:
    counts = await admin_unread_counts_by_source()
    return int(counts.get("all") or 0)


async def admin_unread_counts_by_source() -> dict[str, int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from chat_support_scope import support_operator_user_ids

        exclude = list(await support_operator_user_ids(conn))

        async def _count(source_filter: str | None) -> int:
            clauses = [_NEEDS_REPLY_SQL]
            params: list = []
            ex = _support_exclude_clause(exclude, params)
            if ex:
                clauses.append(ex)
            if source_filter == "web":
                clauses.append("t.source IN ('web', 'both')")
            elif source_filter == "telegram":
                clauses.append("t.source IN ('telegram', 'both')")
            elif source_filter == "exchanger":
                clauses.append("t.source = 'exchanger'")
            where = "WHERE " + " AND ".join(clauses)
            return int(
                await conn.fetchval(
                    f"SELECT COUNT(*)::int FROM web_chat_threads t {where}",
                    *params,
                )
                or 0
            )

        return {
            "all": await _count(None),
            "web": await _count("web"),
            "telegram": await _count("telegram"),
            "exchanger": await _count("exchanger"),
        }


async def get_thread_for_outbound(thread_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM web_chat_threads WHERE id = $1",
            thread_id,
        )
    return dict(row) if row else None


async def buyer_send_image(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    attachment_id: str,
    caption: str | None = None,
    order_id: str | None = None,
) -> dict:
    return await buyer_send_attachment(
        session_token=session_token,
        telegram_user_id=telegram_user_id,
        attachment_id=attachment_id,
        message_type="image",
        caption=caption,
        order_id=order_id,
    )


async def buyer_send_attachment(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    attachment_id: str,
    message_type: str,
    caption: str | None = None,
    attachment_filename: str | None = None,
    order_id: str | None = None,
) -> dict:
    if message_type not in ("image", "video", "document", "audio"):
        raise HTTPException(status_code=400, detail="Invalid message type")
    text = _normalize_body(caption, allow_empty=True)
    thread = await get_or_create_thread(
        session_token=session_token,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await _insert_message(
            conn,
            thread_id=thread["id"],
            sender_role="buyer",
            body=text,
            message_type=message_type,
            attachment_id=attachment_id,
            attachment_filename=attachment_filename,
        )
        await _mark_thread_web_source(conn, thread["id"])
    from chat_auto_reply import maybe_reply_che_kogo

    await maybe_reply_che_kogo(thread["id"], text)
    return _msg_row(row)


async def admin_send_image(
    thread_id: int,
    attachment_id: str,
    caption: str | None = None,
    admin_user_id: int | None = None,
) -> dict:
    return await admin_send_attachment(
        thread_id,
        attachment_id,
        message_type="image",
        caption=caption,
        admin_user_id=admin_user_id,
    )


async def admin_send_attachment(
    thread_id: int,
    attachment_id: str,
    message_type: str,
    caption: str | None = None,
    attachment_filename: str | None = None,
    admin_user_id: int | None = None,
) -> dict:
    from chat_telegram_bridge import mirror_admin_attachment_to_telegram

    if message_type not in ("image", "video", "document", "audio"):
        raise HTTPException(status_code=400, detail="Invalid message type")
    text = _normalize_body(caption, allow_empty=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "SELECT id FROM web_chat_threads WHERE id = $1", thread_id
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        row = await _insert_message(
            conn,
            thread_id=thread_id,
            sender_role="admin",
            body=text,
            message_type=message_type,
            attachment_id=attachment_id,
            attachment_filename=attachment_filename,
            admin_user_id=admin_user_id,
        )
    from exchanger_chat_escalation import clear_exchanger_escalation

    await clear_exchanger_escalation(thread_id)
    logger.info("admin chat attachment thread=%s type=%s admin=%s", thread_id, message_type, admin_user_id)
    msg = _msg_row(row)
    thread_row = await get_thread_for_outbound(thread_id)
    if thread_row:
        await mirror_admin_attachment_to_telegram(
            thread_row, attachment_id, message_type, text, attachment_filename
        )
    return msg


async def verify_attachment_access(
    attachment_id: str,
    *,
    thread_id: int | None = None,
    guest_session: str | None = None,
    telegram_user_id: int | None = None,
    admin: bool = False,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT m.thread_id, t.session_token, t.telegram_user_id
            FROM web_chat_messages m
            JOIN web_chat_threads t ON t.id = m.thread_id
            WHERE m.attachment_id = $1
            LIMIT 1
            """,
            attachment_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    if admin:
        return
    if thread_id and row["thread_id"] != thread_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if telegram_user_id and row["telegram_user_id"] == telegram_user_id:
        return
    if guest_session:
        try:
            token = uuid.UUID(guest_session.strip())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")
        if row["session_token"] == token:
            return
    raise HTTPException(status_code=403, detail="Access denied")


async def buyer_mark_read(thread_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE web_chat_messages SET read_by_buyer = TRUE
            WHERE thread_id = $1 AND sender_role = 'admin' AND read_by_buyer = FALSE
            """,
            thread_id,
        )


async def buyer_get_conversation(
    *,
    session_token: str | None,
    telegram_user_id: int | None,
    order_id: str | None = None,
    after_id: int = 0,
    before_id: int = 0,
    limit: int = 100,
) -> dict:
    thread = await get_thread(
        session_token=session_token,
        telegram_user_id=telegram_user_id,
        order_id=order_id,
    )
    if not thread:
        return {"thread": None, "messages": [], "has_more_older": False, "oldest_id": None}
    await buyer_mark_read(thread["id"])
    window = await list_messages_window(
        thread["id"],
        before_id=before_id,
        after_id=after_id,
        limit=limit,
    )
    return {"thread": thread, **window}


async def get_or_create_exchanger_thread(conn, exchanger_id: int) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM web_chat_threads WHERE external_exchanger_id = $1",
        exchanger_id,
    )
    if not row:
        row = await conn.fetchrow(
            """
            INSERT INTO web_chat_threads (external_exchanger_id, source)
            VALUES ($1, 'exchanger')
            RETURNING *
            """,
            exchanger_id,
        )
    return _thread_summary(row)


async def exchanger_get_conversation(
    *,
    exchanger_id: int,
    after_id: int = 0,
    before_id: int = 0,
    limit: int = 100,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await get_or_create_exchanger_thread(conn, exchanger_id)
    await buyer_mark_read(thread["id"])
    window = await list_messages_window(
        thread["id"],
        before_id=before_id,
        after_id=after_id,
        limit=limit,
    )
    return {"thread": thread, **window}


async def exchanger_send_message(*, exchanger_id: int, body: str) -> dict:
    text = _normalize_body(body)
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await get_or_create_exchanger_thread(conn, exchanger_id)
        row = await _insert_message(
            conn,
            thread_id=thread["id"],
            sender_role="exchanger",
            body=text,
            message_type="text",
        )
        msg_id = int(row["id"])
        thread_id = int(thread["id"])
    from exchanger_chat_escalation import schedule_exchanger_escalation

    await schedule_exchanger_escalation(thread_id, msg_id)
    return _msg_row(row)


async def exchanger_send_attachment(
    *,
    exchanger_id: int,
    attachment_id: str,
    message_type: str,
    caption: str | None = None,
    attachment_filename: str | None = None,
) -> dict:
    if message_type not in ("image", "video", "document", "audio"):
        raise HTTPException(status_code=400, detail="Invalid message type")
    text = _normalize_body(caption, allow_empty=True)
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await get_or_create_exchanger_thread(conn, exchanger_id)
        row = await _insert_message(
            conn,
            thread_id=thread["id"],
            sender_role="exchanger",
            body=text,
            message_type=message_type,
            attachment_id=attachment_id,
            attachment_filename=attachment_filename,
        )
        msg_id = int(row["id"])
        thread_id = int(thread["id"])
    from exchanger_chat_escalation import schedule_exchanger_escalation

    await schedule_exchanger_escalation(thread_id, msg_id)
    return _msg_row(row)


async def admin_list_threads(
    *,
    unread_only: bool = False,
    source_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from chat_support_scope import support_operator_user_ids

        exclude = list(await support_operator_user_ids(conn))
        clauses: list[str] = []
        params: list[object] = []
        if unread_only:
            clauses.append(_NEEDS_REPLY_SQL)
        if source_filter == "web":
            clauses.append("t.source IN ('web', 'both')")
        elif source_filter == "telegram":
            clauses.append("t.source IN ('telegram', 'both')")
        elif source_filter == "exchanger":
            clauses.append("t.source = 'exchanger'")
        if exclude:
            idx = len(params) + 1
            clauses.append(
                f"(t.telegram_user_id IS NULL OR NOT (t.telegram_user_id = ANY(${idx}::bigint[])))"
            )
            params.append(exclude)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total = await conn.fetchval(
            f"SELECT COUNT(*)::int FROM web_chat_threads t {where}",
            *params,
        )
        limit_idx = len(params) + 1
        offset_idx = len(params) + 2
        rows = await conn.fetch(
            f"""
            SELECT t.*,
                (SELECT m.body FROM web_chat_messages m
                 WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_body,
                (SELECT m.message_type FROM web_chat_messages m
                 WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_message_type,
                (SELECT sender_role FROM web_chat_messages m
                 WHERE m.thread_id = t.id ORDER BY m.id DESC LIMIT 1) AS last_sender,
                (SELECT COUNT(*)::int FROM web_chat_messages m
                 WHERE m.thread_id = t.id) AS message_count
            FROM web_chat_threads t
            {where}
            ORDER BY t.last_message_at DESC NULLS LAST, t.id DESC
            LIMIT ${limit_idx} OFFSET ${offset_idx}
            """,
            *params,
            min(limit, 200),
            offset,
        )
        threads = []
        for r in rows:
            last_body = r.get("last_body")
            last_type = r.get("last_message_type") or "text"
            if last_type != "text":
                cap = (last_body or "").strip()
                preview = _preview_body({"message_type": last_type, "body": last_body})
                last_body = preview
            s = await _enrich_thread(
                conn,
                r,
                last_body=last_body,
                last_sender=r.get("last_sender"),
            )
            s["message_count"] = int(r.get("message_count") or 0)
            threads.append(s)
    from bot_user_avatars import schedule_prefetch_bot_user_avatars

    avatar_ids: list[int] = []
    for t in threads:
        buyer = t.get("buyer") or {}
        if buyer.get("guest"):
            continue
        try:
            uid = int(buyer.get("user_id") or 0)
        except (TypeError, ValueError):
            continue
        if uid > 0:
            avatar_ids.append(uid)
    schedule_prefetch_bot_user_avatars(avatar_ids)
    return {"threads": threads, "total": total}


async def admin_get_thread(
    thread_id: int,
    *,
    before_id: int = 0,
    after_id: int = 0,
    limit: int = 100,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        from chat_support_scope import is_support_operator_user, support_operator_user_ids

        row = await conn.fetchrow(
            "SELECT * FROM web_chat_threads WHERE id = $1", thread_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Thread not found")
        exclude = await support_operator_user_ids(conn)
        if is_support_operator_user(row.get("telegram_user_id"), exclude):
            raise HTTPException(status_code=404, detail="Thread not found")
        incremental = after_id > 0
        if not incremental:
            await conn.execute(
                """
                UPDATE web_chat_messages SET read_by_admin = TRUE
                WHERE thread_id = $1
                  AND sender_role IN ('buyer', 'exchanger')
                  AND read_by_admin = FALSE
                """,
                thread_id,
            )
            await conn.execute(
                "UPDATE web_chat_threads SET admin_unread = 0, updated_at = now() WHERE id = $1",
                thread_id,
            )
        profile = None
        if incremental:
            thread = _thread_summary(row)
        else:
            thread = await _enrich_thread(conn, row)
            uid = row.get("telegram_user_id")
            if uid:
                try:
                    from bot_user_avatars import fetch_and_cache_bot_user_avatar

                    await fetch_and_cache_bot_user_avatar(int(uid))
                except Exception:
                    logger.debug("chat thread avatar fetch uid=%s", uid, exc_info=True)
                from buyer_profile_service import build_buyer_profile

                profile = await build_buyer_profile(
                    conn, int(uid), mode="operator", include_finance=False
                )
    window = await list_messages_window(
        thread_id, before_id=before_id, after_id=after_id, limit=limit
    )
    thread["message_count"] = await _thread_message_count(thread_id)
    return {
        "thread": thread,
        "messages": window["messages"],
        "has_more_older": window["has_more_older"],
        "oldest_id": window["oldest_id"],
        "buyer_profile": profile,
    }


async def _thread_message_count(thread_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*)::int FROM web_chat_messages WHERE thread_id = $1",
                thread_id,
            )
            or 0
        )


async def admin_send_message(
    thread_id: int,
    body: str,
    admin_user_id: int | None = None,
) -> dict:
    from chat_telegram_bridge import mirror_admin_text_to_telegram

    text = _normalize_body(body)
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "SELECT id FROM web_chat_threads WHERE id = $1", thread_id
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        row = await _insert_message(
            conn,
            thread_id=thread_id,
            sender_role="admin",
            body=text,
            message_type="text",
            admin_user_id=admin_user_id,
        )
    from exchanger_chat_escalation import clear_exchanger_escalation

    await clear_exchanger_escalation(thread_id)
    logger.info("admin chat reply thread=%s admin=%s", thread_id, admin_user_id)
    msg = _msg_row(row)
    thread_row = await get_thread_for_outbound(thread_id)
    if thread_row:
        await mirror_admin_text_to_telegram(thread_row, text)
    return msg


async def admin_send_sticker(
    thread_id: int,
    file_id: str,
    admin_user_id: int | None = None,
    *,
    operator_id: int | None = None,
) -> dict:
    from chat_stickers import fetch_operator_sticker_sets, sticker_file_id_allowed
    from chat_telegram_bridge import mirror_admin_sticker_to_telegram

    fid = (file_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="file_id required")
    if not await sticker_file_id_allowed(fid, operator_id=operator_id):
        raise HTTPException(status_code=400, detail="Стикер недоступен")

    emoji = ""
    set_name = None
    for st_set in await fetch_operator_sticker_sets(operator_id):
        for st in st_set.get("stickers") or []:
            if st.get("file_id") == fid:
                emoji = (st.get("emoji") or "").strip()
                set_name = st_set.get("name")
                break
        if set_name:
            break

    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            "SELECT id FROM web_chat_threads WHERE id = $1", thread_id
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        row = await _insert_message(
            conn,
            thread_id=thread_id,
            sender_role="admin",
            body=emoji or "🎭",
            message_type="sticker",
            admin_user_id=admin_user_id,
            sticker_file_id=fid,
            sticker_emoji=emoji or None,
            sticker_set_name=set_name,
        )
    from exchanger_chat_escalation import clear_exchanger_escalation

    await clear_exchanger_escalation(thread_id)
    logger.info("admin chat sticker thread=%s admin=%s", thread_id, admin_user_id)
    msg = _msg_row(row)
    thread_row = await get_thread_for_outbound(thread_id)
    if thread_row:
        await mirror_admin_sticker_to_telegram(thread_row, fid)
    return msg

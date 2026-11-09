"""Quick replies and shared templates with RBAC object-ACL."""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Any

from fastapi import HTTPException

from permissions import (
    PERM_TEMPLATES_CREATE,
    PERM_TEMPLATES_DELETE_ANY,
    PERM_TEMPLATES_DELETE_OWN,
    PERM_TEMPLATES_EDIT_ANY,
    PERM_TEMPLATES_EDIT_OWN,
    PERM_TEMPLATES_EDIT_SYSTEM,
    PERM_TEMPLATES_MANAGE_PRIORITY,
    PERM_TEMPLATES_VIEW,
    has_permission,
    require_permission,
)

logger = logging.getLogger("chat_templates")

_COOLDOWN = timedelta(minutes=30)
_MAX_PERSONAL = 50
_MAX_GLOBAL = 50
_PRIORITY_MIN = 0
_PRIORITY_MAX = 9999


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "operator_id": row["operator_id"],
        "scope": "global" if row["operator_id"] is None else "personal",
        "title": row["title"],
        "body": row["body"],
        "trigger_phrase": row["trigger_phrase"],
        "sort_order": row["sort_order"],
        "is_active": row["is_active"],
        "is_system": bool(row.get("is_system") or False),
        "version": int(row.get("version") or 1),
        "created_by_operator_id": row.get("created_by_operator_id"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


_SELECT_COLS = """
id, operator_id, title, body, trigger_phrase, sort_order,
is_active, created_at, updated_at,
COALESCE(is_system, FALSE) AS is_system,
COALESCE(version, 1) AS version,
created_by_operator_id
"""


def _normalize_text(text: str | None) -> str:
    raw = (text or "").strip().lower().replace("ё", "е")
    compact = re.sub(r"[^\w\s]+", " ", raw)
    return re.sub(r"\s+", " ", compact).strip()


def matches_trigger(buyer_text: str | None, trigger_phrase: str | None) -> bool:
    trigger = (trigger_phrase or "").strip()
    if not trigger:
        return False
    trig_norm = _normalize_text(trigger)
    if not trig_norm:
        return False
    if trig_norm in ("че кого", "чекого"):
        from chat_auto_reply import matches_che_kogo

        return matches_che_kogo(buyer_text)
    buyer_norm = _normalize_text(buyer_text)
    if not buyer_norm:
        return False
    if " " in trig_norm:
        return trig_norm in buyer_norm
    return bool(re.search(rf"\b{re.escape(trig_norm)}\b", buyer_norm))


def _validate_fields(
    *,
    title: str | None,
    body: str | None,
    trigger_phrase: str | None = None,
    sort_order: int | None = None,
    require_nonempty: bool = True,
) -> tuple[str | None, str | None, str | None, int | None]:
    new_title = None if title is None else title.strip()
    new_body = None if body is None else body.strip()
    if require_nonempty:
        if not new_title or not new_body:
            raise HTTPException(status_code=400, detail="title и body обязательны")
    if new_title is not None and len(new_title) > 64:
        raise HTTPException(status_code=400, detail="Слишком длинный title")
    if new_body is not None and len(new_body) > 2000:
        raise HTTPException(status_code=400, detail="Слишком длинный body")
    trigger = None
    if trigger_phrase is not None:
        trigger = (trigger_phrase or "").strip() or None
        if trigger and len(trigger) > 256:
            raise HTTPException(status_code=400, detail="trigger_phrase слишком длинный")
    if sort_order is not None:
        so = int(sort_order)
        if so < _PRIORITY_MIN or so > _PRIORITY_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Приоритет: целое число {_PRIORITY_MIN}–{_PRIORITY_MAX}",
            )
        sort_order = so
    return new_title, new_body, trigger, sort_order


async def _audit(
    conn,
    *,
    template_id: int,
    action: str,
    actor_kind: str,
    actor_id: int | None,
    before: dict | None,
    after: dict | None,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO operator_chat_template_audit
              (template_id, actor_kind, actor_id, action, before_json, after_json)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
            """,
            int(template_id),
            actor_kind,
            actor_id,
            action,
            json.dumps(before, ensure_ascii=False) if before else None,
            json.dumps(after, ensure_ascii=False) if after else None,
        )
    except Exception:
        logger.exception("template audit failed id=%s action=%s", template_id, action)


def _is_owner(row, operator_id: int) -> bool:
    created_by = row.get("created_by_operator_id")
    if created_by is not None:
        return int(created_by) == int(operator_id)
    # personal template
    if row.get("operator_id") is not None:
        return int(row["operator_id"]) == int(operator_id)
    return False


def assert_can_mutate_template(
    principal: dict,
    row,
    *,
    action: str,
) -> None:
    """action: update | delete | priority."""
    is_system = bool(row.get("is_system"))
    if is_system and not has_permission(principal, PERM_TEMPLATES_EDIT_SYSTEM):
        raise HTTPException(status_code=403, detail="Системный шаблон нельзя менять")

    op_id = principal.get("id")
    owner = op_id is not None and _is_owner(row, int(op_id))

    if action == "delete":
        if owner and has_permission(principal, PERM_TEMPLATES_DELETE_OWN):
            return
        if has_permission(principal, PERM_TEMPLATES_DELETE_ANY):
            return
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления")

    if action == "priority":
        require_permission(principal, PERM_TEMPLATES_MANAGE_PRIORITY)
        if owner or has_permission(principal, PERM_TEMPLATES_EDIT_ANY) or has_permission(
            principal, PERM_TEMPLATES_EDIT_SYSTEM
        ):
            return
        if is_system:
            raise HTTPException(status_code=403, detail="Системный шаблон нельзя менять")
        raise HTTPException(status_code=403, detail="Недостаточно прав для приоритета")

    # update
    if owner and has_permission(principal, PERM_TEMPLATES_EDIT_OWN):
        return
    if has_permission(principal, PERM_TEMPLATES_EDIT_ANY):
        return
    raise HTTPException(status_code=403, detail="Недостаточно прав для редактирования")


async def list_templates_for_operator(operator_id: int) -> dict[str, list[dict]]:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SELECT_COLS}
            FROM operator_chat_templates
            WHERE is_active
              AND (operator_id IS NULL OR operator_id = $1)
            ORDER BY (operator_id IS NULL) DESC, sort_order, id
            """,
            int(operator_id),
        )
    global_items: list[dict] = []
    personal_items: list[dict] = []
    for row in rows:
        item = _row_to_dict(row)
        if row["operator_id"] is None:
            global_items.append(item)
        else:
            personal_items.append(item)
    return {"global": global_items, "personal": personal_items}


async def list_global_templates_admin() -> list[dict]:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT {_SELECT_COLS}
            FROM operator_chat_templates
            WHERE operator_id IS NULL
            ORDER BY sort_order, id
            """
        )
    return [_row_to_dict(r) for r in rows]


async def create_personal_template(
    operator_id: int,
    *,
    title: str,
    body: str,
    trigger_phrase: str | None = None,
    sort_order: int = 0,
) -> dict:
    title, body, trigger, sort_order = _validate_fields(
        title=title, body=body, trigger_phrase=trigger_phrase, sort_order=sort_order
    )
    if not title or not body or sort_order is None:
        raise HTTPException(status_code=400, detail="template fields required")

    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM operator_chat_templates WHERE operator_id = $1",
            int(operator_id),
        )
        if int(count or 0) >= _MAX_PERSONAL:
            raise HTTPException(status_code=400, detail=f"Не более {_MAX_PERSONAL} личных шаблонов")

        row = await conn.fetchrow(
            f"""
            INSERT INTO operator_chat_templates
              (operator_id, title, body, trigger_phrase, sort_order,
               created_by_operator_id, is_system, version)
            VALUES ($1, $2, $3, $4, $5, $1, FALSE, 1)
            RETURNING {_SELECT_COLS}
            """,
            int(operator_id),
            title,
            body,
            trigger,
            int(sort_order),
        )
        item = _row_to_dict(row)
        await _audit(
            conn,
            template_id=item["id"],
            action="create",
            actor_kind="operator",
            actor_id=int(operator_id),
            before=None,
            after=item,
        )
    return item


async def create_global_template(
    *,
    title: str,
    body: str,
    trigger_phrase: str | None = None,
    sort_order: int = 0,
    created_by_operator_id: int | None = None,
    is_system: bool = False,
    actor_kind: str = "operator",
    actor_id: int | None = None,
    principal: dict | None = None,
) -> dict:
    if principal is not None:
        require_permission(principal, PERM_TEMPLATES_CREATE)
        if is_system and not has_permission(principal, PERM_TEMPLATES_EDIT_SYSTEM):
            raise HTTPException(status_code=403, detail="Нельзя создавать системные шаблоны")
        if created_by_operator_id is None and principal.get("id") and not principal.get("is_admin"):
            created_by_operator_id = int(principal["id"])
            actor_id = int(principal["id"])
            actor_kind = "operator"
        elif principal.get("is_admin"):
            actor_kind = "admin"
            actor_id = int(principal.get("id") or 0) or None

    title, body, trigger, sort_order = _validate_fields(
        title=title, body=body, trigger_phrase=trigger_phrase, sort_order=sort_order
    )
    if not title or not body or sort_order is None:
        raise HTTPException(status_code=400, detail="template fields required")

    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Уникальность приоритета в global scope среди активных.
            clash = await conn.fetchval(
                """
                SELECT id FROM operator_chat_templates
                WHERE operator_id IS NULL AND is_active AND sort_order = $1
                LIMIT 1
                """,
                int(sort_order),
            )
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail="Приоритет уже занят другим шаблоном",
                )

            count = await conn.fetchval(
                "SELECT COUNT(*) FROM operator_chat_templates WHERE operator_id IS NULL"
            )
            if int(count or 0) >= _MAX_GLOBAL:
                raise HTTPException(
                    status_code=400, detail=f"Не более {_MAX_GLOBAL} общих шаблонов"
                )

            row = await conn.fetchrow(
                f"""
                INSERT INTO operator_chat_templates
                  (operator_id, title, body, trigger_phrase, sort_order,
                   created_by_operator_id, is_system, version)
                VALUES (NULL, $1, $2, $3, $4, $5, $6, 1)
                RETURNING {_SELECT_COLS}
                """,
                title,
                body,
                trigger,
                int(sort_order),
                created_by_operator_id,
                bool(is_system),
            )
            item = _row_to_dict(row)
            await _audit(
                conn,
                template_id=item["id"],
                action="create",
                actor_kind=actor_kind,
                actor_id=actor_id,
                before=None,
                after=item,
            )
    return item


async def update_personal_template(
    operator_id: int,
    template_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    trigger_phrase: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
    version: int | None = None,
) -> dict:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = $1 AND operator_id = $2
                FOR UPDATE
                """,
                int(template_id),
                int(operator_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Шаблон не найден")
            if version is not None and int(row["version"]) != int(version):
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )

            new_title = (title if title is not None else row["title"]).strip()
            new_body = (body if body is not None else row["body"]).strip()
            if trigger_phrase is not None:
                new_trigger = (trigger_phrase or "").strip() or None
            else:
                new_trigger = row["trigger_phrase"]
            new_sort = int(sort_order) if sort_order is not None else row["sort_order"]
            new_active = is_active if is_active is not None else row["is_active"]
            _validate_fields(
                title=new_title,
                body=new_body,
                trigger_phrase=new_trigger,
                sort_order=new_sort,
            )

            before = _row_to_dict(row)
            updated = await conn.fetchrow(
                f"""
                UPDATE operator_chat_templates
                SET title = $3, body = $4, trigger_phrase = $5, sort_order = $6,
                    is_active = $7, updated_at = now(), version = version + 1
                WHERE id = $1 AND operator_id = $2 AND version = $8
                RETURNING {_SELECT_COLS}
                """,
                int(template_id),
                int(operator_id),
                new_title,
                new_body,
                new_trigger,
                new_sort,
                new_active,
                int(row["version"]),
            )
            if not updated:
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )
            item = _row_to_dict(updated)
            await _audit(
                conn,
                template_id=item["id"],
                action="update",
                actor_kind="operator",
                actor_id=int(operator_id),
                before=before,
                after=item,
            )
    return item


async def update_global_template(
    template_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    trigger_phrase: str | None = None,
    sort_order: int | None = None,
    is_active: bool | None = None,
    version: int | None = None,
    principal: dict | None = None,
    actor_kind: str = "operator",
    actor_id: int | None = None,
) -> dict:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = $1 AND operator_id IS NULL
                FOR UPDATE
                """,
                int(template_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Шаблон не найден")

            if principal is not None:
                action = "priority" if (
                    sort_order is not None
                    and title is None
                    and body is None
                    and trigger_phrase is None
                    and is_active is None
                ) else "update"
                assert_can_mutate_template(principal, row, action=action)
                if not principal.get("is_admin"):
                    actor_kind = "operator"
                    actor_id = int(principal["id"])
                else:
                    actor_kind = "admin"
                    actor_id = int(principal.get("id") or 0) or None

            if version is not None and int(row["version"]) != int(version):
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )

            new_title = (title if title is not None else row["title"]).strip()
            new_body = (body if body is not None else row["body"]).strip()
            if not new_title or not new_body:
                raise HTTPException(status_code=400, detail="title и body обязательны")
            if trigger_phrase is not None:
                new_trigger = (trigger_phrase or "").strip() or None
            else:
                new_trigger = row["trigger_phrase"]
            new_sort = int(sort_order) if sort_order is not None else int(row["sort_order"])
            new_active = is_active if is_active is not None else row["is_active"]
            _validate_fields(
                title=new_title,
                body=new_body,
                trigger_phrase=new_trigger,
                sort_order=new_sort,
            )

            if new_sort != int(row["sort_order"]):
                clash = await conn.fetchval(
                    """
                    SELECT id FROM operator_chat_templates
                    WHERE operator_id IS NULL AND is_active AND sort_order = $1 AND id <> $2
                    LIMIT 1
                    """,
                    new_sort,
                    int(template_id),
                )
                if clash:
                    raise HTTPException(
                        status_code=409,
                        detail="Приоритет уже занят другим шаблоном",
                    )

            before = _row_to_dict(row)
            updated = await conn.fetchrow(
                f"""
                UPDATE operator_chat_templates
                SET title = $2, body = $3, trigger_phrase = $4, sort_order = $5,
                    is_active = $6, updated_at = now(), version = version + 1
                WHERE id = $1 AND operator_id IS NULL AND version = $7
                RETURNING {_SELECT_COLS}
                """,
                int(template_id),
                new_title,
                new_body,
                new_trigger,
                new_sort,
                new_active,
                int(row["version"]),
            )
            if not updated:
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )
            item = _row_to_dict(updated)
            audit_action = "priority" if (
                sort_order is not None
                and title is None
                and body is None
                and trigger_phrase is None
                and is_active is None
            ) else "update"
            await _audit(
                conn,
                template_id=item["id"],
                action=audit_action,
                actor_kind=actor_kind,
                actor_id=actor_id,
                before=before,
                after=item,
            )
    return item


async def delete_personal_template(operator_id: int, template_id: int) -> None:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = $1 AND operator_id = $2
                FOR UPDATE
                """,
                int(template_id),
                int(operator_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Шаблон не найден")
            before = _row_to_dict(row)
            await conn.execute(
                "DELETE FROM operator_chat_templates WHERE id = $1 AND operator_id = $2",
                int(template_id),
                int(operator_id),
            )
            await _audit(
                conn,
                template_id=int(template_id),
                action="delete",
                actor_kind="operator",
                actor_id=int(operator_id),
                before=before,
                after=None,
            )


async def swap_global_template_priorities(
    template_id_a: int,
    template_id_b: int,
    *,
    principal: dict,
    version_a: int | None = None,
    version_b: int | None = None,
) -> dict[str, list[dict]]:
    """Атомарный обмен приоритетов (без промежуточного unique-конфликта)."""
    require_permission(principal, PERM_TEMPLATES_MANAGE_PRIORITY)
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = ANY($1::int[]) AND operator_id IS NULL
                FOR UPDATE
                """,
                [int(template_id_a), int(template_id_b)],
            )
            by_id = {int(r["id"]): r for r in rows}
            row_a = by_id.get(int(template_id_a))
            row_b = by_id.get(int(template_id_b))
            if not row_a or not row_b:
                raise HTTPException(status_code=404, detail="Шаблон не найден")
            assert_can_mutate_template(principal, row_a, action="priority")
            assert_can_mutate_template(principal, row_b, action="priority")
            if version_a is not None and int(row_a["version"]) != int(version_a):
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )
            if version_b is not None and int(row_b["version"]) != int(version_b):
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )

            order_a = int(row_a["sort_order"])
            order_b = int(row_b["sort_order"])
            # Временный приоритет вне диапазона UI, чтобы обойти unique.
            tmp = _PRIORITY_MAX + 1 + int(template_id_a)
            await conn.execute(
                """
                UPDATE operator_chat_templates
                SET sort_order = $2, updated_at = now(), version = version + 1
                WHERE id = $1 AND version = $3
                """,
                int(template_id_a),
                tmp,
                int(row_a["version"]),
            )
            await conn.execute(
                """
                UPDATE operator_chat_templates
                SET sort_order = $2, updated_at = now(), version = version + 1
                WHERE id = $1 AND version = $3
                """,
                int(template_id_b),
                order_a,
                int(row_b["version"]),
            )
            await conn.execute(
                """
                UPDATE operator_chat_templates
                SET sort_order = $2, updated_at = now(), version = version + 1
                WHERE id = $1
                """,
                int(template_id_a),
                order_b,
            )
            updated = await conn.fetch(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = ANY($1::int[])
                """,
                [int(template_id_a), int(template_id_b)],
            )
            items = [_row_to_dict(r) for r in updated]
            actor_kind = "admin" if principal.get("is_admin") else "operator"
            actor_id = int(principal.get("id") or 0) or None
            for before_row, after_item in (
                (_row_to_dict(row_a), next(i for i in items if i["id"] == int(template_id_a))),
                (_row_to_dict(row_b), next(i for i in items if i["id"] == int(template_id_b))),
            ):
                await _audit(
                    conn,
                    template_id=after_item["id"],
                    action="priority",
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    before=before_row,
                    after=after_item,
                )
    return {"items": items}


async def delete_global_template(
    template_id: int,
    *,
    principal: dict | None = None,
    version: int | None = None,
    actor_kind: str = "operator",
    actor_id: int | None = None,
) -> None:
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"""
                SELECT {_SELECT_COLS}
                FROM operator_chat_templates
                WHERE id = $1 AND operator_id IS NULL
                FOR UPDATE
                """,
                int(template_id),
            )
            if not row:
                raise HTTPException(status_code=404, detail="Шаблон не найден")
            if principal is not None:
                assert_can_mutate_template(principal, row, action="delete")
                if not principal.get("is_admin"):
                    actor_kind = "operator"
                    actor_id = int(principal["id"])
                else:
                    actor_kind = "admin"
                    actor_id = int(principal.get("id") or 0) or None
            if version is not None and int(row["version"]) != int(version):
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )
            before = _row_to_dict(row)
            result = await conn.execute(
                """
                DELETE FROM operator_chat_templates
                WHERE id = $1 AND operator_id IS NULL AND version = $2
                """,
                int(template_id),
                int(row["version"]),
            )
            if result == "DELETE 0":
                raise HTTPException(
                    status_code=409,
                    detail="Шаблон изменён другим пользователем, обновите данные",
                )
            await _audit(
                conn,
                template_id=int(template_id),
                action="delete",
                actor_kind=actor_kind,
                actor_id=actor_id,
                before=before,
                after=None,
            )


async def _cooldown_active(conn, thread_id: int, body: str) -> bool:
    recent = await conn.fetchval(
        """
        SELECT id FROM web_chat_messages
        WHERE thread_id = $1
          AND sender_role = 'admin'
          AND body = $2
          AND created_at > now() - $3::interval
        LIMIT 1
        """,
        int(thread_id),
        body,
        _COOLDOWN,
    )
    return bool(recent)


async def maybe_apply_auto_replies(thread_id: int, buyer_text: str | None) -> None:
    """Send first matching trigger template (global + personal), with cooldown."""
    from db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, body, trigger_phrase
            FROM operator_chat_templates
            WHERE is_active AND trigger_phrase IS NOT NULL AND trigger_phrase <> ''
            ORDER BY (operator_id IS NULL) DESC, sort_order, id
            """
        )

    for row in rows:
        if not matches_trigger(buyer_text, row["trigger_phrase"]):
            continue
        body = row["body"]
        async with pool.acquire() as conn:
            if await _cooldown_active(conn, thread_id, body):
                return
        from chat_service import admin_send_message

        try:
            await admin_send_message(thread_id, body, admin_user_id=None)
            logger.info(
                "auto-reply template=%s thread=%s",
                row["id"],
                thread_id,
            )
        except Exception:
            logger.exception("auto-reply failed template=%s thread=%s", row["id"], thread_id)
        return

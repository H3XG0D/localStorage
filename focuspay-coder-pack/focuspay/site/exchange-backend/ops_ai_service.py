"""Бизнес-логика Ops AI: чат, задачи, learning notes, уведомления."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from html import escape

from db import get_pool

import ops_ai_llm
import ops_ai_rag
from config import settings
from telegram_notify import send_admin_message

logger = logging.getLogger("ops_ai_service")

# Process-local sliding window. NOT a substitute for JWT / 2FA / RBAC / nginx.
# Passing this check must never skip get_current_admin / operator auth.
_RATE: dict[int, list[float]] = {}
_RATE_IS_PROCESS_LOCAL = True
_PRIV_IDEMP: dict[str, tuple[float, str, dict]] = {}
_PRIV_IDEMP_TTL = 3600.0


def rate_limit_is_authoritative() -> bool:
    """In-process map is best-effort only. Auth and server limits still apply."""
    return False


def _rate_ok(operator_id: int) -> bool:
    import time

    oid = int(operator_id or 0)
    if oid == 0:
        return False
    now = time.time()
    window = 60.0
    limit = int(settings.ops_ai_rate_per_min or 20)
    bucket = [t for t in _RATE.get(oid, []) if now - t < window]
    if len(bucket) >= limit:
        _RATE[oid] = bucket
        return False
    bucket.append(now)
    _RATE[oid] = bucket
    return True


def _priv_idem_scope_key(
    *,
    kind: str,
    actor_kind: str,
    actor_id: int,
    task_id: int,
    action: str = "",
    client_key: str | None = None,
) -> str | None:
    """Bind cache to actor+task. Never key by client token alone (cross-user replay)."""
    aid = int(actor_id or 0)
    tid = int(task_id or 0)
    token = (client_key or "").strip()[:128]
    if aid <= 0 or tid <= 0 or not token:
        return None
    kind_n = (kind or "").strip().lower()[:32]
    actor = (actor_kind or "admin").strip().lower()[:16]
    act = (action or "").strip().lower()[:32]
    return f"{kind_n}:{actor}:{aid}:task:{tid}:{act}:{token}"


def _priv_idem_get(key: str, *, scope: str) -> dict | None:
    import time

    now = time.time()
    item = _PRIV_IDEMP.get(key)
    if not item:
        return None
    ts, stored_scope, payload = item
    if now - ts > _PRIV_IDEMP_TTL:
        _PRIV_IDEMP.pop(key, None)
        return None
    if stored_scope != scope:
        return None
    return payload


def _priv_idem_put(key: str, payload: dict, *, scope: str) -> None:
    import time

    _PRIV_IDEMP[key] = (time.time(), scope, payload)


def refuse_auto_cursor_and_git() -> dict[str, Any]:
    """Hard stop: service layer never executes Cursor prompts / git / subprocess."""
    return {
        "cursor_execute": False,
        "git": False,
        "subprocess": False,
        "auto_deploy": False,
        "reason": "ops_ai_requires_human_approve_and_manual_apply",
    }


def _row(r) -> dict[str, Any]:
    return dict(r) if r is not None else {}


async def list_sessions(operator_id: int, *, limit: int = 30) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, operator_id, title, created_at, updated_at
            FROM ops_ai_chat_sessions
            WHERE operator_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            operator_id,
            limit,
        )
    return [_row(r) for r in rows]


async def create_session(operator_id: int, title: str = "Чат") -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ops_ai_chat_sessions (operator_id, title)
            VALUES ($1, $2)
            RETURNING id, operator_id, title, created_at, updated_at
            """,
            operator_id,
            (title or "Чат")[:120],
        )
    return _row(row)


async def get_session(session_id: int, operator_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, operator_id, title, created_at, updated_at
            FROM ops_ai_chat_sessions
            WHERE id = $1 AND operator_id = $2
            """,
            session_id,
            operator_id,
        )
    return _row(row) if row else None


async def list_messages(session_id: int, operator_id: int) -> list[dict]:
    sess = await get_session(session_id, operator_id)
    if not sess:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, role, content, sources_json, attachments_json, created_at
            FROM ops_ai_chat_messages
            WHERE session_id = $1
            ORDER BY id ASC
            LIMIT 200
            """,
            session_id,
        )
    out = []
    for r in rows:
        d = _row(r)
        src = d.get("sources_json")
        if isinstance(src, str):
            try:
                d["sources_json"] = json.loads(src)
            except json.JSONDecodeError:
                d["sources_json"] = []
        at = d.get("attachments_json")
        if isinstance(at, str):
            try:
                at = json.loads(at)
            except json.JSONDecodeError:
                at = []
        safe = []
        for i, a in enumerate(at or []):
            if isinstance(a, dict):
                safe.append(
                    {
                        "index": i,
                        "name": a.get("name"),
                        "content_type": a.get("content_type"),
                        "size": a.get("size"),
                    }
                )
        d["attachments_json"] = safe
        out.append(d)
    return out


async def chat_send(
    *,
    operator_id: int,
    session_id: int,
    content: str,
    ui_context: dict | None = None,
    image_files: list[tuple[bytes, str | None]] | None = None,
) -> dict:
    if not _rate_ok(operator_id):
        raise PermissionError("Слишком много запросов, подождите минуту")
    text = (content or "").strip()
    images_in = image_files or []
    if not text and not images_in:
        raise ValueError("Пустое сообщение")
    if not text and images_in:
        text = "Смотри скриншот — что не так / что видно?"
    if len(text) > 4000:
        raise ValueError("Сообщение слишком длинное")
    sess = await get_session(session_id, operator_id)
    if not sess:
        raise LookupError("Чат не найден")

    import ops_ai_attachments

    attachments: list[dict] = []
    if images_in:
        try:
            attachments = ops_ai_attachments.save_images(session_id, images_in)
        except Exception as e:
            raise ValueError(str(e)) from e

    pool = await get_pool()
    async with pool.acquire() as conn:
        user_msg = await conn.fetchrow(
            """
            INSERT INTO ops_ai_chat_messages (session_id, role, content, attachments_json)
            VALUES ($1, 'user', $2, $3::jsonb)
            RETURNING id, session_id, role, content, sources_json, attachments_json, created_at
            """,
            session_id,
            text,
            json.dumps(attachments, ensure_ascii=False),
        )
        hist_rows = await conn.fetch(
            """
            SELECT role, content FROM ops_ai_chat_messages
            WHERE session_id = $1 AND id < $2
            ORDER BY id DESC LIMIT 12
            """,
            session_id,
            user_msg["id"],
        )

    history = [
        {"role": r["role"], "content": r["content"]}
        for r in reversed(list(hist_rows))
        if r["role"] in ("user", "assistant")
    ]

    import ops_ai_grill

    grill = ops_ai_grill.parse_user_request(text)
    if ops_ai_grill.needs_grill(grill):
        answer = ops_ai_grill.format_grill_reply(grill)
        sources = [{"path": "grill-me", "title": "Прожарка контекста", "score": 100}]
        async with pool.acquire() as conn:
            asst = await conn.fetchrow(
                """
                INSERT INTO ops_ai_chat_messages (session_id, role, content, sources_json)
                VALUES ($1, 'assistant', $2, $3::jsonb)
                RETURNING id, session_id, role, content, sources_json, attachments_json, created_at
                """,
                session_id,
                answer,
                json.dumps(sources, ensure_ascii=False),
            )
            await conn.execute(
                "UPDATE ops_ai_chat_sessions SET updated_at = NOW() WHERE id = $1",
                session_id,
            )
        um = _row(user_msg)
        am = _row(asst)
        if isinstance(am.get("sources_json"), str):
            am["sources_json"] = sources
        if isinstance(um.get("attachments_json"), str):
            try:
                um["attachments_json"] = json.loads(um["attachments_json"])
            except json.JSONDecodeError:
                um["attachments_json"] = attachments
        return {"user": um, "assistant": am, "sources": sources, "grilled": True}

    import ops_ai_surface

    surface = ops_ai_surface.infer_task_surface(text, ui_context)
    surface_block = ops_ai_surface.surface_prompt_block(surface)
    chunks = ops_ai_rag.retrieve(
        ops_ai_surface.rag_query_for_surface(text, surface), limit=8
    )
    import privacy_redaction

    rag_ctx = privacy_redaction.redact_text(
        ops_ai_rag.format_context(chunks), keep_short_ids=True
    )
    try:
        import ops_ai_live_context

        if surface.get("include_live_rates"):
            live = await ops_ai_live_context.build_live_snapshot()
        else:
            live = ops_ai_live_context.live_rates_not_a_target_note()
    except Exception as e:
        logger.warning("live context: %s", e)
        live = ""
    try:
        import ops_ai_ui_context

        ui_block = await ops_ai_ui_context.build_ui_context_block(ui_context)
    except Exception as e:
        logger.warning("ui context: %s", e)
        ui_block = ""
    memory_block = ""
    try:
        import ops_ai_memory

        memory_block = await ops_ai_memory.format_memory_block(
            query=text, operator_id=operator_id, limit=12
        )
    except Exception as e:
        logger.warning("memory context: %s", e)
    context = "\n\n".join(
        p
        for p in (surface_block, ui_block, live, memory_block, f"# RAG\n{rag_ctx}")
        if p
    ).strip()

    data_urls: list[str] = []
    for meta in attachments:
        try:
            path, ctype = ops_ai_attachments.read_attachment(meta)
            data_urls.append(ops_ai_attachments.to_data_url(path, ctype))
        except Exception as e:
            logger.warning("attach read: %s", e)

    remembered: dict | None = None
    try:
        import ops_ai_memory

        remembered = await ops_ai_memory.maybe_remember_from_chat(
            operator_id=operator_id,
            text=text,
            operator_label=f"op#{operator_id}",
        )
    except Exception as e:
        logger.warning("remember from chat: %s", e)

    import ops_ai_audit
    import ops_ai_privacy

    try:
        prepared = await ops_ai_privacy.prepare_llm_payload(
            operator_id=operator_id,
            question=text,
            context=context,
            history=history,
            image_data_urls=data_urls,
            ui_context=ui_context,
        )
    except Exception:
        # Без согласия — только техническое событие, без prompt/response.
        try:
            await ops_ai_audit.record_event(
                correlation_id=privacy_redaction.correlation_id("deny", operator_id),
                actor_type="operator",
                actor_id=operator_id,
                tenant_scope="ops",
                event_type="llm_denied_no_consent",
                consent_version=None,
                request_hash=privacy_redaction.content_hash("denied"),
                meta={"session_id": session_id, "has_images": bool(data_urls)},
            )
        except Exception as ae:
            logger.warning("audit deny write: %s", ae)
        raise

    answer, escalate = await ops_ai_llm.answer_chat(
        question=prepared["question"],
        context=prepared["context"],
        history=prepared["history"],
        image_data_urls=prepared["image_data_urls"],
    )
    try:
        summary = ops_ai_audit.summarize_response_for_audit(answer, escalate)
        await ops_ai_audit.record_event(
            correlation_id=prepared["correlation_id"],
            actor_type="operator",
            actor_id=operator_id,
            tenant_scope="ops",
            event_type="llm_chat",
            consent_version=prepared["consent_version"],
            request_hash=prepared["question_hash"],
            response_hash=summary.get("answer_hash"),
            redacted_request={
                "question": prepared["question"][:500],
                "ui": prepared.get("ui_safe") or {},
            },
            redacted_response=summary,
            meta={
                "session_id": session_id,
                "provider": settings.ops_ai_provider,
                "has_images": prepared["has_images"],
                "rag_hits": len(chunks),
                "escalate": bool(escalate.get("escalate")),
                "consent_version": prepared["consent_version"],
            },
        )
    except Exception as ae:
        logger.warning("audit write: %s", ae)
    if remembered:
        answer = (
            f"{answer}\n\n———\n💾 Записал в память проекта "
            f"(#{remembered.get('id')}: {remembered.get('title')})."
        )
    sources = [{"path": c.path, "title": c.title, "score": c.score} for c in chunks]
    if memory_block:
        sources.insert(0, {"path": "memory", "title": "Память проекта", "score": 97})
    if ui_context and (ui_context.get("path") or ui_context.get("order_id")):
        sources.insert(
            0,
            {
                "path": "ui/" + str(ui_context.get("path") or "screen"),
                "title": "Экран оператора",
                "score": 99,
            },
        )
    if attachments:
        sources.insert(0, {"path": "attachments", "title": f"{len(attachments)} фото", "score": 98})

    escalated_task: dict | None = None
    should_escalate = bool(escalate.get("escalate")) or ops_ai_llm.looks_like_bug_report(text)
    if should_escalate:
        req_parts = [text]
        if escalate.get("bug_summary"):
            req_parts.append(f"\n\nРазбор AI:\n{escalate['bug_summary']}")
        if ui_block:
            req_parts.append(f"\n\n{ui_block[:2500]}")
        try:
            escalated_task = await create_dev_task(
                operator_id=operator_id,
                request_text="\n".join(req_parts)[:8000],
                priority="high",
                source_session_id=session_id,
                source_message_id=int(user_msg["id"]),
                title=(escalate.get("title") or text.split("\n")[0])[:160],
                attachments=attachments,
                prefilled_cursor_prompt=escalate.get("cursor_prompt") or None,
                prefilled_summary=escalate.get("bug_summary") or None,
                ui_context=ui_context,
                skip_rate=True,
            )
            tid = escalated_task.get("id")
            answer = (
                f"{answer}\n\n———\nЗадача #{tid} отправлена в админку (/x8/ai-tasks). "
                "После Approve разработчик скопирует промпт в Cursor."
            )
        except Exception:
            logger.exception("auto escalate failed")

    async with pool.acquire() as conn:
        asst = await conn.fetchrow(
            """
            INSERT INTO ops_ai_chat_messages (session_id, role, content, sources_json)
            VALUES ($1, 'assistant', $2, $3::jsonb)
            RETURNING id, session_id, role, content, sources_json, attachments_json, created_at
            """,
            session_id,
            answer,
            json.dumps(sources, ensure_ascii=False),
        )
        if (sess.get("title") or "") in ("", "Чат"):
            await conn.execute(
                """
                UPDATE ops_ai_chat_sessions
                SET title = $2, updated_at = NOW()
                WHERE id = $1
                """,
                session_id,
                text[:80],
            )
        else:
            await conn.execute(
                "UPDATE ops_ai_chat_sessions SET updated_at = NOW() WHERE id = $1",
                session_id,
            )

    um = _row(user_msg)
    am = _row(asst)
    if isinstance(am.get("sources_json"), str):
        am["sources_json"] = sources
    if isinstance(um.get("attachments_json"), str):
        try:
            um["attachments_json"] = json.loads(um["attachments_json"])
        except json.JSONDecodeError:
            um["attachments_json"] = attachments
    out: dict[str, Any] = {"user": um, "assistant": am, "sources": sources}
    if escalated_task:
        out["escalated_task"] = {
            "id": escalated_task.get("id"),
            "title": escalated_task.get("title"),
            "status": escalated_task.get("status"),
        }
    return out


async def create_dev_task(
    *,
    operator_id: int,
    request_text: str,
    priority: str = "normal",
    source_session_id: int | None = None,
    source_message_id: int | None = None,
    title: str | None = None,
    attachments: list[dict] | None = None,
    prefilled_cursor_prompt: str | None = None,
    prefilled_summary: str | None = None,
    ui_context: dict | None = None,
    skip_rate: bool = False,
) -> dict:
    if not skip_rate and not _rate_ok(operator_id):
        raise PermissionError("Слишком много запросов, подождите минуту")
    text = (request_text or "").strip()
    if not text:
        raise ValueError("Пустой запрос")
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"
    atts = attachments or []

    # IDOR: source_session_id / source_message_id are NOT sufficient access —
    # must belong to the current actor (ownership).
    if source_session_id is not None:
        sess = await get_session(int(source_session_id), int(operator_id))
        if not sess:
            raise ValueError("source_session_id не принадлежит текущему пользователю")
        if source_message_id is not None:
            msgs = await list_messages(int(source_session_id), int(operator_id))
            if not any(int(m.get("id") or 0) == int(source_message_id) for m in msgs):
                raise ValueError("source_message_id не найден в сессии владельца")

    import ops_ai_privacy
    import privacy_redaction

    await ops_ai_privacy.require_llm_consent(operator_id)
    text = ops_ai_privacy.sanitize_question(text)
    if ui_context:
        try:
            from ops_ai_ui_context import validate_ui_context

            ui_context = validate_ui_context(ui_context)
        except Exception as e:
            raise ValueError(f"ui_context: {e}") from e

    # Explicit: never auto-run Cursor / git from task creation.
    _ = refuse_auto_cursor_and_git()

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ops_ai_dev_tasks (
                operator_id, source_session_id, source_message_id,
                title, request_text, priority, status, attachments_json
            ) VALUES ($1, $2, $3, $4, $5, $6, 'drafting', $7::jsonb)
            RETURNING *
            """,
            operator_id,
            source_session_id,
            source_message_id,
            (title or text.split("\n")[0])[:160],
            text,
            priority,
            json.dumps(atts, ensure_ascii=False),
        )
    task_id = int(row["id"])

    try:
        import ops_ai_surface

        surface = ops_ai_surface.infer_task_surface(text, ui_context)
        surface_block = ops_ai_surface.surface_prompt_block(surface)
        chunks = ops_ai_rag.retrieve(
            ops_ai_surface.rag_query_for_surface(text, surface), limit=10
        )
        rag_ctx = privacy_redaction.redact_text(
            ops_ai_rag.format_context(chunks), keep_short_ids=True
        )
        try:
            import ops_ai_live_context

            if surface.get("include_live_rates"):
                live = await ops_ai_live_context.build_live_snapshot()
            else:
                live = ops_ai_live_context.live_rates_not_a_target_note()
        except Exception as e:
            logger.warning("live context (task): %s", e)
            live = ""
        ui_block = ""
        try:
            import ops_ai_ui_context

            ui_block = await ops_ai_ui_context.build_ui_context_block(ui_context)
        except Exception as e:
            logger.warning("ui context (task): %s", e)
        # SURFACE + inbox-aware UI first — иначе LIVE RATES уводят на /exchange.
        context = "\n\n".join(
            p for p in (surface_block, ui_block, live, f"# RAG\n{rag_ctx}") if p
        ).strip()
        prefilled: dict = {}
        if prefilled_cursor_prompt and len(prefilled_cursor_prompt.strip()) > 40:
            prefilled = {
                "title": (title or text.split("\n")[0])[:200],
                "summary": prefilled_summary or "Баг от оператора (vision/чат).",
                "file_list": [],
                "freeze_hit": ops_ai_rag.detect_freeze_hit(text),
                "risks": "",
                "smoke_plan": "Воспроизвести по скрину/описанию; проверить после фикса.",
                "cursor_prompt": ops_ai_llm.sanitize_cursor_prompt(prefilled_cursor_prompt.strip()),
            }
        try:
            import ops_ai_agents

            draft = await ops_ai_agents.run_pipeline(
                request_text=text,
                base_context=context,
                prefilled=prefilled or None,
                ui_context=ui_context,
            )
        except Exception:
            logger.exception("multi-agent failed task=%s, fallback draft", task_id)
            if prefilled:
                draft = prefilled
                draft["agents"] = {"enabled": False, "error": "pipeline_failed"}
            else:
                draft = await ops_ai_llm.draft_dev_task(request_text=text, context=context)
                draft["agents"] = {"enabled": False, "error": "pipeline_failed"}
        freeze = bool(draft.get("freeze_hit")) or ops_ai_rag.detect_freeze_hit(
            text, draft.get("file_list") or []
        )
        agents_payload = draft.get("agents") or {}
        draft_prompt = ops_ai_llm.sanitize_cursor_prompt(
            str(draft.get("cursor_prompt") or "")
        )
        if not str(draft_prompt).lstrip().startswith("HUMAN_SAID"):
            import ops_ai_grill as _grill

            draft_prompt = _grill.compose_cursor_prompt(
                text, _grill.parse_user_request(text), llm_prompt=draft_prompt
            )
        draft["cursor_prompt"] = draft_prompt
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE ops_ai_dev_tasks SET
                    title = $2,
                    summary = $3,
                    file_list_json = $4::jsonb,
                    freeze_hit = $5,
                    cursor_prompt = $6,
                    smoke_plan = $7,
                    risks = $8,
                    agents_json = $9::jsonb,
                    status = 'review',
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                task_id,
                str(draft.get("title") or row["title"])[:200],
                draft.get("summary"),
                json.dumps(draft.get("file_list") or [], ensure_ascii=False),
                freeze,
                draft.get("cursor_prompt"),
                draft.get("smoke_plan"),
                draft.get("risks"),
                json.dumps(agents_payload, ensure_ascii=False),
            )
    except Exception:
        logger.exception("ops_ai draft failed task=%s", task_id)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE ops_ai_dev_tasks SET
                    status = 'review',
                    summary = COALESCE(summary, 'Черновик не сгенерирован — заполните вручную'),
                    risks = COALESCE(risks, 'Ошибка генерации LLM'),
                    cursor_prompt = COALESCE(
                        cursor_prompt,
                        'Задача от оператора:\n' || request_text
                    ),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                task_id,
            )

    task = _normalize_task(_row(row))
    await _notify_devs(task)
    return task


def _normalize_task(d: dict) -> dict:
    fl = d.get("file_list_json")
    if isinstance(fl, str):
        try:
            d["file_list"] = json.loads(fl)
        except json.JSONDecodeError:
            d["file_list"] = []
    elif fl is None:
        d["file_list"] = []
    else:
        d["file_list"] = fl
    at = d.get("attachments_json")
    if isinstance(at, str):
        try:
            d["attachments"] = json.loads(at)
        except json.JSONDecodeError:
            d["attachments"] = []
    elif at is None:
        d["attachments"] = []
    else:
        d["attachments"] = at
    # не светим абсолютные пути наружу — только name/rel/content_type/size
    safe = []
    for i, a in enumerate(d.get("attachments") or []):
        if not isinstance(a, dict):
            continue
        safe.append(
            {
                "index": i,
                "name": a.get("name"),
                "rel": a.get("rel"),
                "content_type": a.get("content_type"),
                "size": a.get("size"),
            }
        )
    d["attachments"] = safe
    ag = d.get("agents_json")
    if isinstance(ag, str):
        try:
            d["agents"] = json.loads(ag)
        except json.JSONDecodeError:
            d["agents"] = {}
    elif ag is None:
        d["agents"] = {}
    else:
        d["agents"] = ag
    try:
        import ops_ai_selfcheck as _sc

        d["agents"] = _sc.normalize_agents(d.get("agents") or {})
    except Exception:
        logger.debug("ignored non-fatal error", exc_info=True)
    return d


async def get_task_attachment_file(task_id: int, index: int):
    """Returns (path, media_type, filename)."""
    from pathlib import Path

    import ops_ai_attachments

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT attachments_json FROM ops_ai_dev_tasks WHERE id = $1",
            task_id,
        )
    if not row:
        raise LookupError("Задача не найдена")
    raw = row["attachments_json"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list) or index < 0 or index >= len(raw):
        raise LookupError("Вложение не найдено")
    meta = raw[index]
    path, ctype = ops_ai_attachments.read_attachment(meta)
    return path, ctype, Path(str(meta.get("name") or path.name)).name


async def list_tasks(
    *,
    status: str | None = None,
    operator_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    pool = await get_pool()
    clauses = ["TRUE"]
    args: list[Any] = []
    if status and status != "all":
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if operator_id is not None:
        args.append(operator_id)
        clauses.append(f"operator_id = ${len(args)}")
    where = " AND ".join(clauses)
    lim_i = len(args) + 1
    off_i = len(args) + 2
    query_args = list(args) + [limit, offset]
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT * FROM ops_ai_dev_tasks WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ${lim_i} OFFSET ${off_i}""",  # nosec B608
            *query_args,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM ops_ai_dev_tasks WHERE {where}",  # nosec B608
            *args,
        )
    return {
        "tasks": [_normalize_task(_row(r)) for r in rows],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
    }


async def get_task(task_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ops_ai_dev_tasks WHERE id = $1", task_id)
    return _normalize_task(_row(row)) if row else None


async def review_task(
    task_id: int,
    *,
    action: str,
    admin_id: int | None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if not admin_id or int(admin_id) <= 0:
        raise ValueError("Требуется повторная авторизация admin")
    # task id alone is not sufficient — caller must be authenticated admin (checked above)
    task = await get_task(task_id)
    if not task:
        raise LookupError("Задача не найдена")
    if task["status"] not in ("review", "drafting", "new"):
        raise ValueError(f"Нельзя {action} в статусе {task['status']}")

    idem = (idempotency_key or "").strip()
    op_id = int(task.get("operator_id") or 0)
    scope = f"admin:{int(admin_id)}:op:{op_id}:task:{int(task_id)}:action:{(action or '').strip().lower()}"
    cache_key = _priv_idem_scope_key(
        kind="review",
        actor_kind="admin",
        actor_id=int(admin_id),
        task_id=int(task_id),
        action=action,
        client_key=idem,
    )
    if cache_key:
        cached = _priv_idem_get(cache_key, scope=scope)
        if cached:
            return cached

    # Never execute cursor_prompt / git / subprocess on approve.
    _ = refuse_auto_cursor_and_git()

    pool = await get_pool()
    if action == "approve":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE ops_ai_dev_tasks SET
                    status = 'approved',
                    reviewed_by_admin_id = $2,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                task_id,
                admin_id,
            )
    elif action == "reject":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE ops_ai_dev_tasks SET
                    status = 'rejected',
                    reject_reason = $2,
                    reviewed_by_admin_id = $3,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                task_id,
                (reason or "")[:500],
                admin_id,
            )
    else:
        raise ValueError("action must be approve|reject")
    out = _normalize_task(_row(row))
    if cache_key:
        _priv_idem_put(cache_key, out, scope=scope)
    return out


async def mark_task_done(
    task_id: int,
    *,
    note: str | None = None,
    admin_id: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    if not admin_id or int(admin_id) <= 0:
        raise ValueError("Требуется повторная авторизация admin")
    task = await get_task(task_id)
    if not task:
        raise LookupError("Задача не найдена")
    if task["status"] not in ("approved", "review"):
        raise ValueError("Done только для approved/review")

    idem = (idempotency_key or "").strip()
    op_id = int(task.get("operator_id") or 0)
    scope = f"admin:{int(admin_id)}:op:{op_id}:task:{int(task_id)}:action:done"
    cache_key = _priv_idem_scope_key(
        kind="done",
        actor_kind="admin",
        actor_id=int(admin_id),
        task_id=int(task_id),
        action="done",
        client_key=idem,
    )
    if cache_key:
        cached = _priv_idem_get(cache_key, scope=scope)
        if cached:
            return cached

    _ = refuse_auto_cursor_and_git()

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE ops_ai_dev_tasks SET
                status = 'done',
                done_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            task_id,
        )
        body = note or task.get("summary") or task.get("request_text") or ""
        await conn.execute(
            """
            INSERT INTO ops_ai_learning_notes (kind, ref_task_id, title, body)
            VALUES ('task_done', $1, $2, $3)
            """,
            task_id,
            f"Done #{task_id}: {task.get('title')}",
            body[:4000],
        )
    await append_learning_markdown(task_id, title=str(task.get("title")), body=body[:2000])
    try:
        import ops_ai_memory

        await ops_ai_memory.remember_task_done(_normalize_task(_row(row)), note=note)
    except Exception as e:
        logger.warning("memory from task done: %s", e)
    ops_ai_rag.rebuild_index(force=True)
    done = _normalize_task(_row(row))
    await _notify_assigner_done(done, note=note)
    if cache_key:
        _priv_idem_put(cache_key, done, scope=scope)
    return done


async def notify_task_done_assigner(
    task_id: int, *, note: str | None = None, force: bool = False
) -> dict:
    """Повторно/бэкап: уведомить постановщика о уже done-задаче (антидубль по done_notified_at)."""
    task = await get_task(task_id)
    if not task:
        raise LookupError("Задача не найдена")
    if task.get("status") != "done":
        raise ValueError("Notify-done только для status=done")
    ok = await _notify_assigner_done(task, note=note, force=force)
    fresh = await get_task(task_id) or task
    return {"task": fresh, "notified": ok}


async def backfill_done_notifications(
    *, limit: int = 100, also_mark_approved: bool = True, admin_id: int | None = None
) -> dict:
    """
    Одноразовый бэкап:
    - approved → mark_task_done (шлёт notify); review НЕ трогаем
    - done без done_notified_at → только notify
    """
    if not admin_id or int(admin_id) <= 0:
        raise ValueError("Требуется повторная авторизация admin")
    pool = await get_pool()
    marked = 0
    notified = 0
    skipped = 0
    errors: list[str] = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, status, done_notified_at
            FROM ops_ai_dev_tasks
            WHERE (
                status = 'done' AND done_notified_at IS NULL
            ) OR (
                status = 'approved' AND $1::boolean
            )
            ORDER BY id ASC
            LIMIT $2
            """,
            also_mark_approved,
            limit,
        )
    for r in rows:
        tid = int(r["id"])
        status = str(r["status"])
        try:
            if status == "approved":
                await mark_task_done(
                    tid,
                    note="Бэкап closeout: задача закрыта, постановщик уведомлён.",
                    admin_id=int(admin_id),
                )
                marked += 1
                notified += 1
            elif status == "done":
                res = await notify_task_done_assigner(
                    tid,
                    note="Бэкап: задача уже была выполнена.",
                )
                if res.get("notified"):
                    notified += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"#{tid}: {e}")
            logger.warning("backfill done notify #%s: %s", tid, e)
    return {
        "marked_done": marked,
        "notified": notified,
        "skipped": skipped,
        "errors": errors[:20],
        "processed": len(rows),
    }


async def mark_chat_useful(
    *,
    operator_id: int,
    session_id: int,
    message_id: int,
    note: str | None = None,
) -> dict:
    sess = await get_session(session_id, operator_id)
    if not sess:
        raise LookupError("Чат не найден")
    pool = await get_pool()
    async with pool.acquire() as conn:
        msg = await conn.fetchrow(
            """
            SELECT id, content FROM ops_ai_chat_messages
            WHERE id = $1 AND session_id = $2 AND role = 'assistant'
            """,
            message_id,
            session_id,
        )
        if not msg:
            raise LookupError("Сообщение не найдено")
        title = f"Useful chat #{session_id}/{message_id}"
        body = (note or msg["content"])[:4000]
        row = await conn.fetchrow(
            """
            INSERT INTO ops_ai_learning_notes (kind, title, body)
            VALUES ('chat_useful', $1, $2)
            RETURNING *
            """,
            title,
            body,
        )
    await append_learning_markdown(None, title=title, body=body[:2000])
    try:
        import ops_ai_memory

        await ops_ai_memory.add_memory(
            kind="person",
            title=title[:200],
            body=body[:3500],
            person_key=ops_ai_memory.person_key_for_operator(operator_id),
            person_label=f"op#{operator_id}",
            source="chat_useful",
            source_ref=f"msg:{message_id}",
            created_by_operator_id=operator_id,
            importance=2,
        )
    except Exception as e:
        logger.warning("memory from useful: %s", e)
    ops_ai_rag.rebuild_index(force=True)
    return _row(row)


async def append_learning_markdown(
    task_id: int | None, *, title: str, body: str
) -> None:
    """Пишет в docs/ops_ai_learning.md если путь доступен (learning-loop)."""
    from pathlib import Path
    from datetime import datetime, timezone

    roots = ops_ai_rag._knowledge_roots()
    if not roots:
        return
    target = roots[0] / "ops_ai_learning.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        header = ""
        if not target.exists() or target.stat().st_size == 0:
            header = (
                "# Ops AI learning log\n\n"
                "Автозаметки после done / «полезный ответ». Индексируется RAG.\n"
            )
        block = (
            header
            + f"\n## {stamp}"
            + (f" · task #{task_id}" if task_id else "")
            + f"\n\n**{title}**\n\n{body}\n\n---\n"
        )
        with target.open("a", encoding="utf-8") as f:
            f.write(block)
    except OSError as e:
        logger.warning("learning markdown append failed: %s", e)


async def _notify_devs(task: dict) -> None:
    site = (settings.public_site_url or "").rstrip("/")
    tid = task.get("id")
    link = f"{site}/x8/ai-tasks?id={tid}" if site else f"task #{tid}"
    freeze = "⚠️ FREEZE" if task.get("freeze_hit") else "ok"
    text = (
        f"<b>Ops AI · задача #{tid}</b> ({escape(str(task.get('priority')))})\n"
        f"<b>{escape(str(task.get('title') or ''))}</b>\n"
        f"Freeze: {freeze}\n"
        f"{escape((task.get('summary') or task.get('request_text') or '')[:800])}\n\n"
        f"<a href=\"{escape(link)}\">Открыть в админке</a>"
    )
    markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "url": f"{link}&action=approve"},
                {"text": "❌ Reject", "url": f"{link}&action=reject"},
            ]
        ]
    }
    chat_id = int(settings.ops_ai_dev_telegram_chat_id or 0) or None
    if not chat_id:
        # По умолчанию — группа «Админ отчеты», не операторская
        chat_id = int(settings.reports_telegram_group_id() or 0) or None
    if not chat_id:
        logger.warning("ops_ai notify: нет TELEGRAM_REPORTS_GROUP_ID / OPS_AI_DEV_TELEGRAM_CHAT_ID")
        return
    try:
        mid = await send_admin_message(text, chat_id=chat_id, reply_markup=markup)
        if mid:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ops_ai_dev_tasks SET telegram_message_id = $2 WHERE id = $1",
                    tid,
                    mid,
                )
    except Exception:
        logger.exception("ops_ai telegram notify failed")


def format_done_notify_html(task: dict, *, note: str | None = None) -> str:
    """HTML для лички постановщику (и для тестов)."""
    site = (settings.public_site_url or "").rstrip("/")
    tid = task.get("id")
    link = f"{site}/x8/ai-tasks?id={tid}" if site else ""
    title = escape(str(task.get("title") or f"Задача #{tid}"))
    body = (note or task.get("summary") or task.get("request_text") or "").strip()
    # Буллеты из note: строки с "- " / "• " или режем по предложениям
    bullets: list[str] = []
    for line in body.splitlines():
        s = line.strip().lstrip("•").strip()
        if s.startswith("- "):
            s = s[2:].strip()
        if s:
            bullets.append(s)
    if not bullets and body:
        bullets = [body[:500]]
    bullets = bullets[:6]
    lines = [
        f"<b>Ops AI · готово #{tid}</b>",
        f"<b>{title}</b>",
        "",
        "<b>Что сделано</b>",
    ]
    for b in bullets:
        lines.append(f"• {escape(b[:400])}")
    if link:
        lines.append("")
        lines.append(f'<a href="{escape(link)}">Открыть в админке</a>')
    return "\n".join(lines)


async def _notify_assigner_done(
    task: dict, *, note: str | None = None, force: bool = False
) -> bool:
    """Личное TG-уведомление постановщику. Антидубль: done_notified_at."""
    tid = int(task.get("id") or 0)
    if not tid:
        return False
    if task.get("done_notified_at") and not force:
        return False

    op_id = task.get("operator_id")
    try:
        op_id_int = int(op_id) if op_id is not None else 0
    except (TypeError, ValueError):
        op_id_int = 0

    # Админские сессии используют отрицательный actor id — у operator_accounts их нет
    if op_id_int <= 0:
        logger.info("ops_ai done notify: skip task #%s (no positive operator_id)", tid)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ops_ai_dev_tasks
                SET done_notified_at = COALESCE(done_notified_at, NOW())
                WHERE id = $1
                """,
                tid,
            )
        return False

    pool = await get_pool()
    async with pool.acquire() as conn:
        if not force:
            claimed = await conn.fetchrow(
                """
                UPDATE ops_ai_dev_tasks
                SET done_notified_at = NOW()
                WHERE id = $1 AND done_notified_at IS NULL
                RETURNING id
                """,
                tid,
            )
            if not claimed:
                return False
        else:
            await conn.execute(
                "UPDATE ops_ai_dev_tasks SET done_notified_at = NOW() WHERE id = $1",
                tid,
            )
        tg = await conn.fetchval(
            """
            SELECT telegram_user_id FROM operator_accounts
            WHERE id = $1 AND telegram_user_id IS NOT NULL
            """,
            op_id_int,
        )

    if not tg:
        logger.info(
            "ops_ai done notify: op#%s has no telegram_user_id (task #%s) — fallback reports",
            op_id_int,
            tid,
        )
        # Fallback: группа отчётов, чтобы closeout не терялся
        reports = int(settings.ops_ai_dev_telegram_chat_id or 0) or None
        if not reports:
            reports = int(settings.reports_telegram_group_id() or 0) or None
        if not reports:
            return False
        op_label = f"op#{op_id_int}"
        async with pool.acquire() as conn:
            uname = await conn.fetchval(
                "SELECT COALESCE(display_name, username) FROM operator_accounts WHERE id = $1",
                op_id_int,
            )
            if uname:
                op_label = str(uname)
        text = (
            format_done_notify_html(task, note=note)
            + f"\n\n<i>Постановщик: {escape(op_label)} (TG не привязан)</i>"
        )
        try:
            mid = await send_admin_message(text, chat_id=int(reports))
            return bool(mid)
        except Exception:
            logger.exception("ops_ai done notify fallback failed task #%s", tid)
            return False

    text = format_done_notify_html(task, note=note)
    try:
        mid = await send_admin_message(text, chat_id=int(tg))
        if not mid:
            logger.warning("ops_ai done notify: send failed task #%s op#%s", tid, op_id_int)
            return False
        return True
    except Exception:
        logger.exception("ops_ai done notify failed task #%s", tid)
        return False


async def pending_review_count() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM ops_ai_dev_tasks WHERE status = 'review'"
            )
            or 0
        )

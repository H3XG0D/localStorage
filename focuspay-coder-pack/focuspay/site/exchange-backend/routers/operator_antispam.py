"""CRUD фраз антиспама для панели оператора."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_operator
from db import get_pool
from group_spam_phrases import BUILTIN_PHRASE_LABELS, validate_operator_phrase
from permissions import PERM_ANTISPAM_PHRASES, enrich_operator_permissions, require_permission

router = APIRouter()


class PhraseBody(BaseModel):
    phrase: str = Field(..., min_length=1, max_length=200)


def _row(r) -> dict:
    return {
        "id": int(r["id"]),
        "phrase": r["phrase"],
        "normalized": r["normalized"],
        "created_by_operator_id": r["created_by_operator_id"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.get("/antispam/phrases")
async def list_phrases(operator=Depends(get_current_operator)):
    enriched = await enrich_operator_permissions(operator)
    require_permission(enriched, PERM_ANTISPAM_PHRASES)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, phrase, normalized, created_by_operator_id, created_at
            FROM group_spam_phrases
            ORDER BY created_at DESC, id DESC
            """
        )
    return {
        "items": [_row(r) for r in rows],
        "builtin": list(BUILTIN_PHRASE_LABELS),
    }


@router.post("/antispam/phrases")
async def create_phrase(body: PhraseBody, operator=Depends(get_current_operator)):
    enriched = await enrich_operator_permissions(operator)
    require_permission(enriched, PERM_ANTISPAM_PHRASES)
    try:
        display, normalized = validate_operator_phrase(body.phrase)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO group_spam_phrases (phrase, normalized, created_by_operator_id)
                VALUES ($1, $2, $3)
                RETURNING id, phrase, normalized, created_by_operator_id, created_at
                """,
                display,
                normalized,
                int(operator["id"]),
            )
        except Exception as exc:
            if type(exc).__name__ == "UniqueViolationError":
                raise HTTPException(status_code=409, detail="Такая фраза уже есть") from exc
            raise
    return _row(row)


@router.delete("/antispam/phrases/{phrase_id}")
async def delete_phrase(phrase_id: int, operator=Depends(get_current_operator)):
    enriched = await enrich_operator_permissions(operator)
    require_permission(enriched, PERM_ANTISPAM_PHRASES)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM group_spam_phrases WHERE id = $1 RETURNING id",
            int(phrase_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Фраза не найдена")
    return {"ok": True, "id": int(row["id"])}

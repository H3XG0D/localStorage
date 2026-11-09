"""Signed deploy webhook — no secrets in URL."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deployment_events import upsert_deploy_event, verify_deploy_signature

router = APIRouter()


class DeployEventBody(BaseModel):
    idempotency_key: str = Field(..., min_length=4, max_length=200)
    environment: str = "production"
    status: str = "pending"
    title: str = "Deployment"
    sectors: list[str] = Field(default_factory=list)
    technical_summary: str = ""
    user_impact: str = ""
    plain_explanation: str = ""
    commit_sha: str | None = None
    build_id: str | None = None
    actor: str | None = None
    logs_url: str | None = None
    source: str = "webhook"
    ops_ai_task_id: int | None = None
    extra: dict | None = None


@router.post("/deploy/events")
async def ingest_deploy_event(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-focuspay-deploy-signature") or request.headers.get(
        "X-FocusPay-Deploy-Signature"
    )
    if not verify_deploy_signature(raw, sig):
        raise HTTPException(status_code=401, detail="Invalid deploy signature")
    try:
        import json

        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    # Validate via pydantic
    try:
        body = DeployEventBody.model_validate(payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    try:
        row = await upsert_deploy_event(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "event": row}

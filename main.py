import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request


app = FastAPI(title="Webhook Hub API", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "fast-api-core"}


def _project_token(project: str) -> str | None:
    key = f"WEBHOOK_TOKEN_{project.upper().replace('-', '_')}"
    value = os.getenv(key)
    return value.strip() if value else None


async def _handle_project_webhook(project: str, request: Request) -> dict:
    expected_token = _project_token(project)
    if not expected_token:
        expected_env = f"WEBHOOK_TOKEN_{project.upper().replace('-', '_')}"
        raise HTTPException(
            status_code=500,
            detail=f"Token not configured for project '{project}'. Expected env: {expected_env}",
        )

    sent_token = request.query_params.get("token")
    if sent_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()
    event = payload.get("event")
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id")

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"project={project} event={event} conversation_id={conversation_id}"
    )
    return {"ok": True}


@app.post("/webhooks/{project}")
async def project_webhook(project: str, request: Request) -> dict:
    return await _handle_project_webhook(project, request)


@app.post("/chatwoot-webhook")
async def chatwoot_webhook(request: Request) -> dict:
    # Backward compatibility for existing Chatwoot URL.
    return await _handle_project_webhook("chatwoot", request)


@app.post("/novauniao-marketing-webhook")
async def novauniao_marketing_webhook(request: Request) -> dict:
    # Convenience alias for this project.
    return await _handle_project_webhook("novauniao_marketing", request)

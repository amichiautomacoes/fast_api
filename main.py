import os
import secrets
from datetime import datetime, timezone
from typing import Any

from celery import Celery
from fastapi import FastAPI, HTTPException, Request


app = FastAPI(title="Webhook Hub API", version="1.0.0")


def _get_env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def _new_trace_id() -> str:
    return f"wf-{secrets.token_hex(8)}"


def _extract_conversation_id(payload: dict[str, Any] | list[dict[str, Any]]) -> int | None:
    raw_item: dict[str, Any]
    if isinstance(payload, list):
        raw_item = payload[0] if payload else {}
    else:
        raw_item = payload
    body = raw_item.get("body", raw_item) if isinstance(raw_item, dict) else {}
    conversation = body.get("conversation") if isinstance(body, dict) else {}
    if isinstance(conversation, dict):
        conversation_id = conversation.get("id")
    else:
        conversation_id = body.get("conversation_id")
    try:
        return int(conversation_id)
    except (TypeError, ValueError):
        return None


def _celery_broker_url() -> str:
    # Dedicated broker for garcom can be set explicitly; fallback to shared REDIS_URL.
    broker = _get_env("GARCOM_CELERY_BROKER_URL")
    if broker:
        return broker
    return _get_env("REDIS_URL")


def _celery_backend_url() -> str:
    backend = _get_env("GARCOM_CELERY_RESULT_BACKEND")
    if backend:
        return backend
    return _celery_broker_url()


def _enqueue_garcom_task(
    *,
    payload: dict[str, Any] | list[dict[str, Any]],
    webhook_id: str | None,
    request_trace_id: str | None,
) -> dict[str, Any]:
    broker_url = _celery_broker_url()
    if not broker_url:
        raise HTTPException(status_code=500, detail="GARCOM_CELERY_BROKER_URL/REDIS_URL not configured")

    trace_id = str(request_trace_id or "").strip() or _new_trace_id()
    conversation_id = _extract_conversation_id(payload)

    celery_app = Celery(
        "webhook_hub",
        broker=broker_url,
        backend=_celery_backend_url(),
    )
    celery_app.send_task(
        "runner.tasks.process_webhook_payload_task",
        kwargs={
            "payload": payload,
            "trace_id": trace_id,
            "webhook_id": webhook_id,
            "conversation_id": conversation_id,
        },
    )
    return {
        "status": "queued",
        "trace_id": trace_id,
        "reason": None,
        "data": {"queued": True},
        "webhook_id": webhook_id,
        "project": "garcom_digital",
    }


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "fast-api-core"}


def _project_token(project: str) -> str | None:
    key = f"WEBHOOK_TOKEN_{project.upper().replace('-', '_')}"
    return os.getenv(key)


async def _handle_project_webhook(project: str, request: Request) -> dict:
    expected_token = _project_token(project)
    if project == "novauniao_marketing" and not expected_token:
        expected_token = os.getenv("WEBHOOK_TOKEN_CHATWOOT_NOVAUNIAO")
    if project == "chatwoot" and not expected_token:
        expected_token = os.getenv("CHATWOOT_WEBHOOK_TOKEN")

    sent_token = request.query_params.get("token")
    if expected_token and sent_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()
    request_trace_id = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
    if project in {"garcom_digital", "garcom-digital", "garcom"}:
        return _enqueue_garcom_task(
            payload=payload,
            webhook_id=request.query_params.get("webhook_id"),
            request_trace_id=request_trace_id,
        )

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


@app.post("/garcom-digital-webhook")
async def garcom_digital_webhook(request: Request) -> dict:
    # Convenience alias for this project.
    return await _handle_project_webhook("garcom_digital", request)

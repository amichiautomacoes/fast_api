import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import redis
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_env_name(project: str) -> str:
    return f"WEBHOOK_TOKEN_{project.upper().replace('-', '_')}"


def _project_token(project: str) -> str | None:
    value = os.getenv(_project_env_name(project))
    return value.strip() if value else None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _event_maxlen() -> int:
    raw = os.getenv("WEBHOOK_EVENTS_MAXLEN", "1000").strip()
    try:
        parsed = int(raw)
        return max(parsed, 1)
    except ValueError:
        return 1000


class MessageCreate(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)
    to: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageReplace(BaseModel):
    project: str = Field(..., min_length=1, max_length=120)
    to: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1, max_length=4000)
    status: str = Field(default="pending", min_length=1, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessagePatch(BaseModel):
    to: str | None = Field(default=None, min_length=1, max_length=120)
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    metadata: dict[str, Any] | None = None


app = FastAPI(title="Webhook Hub API", version="2.0.0")


@app.on_event("startup")
def _startup() -> None:
    redis_url = os.getenv("REDIS_URL", "").strip()
    app.state.redis = None
    if not redis_url:
        return
    client = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    client.ping()
    app.state.redis = client


@app.get("/")
async def root() -> dict[str, Any]:
    return {"ok": True, "service": "webhook-hub", "version": app.version}


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    redis_ready = bool(getattr(request.app.state, "redis", None))
    return {"ok": True, "service": "webhook-hub", "redis_ready": redis_ready}


def _require_redis(request: Request) -> redis.Redis:
    client = getattr(request.app.state, "redis", None)
    if not client:
        raise HTTPException(status_code=503, detail="REDIS_URL not configured or Redis unavailable")
    return client


def _message_key(message_id: str) -> str:
    return f"wh:message:{message_id}"


def _messages_index_key() -> str:
    return "wh:messages:index"


def _read_message(client: redis.Redis, message_id: str) -> dict[str, Any]:
    raw = client.get(_message_key(message_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Message not found")
    return json.loads(raw)


def _write_message(client: redis.Redis, doc: dict[str, Any], *, index_score: float | None = None) -> None:
    message_id = str(doc["id"])
    key = _message_key(message_id)
    if index_score is None:
        index_score = datetime.now(timezone.utc).timestamp()
    payload = json.dumps(doc, ensure_ascii=False)
    pipe = client.pipeline(transaction=True)
    pipe.set(key, payload)
    pipe.zadd(_messages_index_key(), {message_id: index_score})
    pipe.execute()


@app.post("/webhooks/{project}")
async def project_webhook(project: str, request: Request) -> dict[str, Any]:
    expected_token = _project_token(project)
    if not expected_token:
        raise HTTPException(
            status_code=500,
            detail=f"Token not configured for project '{project}'. Expected env: {_project_env_name(project)}",
        )

    sent_token = request.query_params.get("token")
    if sent_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()
    event = payload.get("event")
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id")
    webhook_id = _new_id("whk")

    print(
        f"[{_now_iso()}] project={project} webhook_id={webhook_id} event={event} conversation_id={conversation_id}"
    )

    client = getattr(request.app.state, "redis", None)
    if client:
        key = f"wh:webhooks:{project}"
        event_doc = {
            "id": webhook_id,
            "project": project,
            "event": event,
            "conversation_id": conversation_id,
            "received_at": _now_iso(),
            "payload": payload,
        }
        pipe = client.pipeline(transaction=True)
        pipe.lpush(key, json.dumps(event_doc, ensure_ascii=False))
        pipe.ltrim(key, 0, _event_maxlen() - 1)
        pipe.execute()

    return {"ok": True, "webhook_id": webhook_id, "project": project}


@app.post("/messages")
async def create_message(body: MessageCreate, request: Request) -> dict[str, Any]:
    client = _require_redis(request)
    now = _now_iso()
    doc: dict[str, Any] = {
        "id": _new_id("msg"),
        "project": body.project,
        "to": body.to,
        "text": body.text,
        "status": "pending",
        "metadata": body.metadata,
        "created_at": now,
        "updated_at": now,
    }
    _write_message(client, doc)
    return doc


@app.get("/messages")
async def list_messages(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    client = _require_redis(request)
    message_ids = client.zrevrange(_messages_index_key(), offset, offset + limit - 1)
    items = [_read_message(client, message_id) for message_id in message_ids]
    return {"items": items, "count": len(items), "limit": limit, "offset": offset}


@app.get("/messages/{message_id}")
async def get_message(message_id: str, request: Request) -> dict[str, Any]:
    client = _require_redis(request)
    return _read_message(client, message_id)


@app.put("/messages/{message_id}")
async def replace_message(message_id: str, body: MessageReplace, request: Request) -> dict[str, Any]:
    client = _require_redis(request)
    current = _read_message(client, message_id)
    doc: dict[str, Any] = {
        "id": message_id,
        "project": body.project,
        "to": body.to,
        "text": body.text,
        "status": body.status,
        "metadata": body.metadata,
        "created_at": current["created_at"],
        "updated_at": _now_iso(),
    }
    score = client.zscore(_messages_index_key(), message_id)
    _write_message(client, doc, index_score=float(score) if score is not None else None)
    return doc


@app.patch("/messages/{message_id}")
async def patch_message(message_id: str, body: MessagePatch, request: Request) -> dict[str, Any]:
    client = _require_redis(request)
    doc = _read_message(client, message_id)
    patch_data = body.model_dump(exclude_none=True)
    for key, value in patch_data.items():
        doc[key] = value
    doc["updated_at"] = _now_iso()
    score = client.zscore(_messages_index_key(), message_id)
    _write_message(client, doc, index_score=float(score) if score is not None else None)
    return doc


@app.delete("/messages/{message_id}")
async def delete_message(message_id: str, request: Request) -> dict[str, Any]:
    client = _require_redis(request)
    exists = client.exists(_message_key(message_id))
    if not exists:
        raise HTTPException(status_code=404, detail="Message not found")
    pipe = client.pipeline(transaction=True)
    pipe.delete(_message_key(message_id))
    pipe.zrem(_messages_index_key(), message_id)
    pipe.execute()
    return {"ok": True, "deleted_id": message_id}


@app.post("/chatwoot-webhook")
async def chatwoot_webhook(request: Request) -> dict[str, Any]:
    return await project_webhook("chatwoot", request)


@app.post("/novauniao-marketing-webhook")
async def novauniao_marketing_webhook(request: Request) -> dict[str, Any]:
    return await project_webhook("novauniao_marketing", request)

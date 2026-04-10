import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import redis
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

GARCOM_PROJECT = "garcom_digital"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _event_maxlen() -> int:
    raw = os.getenv("WEBHOOK_EVENTS_MAXLEN", "1000").strip()
    try:
        parsed = int(raw)
        return max(parsed, 1)
    except ValueError:
        return 1000


def _forward_webhook_url() -> str:
    value = os.getenv("FORWARD_WEBHOOK_URL_GARCOM_DIGITAL")
    return value.strip() if value else ""


def _forward_timeout_seconds() -> float:
    raw = os.getenv("FORWARD_WEBHOOK_TIMEOUT_SECONDS", "10").strip()
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return 10.0


def _chatwoot_base_url() -> str:
    return (os.getenv("CHATWOOT_BASE_URL") or "").rstrip("/")


def _chatwoot_account_id() -> str:
    return (os.getenv("CHATWOOT_ACCOUNT_ID") or "").strip()


def _chatwoot_api_access_token() -> str:
    return (os.getenv("CHATWOOT_API_ACCESS_TOKEN") or "").strip()


def _forward_webhook_payload(payload: dict[str, Any], webhook_id: str) -> dict[str, Any]:
    forward_url = _forward_webhook_url()
    if not forward_url:
        return {"attempted": False, "ok": False, "reason": "forward_not_configured", "status_code": None}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        forward_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Source-Webhook-Id": webhook_id,
        },
        method="POST",
    )
    timeout = _forward_timeout_seconds()
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
            return {
                "attempted": True,
                "ok": 200 <= int(resp.status) < 300,
                "status_code": int(resp.status),
                "response_body": response_body[:1000],
                "reason": None,
            }
    except urlerror.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "attempted": True,
            "ok": False,
            "status_code": int(exc.code),
            "response_body": body_text[:1000],
            "reason": "forward_http_error",
        }
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "status_code": None,
            "response_body": "",
            "reason": f"forward_exception:{exc.__class__.__name__}",
        }


def _send_outgoing_to_chatwoot(*, conversation_id: int, content: str) -> dict[str, Any]:
    base_url = _chatwoot_base_url()
    account_id = _chatwoot_account_id()
    api_token = _chatwoot_api_access_token()
    if not (base_url and account_id and api_token):
        return {"attempted": False, "ok": False, "reason": "chatwoot_not_configured", "status_code": None}

    url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{int(conversation_id)}/messages"
    payload = {"content": content, "message_type": "outgoing", "private": False}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "api_access_token": api_token},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10.0) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
            return {
                "attempted": True,
                "ok": 200 <= int(resp.status) < 300,
                "status_code": int(resp.status),
                "response_body": response_body[:1000],
                "reason": None,
            }
    except urlerror.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "attempted": True,
            "ok": False,
            "status_code": int(exc.code),
            "response_body": body_text[:1000],
            "reason": "chatwoot_http_error",
        }
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "status_code": None,
            "response_body": "",
            "reason": f"chatwoot_exception:{exc.__class__.__name__}",
        }


def _should_skip_webhook_forward(payload: dict[str, Any]) -> tuple[bool, str | None]:
    event_name = str(payload.get("event") or "").strip().lower()
    if event_name != "message_created":
        return False, None

    message_obj = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    message_type = str(payload.get("message_type") or message_obj.get("message_type") or "").strip().lower()
    if message_type == "outgoing":
        return True, "outgoing_message"

    sender_obj = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    sender_type = str(
        sender_obj.get("type")
        or sender_obj.get("sender_type")
        or payload.get("sender_type")
        or ""
    ).strip().lower()
    if sender_type in {"agent", "bot"}:
        return True, "agent_or_bot_message"

    return False, None


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


class ChatwootOutgoing(BaseModel):
    conversation_id: int = Field(..., ge=1)
    content: str = Field(..., min_length=1, max_length=4000)
    trace_id: str | None = Field(default=None, max_length=128)
    webhook_id: str | None = Field(default=None, max_length=128)


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


@app.post("/webhooks/garcom_digital")
async def garcom_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    event = payload.get("event")
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id")
    webhook_id = _new_id("whk")
    skip_forward, skip_reason = _should_skip_webhook_forward(payload)

    print(
        f"[{_now_iso()}] project={GARCOM_PROJECT} webhook_id={webhook_id} event={event} conversation_id={conversation_id}"
    )

    if skip_forward:
        return {
            "ok": True,
            "webhook_id": webhook_id,
            "project": GARCOM_PROJECT,
            "skipped": True,
            "reason": skip_reason,
            "forward": {"attempted": False, "ok": False, "reason": skip_reason, "status_code": None},
        }

    client = getattr(request.app.state, "redis", None)
    if client:
        key = f"wh:webhooks:{GARCOM_PROJECT}"
        event_doc = {
            "id": webhook_id,
            "project": GARCOM_PROJECT,
            "event": event,
            "conversation_id": conversation_id,
            "received_at": _now_iso(),
            "payload": payload,
        }
        pipe = client.pipeline(transaction=True)
        pipe.lpush(key, json.dumps(event_doc, ensure_ascii=False))
        pipe.ltrim(key, 0, _event_maxlen() - 1)
        pipe.execute()

    forward_result = _forward_webhook_payload(payload, webhook_id)
    return {
        "ok": True,
        "webhook_id": webhook_id,
        "project": GARCOM_PROJECT,
        "forward": forward_result,
    }


@app.post("/webhook")
async def garcom_webhook_alias(request: Request) -> dict[str, Any]:
    return await garcom_webhook(request)


@app.post("/bridge/chatwoot/outgoing")
async def bridge_chatwoot_outgoing(body: ChatwootOutgoing) -> dict[str, Any]:
    result = _send_outgoing_to_chatwoot(
        conversation_id=int(body.conversation_id),
        content=body.content,
    )
    return {
        "ok": bool(result.get("ok")),
        "trace_id": body.trace_id,
        "webhook_id": body.webhook_id,
        "chatwoot": result,
    }


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



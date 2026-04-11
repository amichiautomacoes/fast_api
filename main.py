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


def _evolution_base_url() -> str:
    return (os.getenv("EVOLUTION_BASE_URL") or "").rstrip("/")


def _evolution_api_key() -> str:
    return (os.getenv("EVOLUTION_API_KEY") or "").strip()


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


def _send_outgoing_to_evolution(
    *,
    instance: str,
    number: str,
    content: str,
    delay: int | None = None,
    link_preview: bool | None = None,
    quoted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = _evolution_base_url()
    api_key = _evolution_api_key()
    if not (base_url and api_key):
        return {"attempted": False, "ok": False, "reason": "evolution_not_configured", "status_code": None}
    if not instance.strip():
        return {"attempted": False, "ok": False, "reason": "evolution_instance_missing", "status_code": None}
    if not number.strip():
        return {"attempted": False, "ok": False, "reason": "evolution_number_missing", "status_code": None}

    url = f"{base_url}/message/sendText/{instance.strip()}"
    payload: dict[str, Any] = {
        "number": number.strip(),
        "text": content,
    }
    if delay is not None:
        payload["delay"] = int(delay)
    if link_preview is not None:
        payload["linkPreview"] = bool(link_preview)
    if quoted:
        payload["quoted"] = quoted

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "apikey": api_key},
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
            "reason": "evolution_http_error",
        }
    except Exception as exc:
        return {
            "attempted": True,
            "ok": False,
            "status_code": None,
            "response_body": "",
            "reason": f"evolution_exception:{exc.__class__.__name__}",
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
    def _first_string(*values: Any) -> str:
        for value in values:
            txt = str(value or "").strip().lower()
            if txt:
                return txt
        return ""

    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        txt = str(value or "").strip().lower()
        return txt in {"1", "true", "yes", "y", "fromme", "from_me"}

    event_name = _first_string(payload.get("event"), payload.get("event_type"), payload.get("type"))
    if event_name and event_name not in {"message_created", "messages_upsert", "send_message", "message"}:
        return False, None

    message_obj = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    message_type = _first_string(
        payload.get("message_type"),
        message_obj.get("message_type"),
        data_obj.get("message_type"),
    )
    if message_type in {"outgoing", "sent", "agent", "bot"}:
        return True, "outgoing_message"

    sender_obj = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    sender_type = _first_string(
        sender_obj.get("type"),
        sender_obj.get("sender_type"),
        payload.get("sender_type"),
        data_obj.get("sender_type"),
    )
    if sender_type in {"agent", "bot", "outgoing"}:
        return True, "agent_or_bot_message"

    if _is_truthy(payload.get("fromMe") or payload.get("from_me") or data_obj.get("fromMe") or data_obj.get("from_me")):
        return True, "from_me_message"

    key_obj = payload.get("key") if isinstance(payload.get("key"), dict) else {}
    data_key_obj = data_obj.get("key") if isinstance(data_obj.get("key"), dict) else {}
    if _is_truthy(key_obj.get("fromMe") or key_obj.get("from_me") or data_key_obj.get("fromMe") or data_key_obj.get("from_me")):
        return True, "from_me_message"

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


class EvolutionOutgoing(BaseModel):
    instance: str = Field(..., min_length=1, max_length=120)
    number: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=4000)
    delay: int | None = Field(default=None, ge=0, le=60000)
    link_preview: bool | None = None
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


def _handle_inbound_payload(
    *,
    payload: dict[str, Any],
    request: Request,
    webhook_id: str,
    source: str | None = None,
) -> dict[str, Any]:
    event = payload.get("event")
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id")
    skip_forward, skip_reason = _should_skip_webhook_forward(payload)

    print(
        f"[{_now_iso()}] project={GARCOM_PROJECT} source={source or 'auto'} webhook_id={webhook_id} event={event} conversation_id={conversation_id}"
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
        "source": source or "auto",
        "forward": forward_result,
    }


@app.post("/bridge/inbound")
async def bridge_inbound(request: Request, source: str = Query(default="auto")) -> dict[str, Any]:
    payload = await request.json()
    webhook_id = _new_id("whk")
    return _handle_inbound_payload(
        payload=payload,
        request=request,
        webhook_id=webhook_id,
        source=source,
    )


@app.post("/webhooks/garcom_digital")
async def garcom_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    webhook_id = _new_id("whk")
    return _handle_inbound_payload(
        payload=payload,
        request=request,
        webhook_id=webhook_id,
        source="garcom_digital",
    )


@app.post("/webhook")
async def garcom_webhook_alias(request: Request) -> dict[str, Any]:
    return await garcom_webhook(request)


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    webhook_id = _new_id("whk")
    return _handle_inbound_payload(
        payload=payload,
        request=request,
        webhook_id=webhook_id,
        source="chatwoot",
    )


@app.post("/webhook/evolution")
async def evolution_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    webhook_id = _new_id("whk")
    return _handle_inbound_payload(
        payload=payload,
        request=request,
        webhook_id=webhook_id,
        source="evolution",
    )


@app.post("/bridge/outgoing")
async def bridge_outgoing(body: dict[str, Any]) -> dict[str, Any]:
    destination = str(body.get("destination") or "chatwoot").strip().lower()
    content = str(body.get("content") or "").strip()
    trace_id = body.get("trace_id")
    webhook_id = body.get("webhook_id")

    if not content:
        raise HTTPException(status_code=422, detail="content is required")

    if destination == "chatwoot":
        conversation_id = body.get("conversation_id")
        if conversation_id is None:
            raise HTTPException(status_code=422, detail="conversation_id is required for chatwoot outbound")
        result = _send_outgoing_to_chatwoot(
            conversation_id=int(conversation_id),
            content=content,
        )
        return {
            "ok": bool(result.get("ok")),
            "destination": "chatwoot",
            "trace_id": trace_id,
            "webhook_id": webhook_id,
            "chatwoot": result,
        }

    if destination == "evolution":
        instance = str(body.get("instance") or "").strip()
        number = str(body.get("number") or "").strip()
        if not instance:
            raise HTTPException(status_code=422, detail="instance is required for evolution outbound")
        if not number:
            raise HTTPException(status_code=422, detail="number is required for evolution outbound")
        result = _send_outgoing_to_evolution(
            instance=instance,
            number=number,
            content=content,
            delay=body.get("delay"),
            link_preview=body.get("link_preview"),
            quoted=body.get("quoted") if isinstance(body.get("quoted"), dict) else None,
        )
        return {
            "ok": bool(result.get("ok")),
            "destination": "evolution",
            "trace_id": trace_id,
            "webhook_id": webhook_id,
            "evolution": result,
        }

    raise HTTPException(status_code=422, detail="destination must be 'chatwoot' or 'evolution'")


@app.post("/bridge/chatwoot/outgoing")
async def bridge_chatwoot_outgoing(body: ChatwootOutgoing) -> dict[str, Any]:
    return await bridge_outgoing(
        {
            "destination": "chatwoot",
            "conversation_id": body.conversation_id,
            "content": body.content,
            "trace_id": body.trace_id,
            "webhook_id": body.webhook_id,
        }
    )


@app.post("/bridge/evolution/outgoing")
async def bridge_evolution_outgoing(body: EvolutionOutgoing) -> dict[str, Any]:
    return await bridge_outgoing(
        {
            "destination": "evolution",
            "instance": body.instance,
            "number": body.number,
            "content": body.content,
            "delay": body.delay,
            "link_preview": body.link_preview,
            "trace_id": body.trace_id,
            "webhook_id": body.webhook_id,
        }
    )


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



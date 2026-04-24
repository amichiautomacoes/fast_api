import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import redis
from fastapi import FastAPI, Header, HTTPException, Request


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _event_maxlen() -> int:
    raw = os.getenv("WEBHOOK_EVENTS_MAXLEN", "1000").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 1000


def _pull_max_limit() -> int:
    raw = os.getenv("INBOX_PULL_MAX_LIMIT", "500").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 500


def _forward_timeout_seconds() -> float:
    raw = os.getenv("FORWARD_WEBHOOK_TIMEOUT_SECONDS", "10").strip()
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return 10.0


def _normalize_project(name: str) -> str:
    value = (name or "").strip().lower()
    if not value:
        return ""
    cleaned = []
    for ch in value:
        if ch.isalnum() or ch in {"_", "-", "."}:
            cleaned.append(ch)
    return "".join(cleaned)


def _extract_bearer_token(value: str | None) -> str:
    if not value:
        return ""
    txt = value.strip()
    if not txt:
        return ""
    low = txt.lower()
    if low.startswith("bearer "):
        return txt[7:].strip()
    return txt


def _load_project_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}

    json_raw = (os.getenv("WEBHOOK_PROJECT_TOKENS_JSON") or "").strip()
    if json_raw:
        try:
            parsed = json.loads(json_raw)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    project = _normalize_project(str(key))
                    token = str(value or "").strip()
                    if project and token:
                        tokens[project] = token
        except json.JSONDecodeError:
            pass

    csv_raw = (os.getenv("WEBHOOK_PROJECT_TOKENS") or "").strip()
    if csv_raw:
        for pair in csv_raw.split(","):
            item = pair.strip()
            if not item or ":" not in item:
                continue
            left, right = item.split(":", 1)
            project = _normalize_project(left)
            token = right.strip()
            if project and token:
                tokens[project] = token

    return tokens


def _normalize_route_key(project: str, source: str) -> str:
    return f"{_normalize_project(project)}:{_normalize_project(source)}"


def _load_forward_routes() -> dict[str, str]:
    routes: dict[str, str] = {}

    json_raw = (os.getenv("FORWARD_ROUTES_JSON") or "").strip()
    if json_raw:
        try:
            parsed = json.loads(json_raw)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    url = str(value or "").strip()
                    if not url:
                        continue
                    normalized_key = str(key).replace("/", ":").strip().lower()
                    if ":" not in normalized_key:
                        continue
                    project, source = normalized_key.split(":", 1)
                    route_key = _normalize_route_key(project, source)
                    if route_key and url:
                        routes[route_key] = url
        except json.JSONDecodeError:
            pass

    # Backward compatibility for the previous single-project setup.
    garcom_url = (os.getenv("FORWARD_WEBHOOK_URL_GARCOM_DIGITAL") or "").strip()
    if garcom_url:
        routes[_normalize_route_key("garcom_digital", "chatwoot")] = garcom_url
        routes[_normalize_route_key("garcom_digital", "default")] = garcom_url

    return routes


def _resolve_forward_url(project: str, source: str) -> str:
    routes = _load_forward_routes()
    p = _normalize_project(project)
    s = _normalize_project(source)
    candidates = [
        _normalize_route_key(p, s),
        _normalize_route_key(p, "default"),
        _normalize_route_key("default", s),
        _normalize_route_key("default", "default"),
    ]
    for key in candidates:
        url = routes.get(key)
        if url:
            return url
    return ""


def _forward_webhook_payload(
    payload: dict[str, Any],
    webhook_id: str,
    project: str,
    source: str,
) -> dict[str, Any]:
    forward_url = _resolve_forward_url(project, source)
    if not forward_url:
        return {"attempted": False, "ok": False, "reason": "forward_not_configured", "status_code": None}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        forward_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Source-Webhook-Id": webhook_id,
            "X-Webhook-Project": project,
            "X-Webhook-Source": source,
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


def _validate_project_token(
    project: str,
    authorization: str | None,
    x_webhook_token: str | None,
) -> None:
    require_token = _bool_env("WEBHOOK_REQUIRE_TOKEN", True)
    if not require_token:
        return

    per_project_tokens = _load_project_tokens()
    global_token = (os.getenv("WEBHOOK_GLOBAL_TOKEN") or "").strip()

    normalized_project = _normalize_project(project)
    expected = per_project_tokens.get(normalized_project) or global_token
    if not expected:
        if require_token:
            raise HTTPException(status_code=401, detail="No token configured for project")
        return

    received = _extract_bearer_token(authorization) or _extract_bearer_token(x_webhook_token)
    if not received or received != expected:
        raise HTTPException(status_code=401, detail="Invalid token")


app = FastAPI(title="Webhook Hub API", version="3.0.0")


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


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return {"ok": True}


def _store_event(
    *,
    request: Request,
    project: str,
    source: str,
    webhook_id: str,
    payload: dict[str, Any],
) -> None:
    client = getattr(request.app.state, "redis", None)
    if not client:
        return

    key = f"wh:webhooks:{project}:{source}"
    event_doc = {
        "id": webhook_id,
        "project": project,
        "source": source,
        "received_at": _now_iso(),
        "payload": payload,
    }
    pipe = client.pipeline(transaction=True)
    pipe.lpush(key, json.dumps(event_doc, ensure_ascii=False))
    pipe.ltrim(key, 0, _event_maxlen() - 1)
    pipe.execute()


def _require_redis(request: Request) -> redis.Redis:
    client = getattr(request.app.state, "redis", None)
    if not client:
        raise HTTPException(status_code=503, detail="REDIS_URL not configured or Redis unavailable")
    return client


def _events_key(project: str, source: str) -> str:
    return f"wh:webhooks:{project}:{source}"


async def _handle_webhook(
    *,
    request: Request,
    project: str,
    source: str,
    authorization: str | None,
    x_webhook_token: str | None,
) -> dict[str, Any]:
    normalized_project = _normalize_project(project)
    normalized_source = _normalize_project(source)
    if not normalized_project:
        raise HTTPException(status_code=422, detail="Invalid project")
    if not normalized_source:
        raise HTTPException(status_code=422, detail="Invalid source")

    _validate_project_token(normalized_project, authorization, x_webhook_token)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JSON body must be an object")

    webhook_id = _new_id("whk")
    _store_event(
        request=request,
        project=normalized_project,
        source=normalized_source,
        webhook_id=webhook_id,
        payload=payload,
    )

    forward_result = _forward_webhook_payload(
        payload=payload,
        webhook_id=webhook_id,
        project=normalized_project,
        source=normalized_source,
    )

    return {
        "ok": True,
        "webhook_id": webhook_id,
        "project": normalized_project,
        "source": normalized_source,
        "forward": forward_result,
    }


@app.post("/v1/webhooks/{project}/{source}")
async def post_webhook_v1(
    project: str,
    source: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return await _handle_webhook(
        request=request,
        project=project,
        source=source,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
    )


@app.post("/rd/entrada")
async def rd_entrada(
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None),
) -> dict[str, Any]:
    project = (os.getenv("DEFAULT_PROJECT") or "default").strip() or "default"
    return await _handle_webhook(
        request=request,
        project=project,
        source="rd_station",
        authorization=authorization,
        x_webhook_token=x_webhook_token,
    )


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(
    request: Request,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None),
) -> dict[str, Any]:
    project = (os.getenv("CHATWOOT_DEFAULT_PROJECT") or "garcom_digital").strip() or "garcom_digital"
    return await _handle_webhook(
        request=request,
        project=project,
        source="chatwoot",
        authorization=authorization,
        x_webhook_token=x_webhook_token,
    )


@app.post("/v1/inbox/{project}/{source}/pull")
async def pull_webhook_events(
    project: str,
    source: str,
    request: Request,
    limit: int = 50,
    authorization: str | None = Header(default=None),
    x_webhook_token: str | None = Header(default=None),
) -> dict[str, Any]:
    normalized_project = _normalize_project(project)
    normalized_source = _normalize_project(source)
    if not normalized_project:
        raise HTTPException(status_code=422, detail="Invalid project")
    if not normalized_source:
        raise HTTPException(status_code=422, detail="Invalid source")

    _validate_project_token(normalized_project, authorization, x_webhook_token)
    client = _require_redis(request)

    safe_limit = max(1, min(int(limit), _pull_max_limit()))
    key = _events_key(normalized_project, normalized_source)

    # Consume events from Redis queue (FIFO for oldest first in returned payload).
    raw_items = client.lpop(key, safe_limit)
    if raw_items is None:
        raw_list: list[str] = []
    elif isinstance(raw_items, list):
        raw_list = [str(item) for item in raw_items]
    else:
        raw_list = [str(raw_items)]

    events: list[dict[str, Any]] = []
    for item in raw_list:
        try:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                events.append(parsed)
        except json.JSONDecodeError:
            continue

    # Reverse so consumers process in chronological order.
    events.reverse()
    remaining = client.llen(key)
    return {
        "ok": True,
        "project": normalized_project,
        "source": normalized_source,
        "pulled": len(events),
        "remaining": int(remaining),
        "events": events,
    }

"""HW4 FastAPI server. Run: uvicorn server:app --host 0.0.0.0 --port 8080."""

import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from contextlib import asynccontextmanager
import anyio
from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool
from cloud_log import emit
from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.cloud import pubsub_v1, storage

# This is the assignment's simulated policy, not a statement of current law.
FORBIDDEN = {
    "north korea": "North Korea", "kp": "North Korea", "prk": "North Korea",
    "dprk": "North Korea", "iran": "Iran", "ir": "Iran", "irn": "Iran",
    "cuba": "Cuba", "cu": "Cuba", "cub": "Cuba",
    "myanmar": "Myanmar", "burma": "Myanmar", "mm": "Myanmar", "mmr": "Myanmar",
    "iraq": "Iraq", "iq": "Iraq", "irq": "Iraq",
    "libya": "Libya", "ly": "Libya", "lby": "Libya",
    "sudan": "Sudan", "sd": "Sudan", "sdn": "Sudan",
    "zimbabwe": "Zimbabwe", "zw": "Zimbabwe", "zwe": "Zimbabwe",
    "syria": "Syria", "sy": "Syria", "syr": "Syria",
}


@lru_cache(maxsize=1)
def clients():
    # In the cloud, ADC resolves to the attached runtime service account.
    return storage.Client(), pubsub_v1.PublisherClient()


def log_error(event, message):
    status = event.get("status")
    severity = "CRITICAL" if event.get("event") == "forbidden_country" else ("ERROR" if status in {501, 503} else "WARNING")
    emit({"message": message, **event}, severity)


def reply(body, status, request_id, content_type="text/plain; charset=utf-8"):
    return Response(body, status_code=status, headers={
        "Content-Type": content_type,
        "X-Request-ID": request_id, "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


def serve_file(request, filename=None):
    request_id = str(uuid.uuid4())
    event = {
        "event_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": request.method,
        "path": request.url.path,
        "country": request.headers.get("X-country", "").strip(),
    }
    if request.method not in {"GET", "POST"}:
        log_error({**event, "event": "unsupported_method", "status": 501}, "Method not implemented")
        return reply("Method not implemented\n", 501, request_id)

    if isinstance(filename, str):
        event["file"] = filename
    country = FORBIDDEN.get(" ".join(event["country"].casefold().split()))
    if country:
        denied = {**event, "event": "forbidden_country", "country": country, "status": 400}
        log_error(denied, f"Permission denied for country {country}")
        try:
            _, publisher = clients()
            # Wait for acknowledgement from Pub/Sub before returning to the client.
            publisher.publish(os.environ["TOPIC_PATH"], json.dumps(denied).encode()).result(timeout=20)
        except Exception as error:
            log_error({**event, "event": "publish_failed", "status": 503,
                       "error_type": type(error).__name__}, "Could not publish forbidden request")
            return reply("Notification service unavailable; retry later\n", 503, request_id)
        return reply(f"Permission denied: {country}\n", 400, request_id)

    if not isinstance(filename, str) or not filename:
        status = 404 if request.method == "GET" else 400
        log_error({**event, "event": "missing_filename", "status": status}, "Missing file name")
        return reply("Supply a file path (GET) or a file field (POST)\n", status, request_id)

    prefix = os.environ.get("DATA_PREFIX", "").strip("/")
    object_name = f"{prefix}/{filename}" if prefix else filename
    log_prefix = os.environ.get("LOG_PREFIX", "logs/hw3/").strip("/") + "/"
    event["file"] = object_name
    # Keep the HTTP service restricted to data, not its own audit log directory.
    if any(part in {"", ".", ".."} for part in filename.split("/")) or object_name.startswith(log_prefix):
        log_error({**event, "event": "not_found", "status": 404}, "File not found")
        return reply("File not found\n", 404, request_id)
    try:
        storage_client, _ = clients()
        blob = storage_client.bucket(os.environ["BUCKET_NAME"]).blob(object_name)
        body = blob.download_as_bytes(timeout=30)
    except NotFound:
        log_error({**event, "event": "not_found", "status": 404}, "File not found")
        return reply("File not found\n", 404, request_id)
    except GoogleAPICallError as error:
        log_error({**event, "event": "storage_failed", "status": 503,
                   "error_type": type(error).__name__}, "Storage unavailable")
        return reply("Storage unavailable; retry later\n", 503, request_id)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return reply(body, 200, request_id, content_type)


@asynccontextmanager
async def lifespan(app):
    # Keep synchronous Google SDK calls off the event loop, with bounded threads.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 8
    yield


app = FastAPI(title="CS528 HW4", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def unsupported_methods(request: Request, call_next):
    # Intercept before routing, including OPTIONS and CONNECT authority targets.
    if request.method not in {"GET", "POST"}:
        return await run_in_threadpool(serve_file, request)
    return await call_next(request)


@app.api_route("/", methods=["GET", "POST"])
@app.api_route("/{path:path}", methods=["GET", "POST"])
async def file_endpoint(request: Request):
    filename = request.url.path.lstrip("/")
    if request.method == "POST":
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return Response("Request body too large\n", status_code=413)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        try:
            if content_type == "application/json" or content_type.endswith("+json"):
                payload = json.loads(body)
                filename = payload.get("file") if isinstance(payload, dict) else None
            elif content_type == "text/plain":
                filename = body.decode("utf-8").strip()
            elif content_type == "application/x-www-form-urlencoded":
                from urllib.parse import parse_qs
                filename = parse_qs(body.decode("utf-8")).get("file", [None])[0]
            else:
                filename = None
        except (ValueError, UnicodeDecodeError):
            filename = None
    return await run_in_threadpool(serve_file, request, filename)

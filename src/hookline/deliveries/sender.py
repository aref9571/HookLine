import json
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx2

from hookline.config import APP_VERSION, Settings
from hookline.deliveries.signing import build_signature_header
from hookline.endpoints.url_safety import Resolver, validate_target_url
from hookline.errors import InvalidFieldError

logger = logging.getLogger(__name__)

MAX_RESPONSE_EXCERPT_CHARACTERS = 1000


@dataclass
class DeliveryRequest:
    url: str = field(repr=False)
    secret: str = field(repr=False)
    event_id: uuid.UUID
    event_type: str
    event_created_at: datetime
    payload: dict[str, Any] = field(repr=False)
    attempt_number: int


@dataclass
class DeliveryResult:
    succeeded: bool
    status_code: int | None
    error: str | None
    duration_ms: int
    response_excerpt: str | None


def build_body(request: DeliveryRequest) -> bytes:
    message = {
        "id": str(request.event_id),
        "type": request.event_type,
        "created_at": request.event_created_at.isoformat(),
        "data": request.payload,
    }
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode()


def build_headers(request: DeliveryRequest, body: bytes, now: datetime) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": f"Hookline/{APP_VERSION}",
        "Hookline-Event-Id": str(request.event_id),
        "Hookline-Event-Type": request.event_type,
        "Hookline-Attempt": str(request.attempt_number),
        "Hookline-Signature": build_signature_header(request.secret, int(now.timestamp()), body),
    }


def read_excerpt(response: httpx2.Response) -> str | None:
    excerpt = ""
    for chunk in response.iter_text():
        excerpt += chunk
        if len(excerpt) >= MAX_RESPONSE_EXCERPT_CHARACTERS:
            break
    if not excerpt:
        return None
    return excerpt[:MAX_RESPONSE_EXCERPT_CHARACTERS]


def classify_status(status_code: int) -> tuple[bool, str | None]:
    if 200 <= status_code <= 299:
        return True, None
    if 300 <= status_code <= 399:
        return False, "redirect not followed"
    return False, None


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def failed_result(error: str, duration_ms: int) -> DeliveryResult:
    return DeliveryResult(
        succeeded=False,
        status_code=None,
        error=error,
        duration_ms=duration_ms,
        response_excerpt=None,
    )


def post_delivery(
    client: httpx2.Client, url: str, body: bytes, headers: dict[str, str], timeout_seconds: int
) -> DeliveryResult:
    started = time.monotonic()
    try:
        with client.stream(
            "POST",
            url,
            content=body,
            headers=headers,
            follow_redirects=False,
            timeout=timeout_seconds,
        ) as response:
            excerpt = read_excerpt(response)
    except httpx2.TimeoutException:
        return failed_result("timeout", elapsed_ms(started))
    except httpx2.TransportError:
        return failed_result("connection error", elapsed_ms(started))
    except httpx2.HTTPError:
        return failed_result("request failed", elapsed_ms(started))

    succeeded, error = classify_status(response.status_code)
    return DeliveryResult(
        succeeded=succeeded,
        status_code=response.status_code,
        error=error,
        duration_ms=elapsed_ms(started),
        response_excerpt=excerpt,
    )


def send_delivery(
    client: httpx2.Client,
    request: DeliveryRequest,
    now: datetime,
    settings: Settings,
    resolver: Resolver = socket.getaddrinfo,
) -> DeliveryResult:
    try:
        validate_target_url(request.url, settings, resolver)
    except InvalidFieldError:
        logger.warning("Delivery target not allowed for event %s", request.event_id)
        return failed_result("target address not allowed", 0)

    body = build_body(request)
    headers = build_headers(request, body, now)
    return post_delivery(client, request.url, body, headers, settings.delivery_timeout_seconds)

import json
import socket
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest

from hookline.config import APP_VERSION, Settings
from hookline.deliveries.sender import DeliveryRequest, DeliveryResult, send_delivery
from hookline.deliveries.signing import sign, verify_signature
from tests.conftest import UNREACHABLE_DATABASE_URL

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
EVENT_ID = uuid.UUID("0b6f5c3e-8f7a-4f2e-9a51-3c2d1e0f9a87")
SECRET = "whsec_sender-test-secret"
TARGET_URL = "https://hooks.example.com/webhook"

FAKE_DNS = {
    "hooks.example.com": ["93.184.215.14"],
    "internal.example.com": ["10.1.2.3"],
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def fake_resolver(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
    if host not in FAKE_DNS:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))
        for address in FAKE_DNS[host]
    ]


def make_settings() -> Settings:
    return Settings(database_url=UNREACHABLE_DATABASE_URL, delivery_timeout_seconds=7)


def make_request(url: str = TARGET_URL) -> DeliveryRequest:
    return DeliveryRequest(
        url=url,
        secret=SECRET,
        event_id=EVENT_ID,
        event_type="order.created",
        event_created_at=datetime(2026, 10, 17, 11, 59, 30, tzinfo=UTC),
        payload={"order_id": 42, "customer": "Zoë"},
        attempt_number=3,
    )


def send_with(
    handler: Handler, request: DeliveryRequest | None = None
) -> tuple[DeliveryResult, list[httpx2.Request]]:
    sent: list[httpx2.Request] = []

    def recording_handler(outgoing: httpx2.Request) -> httpx2.Response:
        sent.append(outgoing)
        return handler(outgoing)

    with httpx2.Client(transport=httpx2.MockTransport(recording_handler)) as client:
        result = send_delivery(
            client, request or make_request(), NOW, make_settings(), fake_resolver
        )
    return result, sent


def respond_with(
    status_code: int, text: str = "", headers: dict[str, str] | None = None
) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, text=text, headers=headers)

    return handler


def raise_error(error: type[httpx2.RequestError]) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error("failed", request=request)

    return handler


def test_sent_body_is_compact_json_with_the_event() -> None:
    result, sent = send_with(respond_with(200))

    assert result.succeeded
    assert len(sent) == 1
    assert sent[0].method == "POST"
    assert str(sent[0].url) == TARGET_URL
    assert (
        sent[0].content
        == (
            '{"id":"0b6f5c3e-8f7a-4f2e-9a51-3c2d1e0f9a87","type":"order.created",'
            '"created_at":"2026-10-17T11:59:30+00:00",'
            '"data":{"order_id":42,"customer":"Zoë"}}'
        ).encode()
    )
    assert json.loads(sent[0].content)["data"] == {"order_id": 42, "customer": "Zoë"}


def test_sent_body_bytes_are_the_signed_bytes() -> None:
    _, sent = send_with(respond_with(200))

    timestamp = int(NOW.timestamp())
    signature_header = sent[0].headers["Hookline-Signature"]
    assert signature_header == f"t={timestamp},v1={sign(SECRET, timestamp, sent[0].content)}"
    assert verify_signature(SECRET, signature_header, sent[0].content, NOW)


def test_all_required_headers_are_sent() -> None:
    _, sent = send_with(respond_with(200))

    headers = sent[0].headers
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == f"Hookline/{APP_VERSION}"
    assert headers["Hookline-Event-Id"] == str(EVENT_ID)
    assert headers["Hookline-Event-Type"] == "order.created"
    assert headers["Hookline-Attempt"] == "3"
    assert headers["Hookline-Signature"].startswith(f"t={int(NOW.timestamp())},v1=")


def test_request_uses_the_delivery_timeout_setting() -> None:
    _, sent = send_with(respond_with(200))

    assert sent[0].extensions["timeout"] == {"connect": 7, "read": 7, "write": 7, "pool": 7}


@pytest.mark.parametrize("status_code", [200, 204])
def test_2xx_responses_succeed(status_code: int) -> None:
    result, _ = send_with(respond_with(status_code))

    assert result.succeeded
    assert result.status_code == status_code
    assert result.error is None
    assert result.duration_ms >= 0


@pytest.mark.parametrize("status_code", [400, 410, 500])
def test_error_responses_fail_with_the_status_code(status_code: int) -> None:
    result, _ = send_with(respond_with(status_code, text="no thanks"))

    assert not result.succeeded
    assert result.status_code == status_code
    assert result.error is None
    assert result.response_excerpt == "no thanks"


def test_redirect_is_not_followed_and_fails() -> None:
    result, sent = send_with(
        respond_with(301, headers={"Location": "https://hooks.example.com/other"})
    )

    assert not result.succeeded
    assert result.status_code == 301
    assert result.error == "redirect not followed"
    assert len(sent) == 1


def test_timeout_fails_without_an_exception() -> None:
    result, _ = send_with(raise_error(httpx2.ReadTimeout))

    assert result == DeliveryResult(
        succeeded=False,
        status_code=None,
        error="timeout",
        duration_ms=result.duration_ms,
        response_excerpt=None,
    )


def test_connection_error_fails_without_an_exception() -> None:
    result, _ = send_with(raise_error(httpx2.ConnectError))

    assert not result.succeeded
    assert result.status_code is None
    assert result.error == "connection error"
    assert result.response_excerpt is None


def test_other_request_error_fails_without_an_exception() -> None:
    result, _ = send_with(raise_error(httpx2.DecodingError))

    assert not result.succeeded
    assert result.status_code is None
    assert result.error == "request failed"


def test_long_response_body_is_cut_to_1000_characters() -> None:
    result, _ = send_with(respond_with(200, text="é" * 5000))

    assert result.response_excerpt == "é" * 1000


def test_empty_response_body_gives_no_excerpt() -> None:
    result, _ = send_with(respond_with(204))

    assert result.response_excerpt is None


@pytest.mark.parametrize(
    "url",
    [
        "https://internal.example.com/webhook",
        "https://localhost/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://unknown.example.com/webhook",
        "http://hooks.example.com/webhook",
    ],
)
def test_unsafe_url_is_not_requested(url: str) -> None:
    result, sent = send_with(respond_with(200), make_request(url))

    assert sent == []
    assert result == DeliveryResult(
        succeeded=False,
        status_code=None,
        error="target address not allowed",
        duration_ms=0,
        response_excerpt=None,
    )

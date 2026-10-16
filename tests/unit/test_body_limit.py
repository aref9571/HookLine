from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from hookline.config import Settings
from hookline.errors import PROBLEM_JSON
from hookline.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL

LIMIT = 100


def echo_json(body: dict[str, Any]) -> dict[str, Any]:
    return body


async def count_bytes(request: Request) -> dict[str, int]:
    return {"size": len(await request.body())}


def build_test_app() -> FastAPI:
    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL, max_body_bytes=LIMIT))
    app.add_api_route("/test/echo", echo_json, methods=["POST"])
    app.add_api_route("/test/size", count_bytes, methods=["POST"])
    return app


def make_client() -> TestClient:
    return TestClient(build_test_app())


def chunks(sizes: list[int]) -> Iterator[bytes]:
    for size in sizes:
        yield b"x" * size


def assert_body_too_large(response: Any) -> None:
    assert response.status_code == 413
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["status"] == 413
    assert body["type"] == "about:blank"
    assert body["detail"] == "The request body is too large."


def test_body_at_the_limit_is_accepted() -> None:
    response = make_client().post("/test/size", content=b"x" * LIMIT)

    assert response.status_code == 200
    assert response.json() == {"size": LIMIT}


def test_declared_body_over_the_limit_returns_413() -> None:
    response = make_client().post("/test/size", content=b"x" * (LIMIT + 1))

    assert_body_too_large(response)


def test_declared_json_body_over_the_limit_returns_413_before_validation() -> None:
    response = make_client().post("/test/echo", json={"data": "x" * LIMIT})

    assert_body_too_large(response)


def test_chunked_body_within_the_limit_is_accepted() -> None:
    response = make_client().post("/test/size", content=chunks([40, 40, 20]))

    assert response.status_code == 200
    assert response.json() == {"size": LIMIT}


def test_chunked_body_that_grows_over_the_limit_returns_413() -> None:
    response = make_client().post("/test/size", content=chunks([40, 40, 40]))

    assert_body_too_large(response)


def test_chunked_json_body_over_the_limit_returns_413() -> None:
    response = make_client().post(
        "/test/echo",
        content=chunks([60, 60]),
        headers={"Content-Type": "application/json"},
    )

    assert_body_too_large(response)


def test_requests_without_body_are_not_affected() -> None:
    response = make_client().get("/health/live")

    assert response.status_code == 200

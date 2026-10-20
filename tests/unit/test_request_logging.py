import logging
import re

import pytest
from fastapi.testclient import TestClient

from hookline.config import Settings
from hookline.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL

LOGGER_NAME = "hookline.request_logging"


def request_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]


def test_each_request_is_logged_with_method_path_status_and_duration(
    client_without_database: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    client_without_database.get("/health/live")
    client_without_database.post("/api/v1/auth/login", json={})
    client_without_database.get("/no-such-path")

    lines = request_lines(caplog)
    assert len(lines) == 3
    assert re.fullmatch(r"GET /health/live 200 duration_ms=\d+", lines[0])
    assert re.fullmatch(r"POST /api/v1/auth/login 400 duration_ms=\d+", lines[1])
    assert re.fullmatch(r"GET /no-such-path 404 duration_ms=\d+", lines[2])


def test_query_strings_headers_and_bodies_are_not_logged(
    client_without_database: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    client_without_database.post(
        "/api/v1/auth/login?token=query-secret",
        json={"email": "user@example.com", "password": "body-secret-password"},
        headers={"Authorization": "Bearer header-secret", "X-API-Key": "hk_header-key"},
    )

    lines = request_lines(caplog)
    assert len(lines) == 1
    assert lines[0].startswith("POST /api/v1/auth/login 503 ")
    for secret in ("query-secret", "body-secret-password", "header-secret", "hk_header-key"):
        assert secret not in caplog.text


def test_unhandled_error_is_logged_as_500(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL))

    @app.get("/broken")
    def broken() -> None:
        raise RuntimeError("boom")

    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/broken")
    app.state.engine.dispose()

    assert response.status_code == 500
    assert len(request_lines(caplog)) == 1
    assert re.fullmatch(r"GET /broken 500 duration_ms=\d+", request_lines(caplog)[0])


def test_rejected_large_body_is_logged_as_413(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL, max_body_bytes=10))
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    with TestClient(app) as client:
        client.post("/api/v1/events", content=b"x" * 11)
    app.state.engine.dispose()

    assert len(request_lines(caplog)) == 1
    assert request_lines(caplog)[0].startswith("POST /api/v1/events 413 ")

from fastapi.testclient import TestClient

from hookline.config import Settings
from hookline.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL


def test_responses_have_nosniff_header(client_without_database: TestClient) -> None:
    responses = [
        client_without_database.get("/health/live"),
        client_without_database.get("/no-such-path"),
        client_without_database.get("/health/ready"),
    ]

    assert [response.status_code for response in responses] == [200, 404, 503]
    for response in responses:
        assert response.headers["x-content-type-options"] == "nosniff"


def test_only_auth_responses_forbid_caching(client_without_database: TestClient) -> None:
    auth_response = client_without_database.post("/api/v1/auth/login", json={})
    other_response = client_without_database.get("/health/live")

    assert auth_response.status_code == 400
    assert auth_response.headers["cache-control"] == "no-store"
    assert "cache-control" not in other_response.headers


def test_body_too_large_response_has_nosniff_header() -> None:
    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL, max_body_bytes=10))
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", content=b"x" * 11)
    app.state.engine.dispose()

    assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_cors_is_not_enabled(client_without_database: TestClient) -> None:
    response = client_without_database.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers

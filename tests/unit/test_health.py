from fastapi.testclient import TestClient

from hookline.errors import PROBLEM_JSON


def test_live_returns_ok(client_without_database: TestClient) -> None:
    response = client_without_database.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_problem_details_when_database_is_unreachable(
    client_without_database: TestClient,
) -> None:
    response = client_without_database.get("/health/ready")

    assert response.status_code == 503
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json() == {
        "type": "about:blank",
        "title": "Service unavailable",
        "status": 503,
        "detail": "The database is not available.",
    }


def test_docs_page_is_available(client_without_database: TestClient) -> None:
    response = client_without_database.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_openapi_schema_is_available(client_without_database: TestClient) -> None:
    response = client_without_database.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Hookline"
    assert schema["info"]["version"] == "1.0.0"
    assert "/health/live" in schema["paths"]
    assert "/health/ready" in schema["paths"]

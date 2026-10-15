import pytest
from fastapi.testclient import TestClient

from hookline.errors import PROBLEM_JSON


def test_users_me_without_token_returns_401_with_www_authenticate(
    client_without_database: TestClient,
) -> None:
    response = client_without_database.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json()["detail"] == "Missing bearer token."


@pytest.mark.parametrize("header", ["Bearer not-a-token", "Basic dXNlcjpwYXNz", "Bearer"])
def test_users_me_with_invalid_authorization_returns_401(
    client_without_database: TestClient, header: str
) -> None:
    response = client_without_database.get("/api/v1/users/me", headers={"Authorization": header})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_with_missing_fields_returns_400(client_without_database: TestClient) -> None:
    response = client_without_database.post("/api/v1/auth/login", json={"email": "a@b.co"})

    assert response.status_code == 400
    assert response.json()["errors"] == [{"field": "password", "message": "Field required"}]


def test_refresh_with_empty_token_returns_400(client_without_database: TestClient) -> None:
    response = client_without_database.post("/api/v1/auth/refresh", json={"refresh_token": ""})

    assert response.status_code == 400


def test_openapi_schema_lists_the_auth_routes(client_without_database: TestClient) -> None:
    paths = client_without_database.get("/openapi.json").json()["paths"]

    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/users/me" in paths

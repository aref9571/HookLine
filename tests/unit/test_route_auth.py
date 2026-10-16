import uuid

import pytest
from fastapi.testclient import TestClient

ANY_ID = str(uuid.uuid4())

JWT_ROUTES = [
    ("POST", "/api/v1/users"),
    ("GET", "/api/v1/users"),
    ("PATCH", "/api/v1/users/" + ANY_ID),
    ("POST", "/api/v1/api-keys"),
    ("GET", "/api/v1/api-keys"),
    ("DELETE", "/api/v1/api-keys/" + ANY_ID),
    ("POST", "/api/v1/endpoints"),
    ("GET", "/api/v1/endpoints"),
    ("GET", "/api/v1/endpoints/" + ANY_ID),
    ("PATCH", "/api/v1/endpoints/" + ANY_ID),
    ("DELETE", "/api/v1/endpoints/" + ANY_ID),
    ("POST", "/api/v1/endpoints/" + ANY_ID + "/rotate-secret"),
    ("GET", "/api/v1/events"),
    ("GET", "/api/v1/events/" + ANY_ID),
]


@pytest.mark.parametrize(("method", "path"), JWT_ROUTES)
def test_jwt_routes_reject_anonymous_requests(
    client_without_database: TestClient, method: str, path: str
) -> None:
    response = client_without_database.request(method, path, json={})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_openapi_schema_lists_user_and_api_key_routes(client_without_database: TestClient) -> None:
    paths = client_without_database.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/users"]) == {"get", "post"}
    assert set(paths["/api/v1/users/{user_id}"]) == {"patch"}
    assert set(paths["/api/v1/api-keys"]) == {"get", "post"}
    assert set(paths["/api/v1/api-keys/{api_key_id}"]) == {"delete"}


def test_openapi_schema_lists_endpoint_routes(client_without_database: TestClient) -> None:
    paths = client_without_database.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/endpoints"]) == {"get", "post"}
    assert set(paths["/api/v1/endpoints/{endpoint_id}"]) == {"get", "patch", "delete"}
    assert set(paths["/api/v1/endpoints/{endpoint_id}/rotate-secret"]) == {"post"}


def test_event_intake_rejects_requests_without_api_key(
    client_without_database: TestClient,
) -> None:
    response = client_without_database.post(
        "/api/v1/events", json={"event_type": "order.created", "payload": {}}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


def test_openapi_schema_lists_event_routes(client_without_database: TestClient) -> None:
    paths = client_without_database.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/events"]) == {"get", "post"}
    assert set(paths["/api/v1/events/{event_id}"]) == {"get"}

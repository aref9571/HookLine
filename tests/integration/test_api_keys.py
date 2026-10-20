import hashlib
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.users.models import User, UserRole
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def owner_headers(client: TestClient, owner: User) -> dict[str, str]:
    return auth_headers(client, OWNER_EMAIL)


@pytest.fixture
def other_headers(client: TestClient, db_session: Session) -> dict[str, str]:
    add_user(db_session, OTHER_EMAIL)
    return auth_headers(client, OTHER_EMAIL)


def create_key(client: TestClient, headers: dict[str, str], name: str = "Shop") -> dict[str, str]:
    response = client.post("/api/v1/api-keys", json={"name": name}, headers=headers)
    assert response.status_code == 201
    body: dict[str, str] = response.json()
    return body


def test_creating_a_key_returns_the_plaintext_once_and_stores_its_hash(
    client: TestClient, owner_headers: dict[str, str], owner: User, db_session: Session
) -> None:
    body = create_key(client, owner_headers, "  Shop backend  ")

    assert set(body) == {
        "id",
        "name",
        "prefix",
        "last_used_at",
        "revoked_at",
        "created_at",
        "key",
        "message",
    }
    assert body["name"] == "Shop backend"
    assert body["key"].startswith("hk_")
    assert len(body["key"]) == 46
    assert body["prefix"] == body["key"][:12]
    assert body["message"] == "Store this key now. It will not be shown again."
    stored = db_session.get(ApiKey, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.user_id == owner.id
    assert stored.key_hash == hashlib.sha256(body["key"].encode()).hexdigest()


def test_each_key_is_different(client: TestClient, owner_headers: dict[str, str]) -> None:
    first = create_key(client, owner_headers)
    second = create_key(client, owner_headers)

    assert first["key"] != second["key"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_creating_a_key_validates_the_name(
    client: TestClient, owner_headers: dict[str, str], name: str
) -> None:
    response = client.post("/api/v1/api-keys", json={"name": name}, headers=owner_headers)

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "name"


def test_listing_shows_only_own_keys_without_plaintext_or_hash(
    client: TestClient,
    owner_headers: dict[str, str],
    other_headers: dict[str, str],
    db_session: Session,
) -> None:
    first = create_key(client, owner_headers, "first")
    second = create_key(client, owner_headers, "second")
    create_key(client, other_headers, "not mine")

    response = client.get("/api/v1/api-keys", headers=owner_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [key["name"] for key in body["items"]] == ["second", "first"]
    assert set(body["items"][0]) == {
        "id",
        "name",
        "prefix",
        "last_used_at",
        "revoked_at",
        "created_at",
    }
    stored = db_session.get(ApiKey, uuid.UUID(first["id"]))
    assert stored is not None
    for secret in (first["key"], second["key"], stored.key_hash):
        assert secret not in response.text


def test_listing_keys_is_paginated(client: TestClient, owner_headers: dict[str, str]) -> None:
    for number in range(3):
        create_key(client, owner_headers, f"key {number}")

    response = client.get(
        "/api/v1/api-keys", params={"limit": 1, "offset": 1}, headers=owner_headers
    )

    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert [key["name"] for key in body["items"]] == ["key 1"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_listing_keys_rejects_invalid_page_parameters(
    client: TestClient, owner_headers: dict[str, str], params: dict[str, int]
) -> None:
    response = client.get("/api/v1/api-keys", params=params, headers=owner_headers)

    assert response.status_code == 400


def test_revoking_a_key_sets_revoked_at_and_twice_is_fine(
    client: TestClient, owner_headers: dict[str, str], db_session: Session
) -> None:
    key = create_key(client, owner_headers)

    first = client.delete(f"/api/v1/api-keys/{key['id']}", headers=owner_headers)
    stored = db_session.get(ApiKey, uuid.UUID(key["id"]))
    assert stored is not None
    revoked_at = stored.revoked_at
    second = client.delete(f"/api/v1/api-keys/{key['id']}", headers=owner_headers)
    db_session.refresh(stored)

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 204
    assert revoked_at is not None
    assert stored.revoked_at == revoked_at
    listed = client.get("/api/v1/api-keys", headers=owner_headers).json()["items"]
    assert listed[0]["revoked_at"] is not None


def test_revoking_another_users_key_returns_404(
    client: TestClient,
    owner_headers: dict[str, str],
    other_headers: dict[str, str],
    db_session: Session,
) -> None:
    key = create_key(client, owner_headers)

    response = client.delete(f"/api/v1/api-keys/{key['id']}", headers=other_headers)

    assert response.status_code == 404
    stored = db_session.get(ApiKey, uuid.UUID(key["id"]))
    assert stored is not None
    assert stored.revoked_at is None


def test_admins_also_see_and_revoke_only_their_own_keys(
    client: TestClient,
    owner_headers: dict[str, str],
    db_session: Session,
) -> None:
    key = create_key(client, owner_headers)
    add_user(db_session, "admin@example.com", UserRole.ADMIN)
    admin_headers = auth_headers(client, "admin@example.com")

    listed = client.get("/api/v1/api-keys", headers=admin_headers)
    revoked = client.delete(f"/api/v1/api-keys/{key['id']}", headers=admin_headers)

    assert listed.json()["total"] == 0
    assert revoked.status_code == 404
    stored = db_session.get(ApiKey, uuid.UUID(key["id"]))
    assert stored is not None
    assert stored.revoked_at is None


def test_revoking_an_unknown_key_returns_404(
    client: TestClient, owner_headers: dict[str, str]
) -> None:
    response = client.delete(f"/api/v1/api-keys/{uuid.uuid4()}", headers=owner_headers)

    assert response.status_code == 404


def test_api_key_plaintext_and_hash_never_appear_in_logs(
    client: TestClient,
    owner_headers: dict[str, str],
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    key = create_key(client, owner_headers)
    client.delete(f"/api/v1/api-keys/{key['id']}", headers=owner_headers)

    stored = db_session.get(ApiKey, uuid.UUID(key["id"]))
    assert stored is not None
    assert "API key" in caplog.text
    assert key["key"] not in caplog.text
    assert stored.key_hash not in caplog.text

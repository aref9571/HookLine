import logging
import socket
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hookline.clock import get_now
from hookline.deliveries.models import Delivery, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.endpoints.url_safety import get_resolver
from hookline.events.models import Event
from hookline.users.models import User, UserRole
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"
ADMIN_EMAIL = "admin@example.com"
FIXED_NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
SECRET_MESSAGE = "Store this secret now. It will not be shown again."

FAKE_DNS = {
    "hooks.example.com": "93.184.215.14",
    "orders.example.com": "93.184.215.15",
    "internal.example.com": "10.0.0.7",
}

READ_FIELDS = {
    "id",
    "user_id",
    "url",
    "description",
    "event_types",
    "is_active",
    "created_at",
    "updated_at",
}


def fake_resolver(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
    if host not in FAKE_DNS:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (FAKE_DNS[host], 0))]


@pytest.fixture
def api(client: TestClient) -> TestClient:
    client.app.dependency_overrides[get_resolver] = lambda: fake_resolver
    return client


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def owner_headers(api: TestClient, owner: User) -> dict[str, str]:
    return auth_headers(api, OWNER_EMAIL)


@pytest.fixture
def other_headers(api: TestClient, db_session: Session) -> dict[str, str]:
    add_user(db_session, OTHER_EMAIL)
    return auth_headers(api, OTHER_EMAIL)


@pytest.fixture
def admin_headers(api: TestClient, db_session: Session) -> dict[str, str]:
    add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)
    return auth_headers(api, ADMIN_EMAIL)


def endpoint_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": "https://hooks.example.com/webhook",
        "description": "Order system",
        "event_types": ["order.created", "order.paid"],
    }
    body.update(changes)
    return body


def create_endpoint(api: TestClient, headers: dict[str, str], **changes: Any) -> dict[str, Any]:
    response = api.post("/api/v1/endpoints", json=endpoint_body(**changes), headers=headers)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def endpoint_url(endpoint: dict[str, Any]) -> str:
    return "/api/v1/endpoints/" + endpoint["id"]


def test_creating_an_endpoint_returns_the_secret_once_and_stores_it(
    api: TestClient, owner_headers: dict[str, str], owner: User, db_session: Session
) -> None:
    body = create_endpoint(api, owner_headers)

    assert set(body) == READ_FIELDS | {"secret", "message"}
    assert body["user_id"] == str(owner.id)
    assert body["url"] == "https://hooks.example.com/webhook"
    assert body["description"] == "Order system"
    assert body["event_types"] == ["order.created", "order.paid"]
    assert body["is_active"] is True
    assert body["secret"].startswith("whsec_")
    assert len(body["secret"]) == 49
    assert body["message"] == SECRET_MESSAGE
    stored = db_session.get(Endpoint, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.secret == body["secret"]


def test_each_endpoint_gets_a_different_secret(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    first = create_endpoint(api, owner_headers)
    second = create_endpoint(api, owner_headers)

    assert first["secret"] != second["secret"]


def test_creating_an_endpoint_accepts_the_wildcard_and_no_description(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    response = api.post(
        "/api/v1/endpoints",
        json={"url": "https://hooks.example.com", "event_types": ["*"]},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.json()["event_types"] == ["*"]
    assert response.json()["description"] is None


def test_full_endpoint_flow_shows_the_secret_only_on_create_and_rotate(
    api: TestClient, owner_headers: dict[str, str], db_session: Session
) -> None:
    created = create_endpoint(api, owner_headers)
    path = endpoint_url(created)
    api.app.dependency_overrides[get_now] = lambda: FIXED_NOW

    listed = api.get("/api/v1/endpoints", headers=owner_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert set(listed.json()["items"][0]) == READ_FIELDS

    fetched = api.get(path, headers=owner_headers)
    assert fetched.status_code == 200
    assert set(fetched.json()) == READ_FIELDS

    updated = api.patch(
        path,
        json={
            "url": "https://orders.example.com/v2",
            "description": "New order system",
            "event_types": ["order.refunded"],
            "is_active": False,
        },
        headers=owner_headers,
    )
    assert updated.status_code == 200
    assert set(updated.json()) == READ_FIELDS
    assert updated.json()["url"] == "https://orders.example.com/v2"
    assert updated.json()["description"] == "New order system"
    assert updated.json()["event_types"] == ["order.refunded"]
    assert updated.json()["is_active"] is False
    assert updated.json()["updated_at"] == "2030-01-02T03:04:05Z"

    rotated = api.post(path + "/rotate-secret", headers=owner_headers)
    assert rotated.status_code == 200
    assert set(rotated.json()) == READ_FIELDS | {"secret", "message"}
    assert rotated.json()["secret"].startswith("whsec_")
    assert rotated.json()["secret"] != created["secret"]
    stored = db_session.get(Endpoint, uuid.UUID(created["id"]))
    assert stored is not None
    db_session.refresh(stored)
    assert stored.secret == rotated.json()["secret"]

    deleted = api.delete(path, headers=owner_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api.get(path, headers=owner_headers).status_code == 404
    assert api.delete(path, headers=owner_headers).status_code == 404


def test_secret_is_never_in_responses_other_than_create_and_rotate(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    created = create_endpoint(api, owner_headers)
    path = endpoint_url(created)
    responses = [
        api.get("/api/v1/endpoints", headers=owner_headers),
        api.get(path, headers=owner_headers),
        api.patch(path, json={"description": "changed"}, headers=owner_headers),
    ]

    for response in responses:
        assert response.status_code == 200
        assert created["secret"] not in response.text
        assert "whsec_" not in response.text


def test_patch_changes_only_the_fields_sent(api: TestClient, owner_headers: dict[str, str]) -> None:
    created = create_endpoint(api, owner_headers)

    response = api.patch(endpoint_url(created), json={"is_active": False}, headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["url"] == created["url"]
    assert response.json()["description"] == created["description"]
    assert response.json()["event_types"] == created["event_types"]
    assert response.json()["is_active"] is False


def test_patch_treats_null_as_no_change_except_for_description(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    created = create_endpoint(api, owner_headers)

    response = api.patch(
        endpoint_url(created),
        json={"url": None, "event_types": None, "is_active": None},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["url"] == created["url"]
    assert response.json()["event_types"] == created["event_types"]
    assert response.json()["is_active"] is True
    assert response.json()["description"] == created["description"]


def test_patch_with_null_description_clears_it(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    created = create_endpoint(api, owner_headers)

    response = api.patch(endpoint_url(created), json={"description": None}, headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["description"] is None


def test_patch_revalidates_the_url(
    api: TestClient, owner_headers: dict[str, str], db_session: Session
) -> None:
    created = create_endpoint(api, owner_headers)

    response = api.patch(
        endpoint_url(created),
        json={"url": "https://internal.example.com/hook"},
        headers=owner_headers,
    )

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["errors"] == [
        {"field": "url", "message": "must not point to a private or reserved address"}
    ]
    stored = db_session.get(Endpoint, uuid.UUID(created["id"]))
    assert stored is not None
    assert stored.url == created["url"]


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://hooks.example.com/webhook", "must use https"),
        ("https://127.0.0.1/webhook", "must not point to a private or reserved address"),
        ("https://localhost/webhook", "must not point to localhost"),
        ("https://internal.example.com/webhook", "must not point to a private or reserved address"),
        ("https://unknown.example.com/webhook", "host could not be resolved"),
    ],
)
def test_creating_an_endpoint_rejects_unsafe_urls(
    api: TestClient,
    owner_headers: dict[str, str],
    db_session: Session,
    url: str,
    message: str,
) -> None:
    response = api.post("/api/v1/endpoints", json=endpoint_body(url=url), headers=owner_headers)

    assert response.status_code == 400
    assert response.json() == {
        "type": "about:blank",
        "title": "Invalid request",
        "status": 400,
        "detail": "One or more fields are invalid.",
        "errors": [{"field": "url", "message": message}],
    }
    assert db_session.scalars(select(Endpoint)).all() == []


@pytest.mark.parametrize(
    "event_types",
    [
        ["Order.Created"],
        ["order created"],
        [],
        ["type." + str(number) for number in range(51)],
        ["order.created", "order.created"],
        ["*", "order.created"],
        [""],
        ["-order"],
        ["a" * 101],
    ],
)
def test_invalid_event_types_return_400(
    api: TestClient, owner_headers: dict[str, str], event_types: list[str]
) -> None:
    response = api.post(
        "/api/v1/endpoints", json=endpoint_body(event_types=event_types), headers=owner_headers
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"].startswith("event_types")


def test_event_types_accept_50_items_and_100_characters(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    event_types = ["type." + str(number) for number in range(49)] + ["a" * 100]

    response = api.post(
        "/api/v1/endpoints", json=endpoint_body(event_types=event_types), headers=owner_headers
    )

    assert response.status_code == 201
    assert response.json()["event_types"] == event_types


def test_patch_rejects_invalid_event_types(api: TestClient, owner_headers: dict[str, str]) -> None:
    created = create_endpoint(api, owner_headers)

    response = api.patch(
        endpoint_url(created), json={"event_types": ["Bad Type"]}, headers=owner_headers
    )

    assert response.status_code == 400


def test_description_longer_than_255_characters_returns_400(
    api: TestClient, owner_headers: dict[str, str]
) -> None:
    response = api.post(
        "/api/v1/endpoints", json=endpoint_body(description="d" * 256), headers=owner_headers
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "description"


def test_members_get_404_for_endpoints_of_other_users(
    api: TestClient,
    owner_headers: dict[str, str],
    other_headers: dict[str, str],
    db_session: Session,
) -> None:
    created = create_endpoint(api, owner_headers)
    path = endpoint_url(created)

    responses = [
        api.get(path, headers=other_headers),
        api.patch(path, json={"is_active": False}, headers=other_headers),
        api.delete(path, headers=other_headers),
        api.post(path + "/rotate-secret", headers=other_headers),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json()["detail"] == "Endpoint not found."
    stored = db_session.get(Endpoint, uuid.UUID(created["id"]))
    assert stored is not None
    db_session.refresh(stored)
    assert stored.is_active is True
    assert stored.secret == created["secret"]


def test_unknown_endpoint_returns_404(api: TestClient, owner_headers: dict[str, str]) -> None:
    response = api.get("/api/v1/endpoints/" + str(uuid.uuid4()), headers=owner_headers)

    assert response.status_code == 404


def test_members_list_only_their_own_endpoints(
    api: TestClient, owner_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    own = create_endpoint(api, owner_headers)
    create_endpoint(api, other_headers)

    response = api.get("/api/v1/endpoints", headers=owner_headers)

    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [own["id"]]


def test_admins_see_and_manage_all_endpoints(
    api: TestClient,
    owner_headers: dict[str, str],
    other_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    first = create_endpoint(api, owner_headers)
    second = create_endpoint(api, other_headers)

    listed = api.get("/api/v1/endpoints", headers=admin_headers)
    fetched = api.get(endpoint_url(first), headers=admin_headers)
    updated = api.patch(endpoint_url(second), json={"is_active": False}, headers=admin_headers)

    assert listed.json()["total"] == 2
    assert {item["id"] for item in listed.json()["items"]} == {first["id"], second["id"]}
    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False


def test_listing_is_paginated_newest_first(api: TestClient, owner_headers: dict[str, str]) -> None:
    created = [create_endpoint(api, owner_headers) for _ in range(3)]

    first_page = api.get("/api/v1/endpoints?limit=2", headers=owner_headers).json()
    second_page = api.get("/api/v1/endpoints?limit=2&offset=2", headers=owner_headers).json()

    assert first_page["total"] == 3
    assert first_page["limit"] == 2
    assert first_page["offset"] == 0
    assert [item["id"] for item in first_page["items"]] == [created[2]["id"], created[1]["id"]]
    assert [item["id"] for item in second_page["items"]] == [created[0]["id"]]
    assert second_page["offset"] == 2


def test_listing_can_filter_by_is_active(api: TestClient, owner_headers: dict[str, str]) -> None:
    active = create_endpoint(api, owner_headers)
    inactive = create_endpoint(api, owner_headers)
    api.patch(endpoint_url(inactive), json={"is_active": False}, headers=owner_headers)

    active_page = api.get("/api/v1/endpoints?is_active=true", headers=owner_headers).json()
    inactive_page = api.get("/api/v1/endpoints?is_active=false", headers=owner_headers).json()

    assert [item["id"] for item in active_page["items"]] == [active["id"]]
    assert active_page["total"] == 1
    assert [item["id"] for item in inactive_page["items"]] == [inactive["id"]]
    assert inactive_page["total"] == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "is_active=maybe"])
def test_listing_rejects_invalid_query_parameters(
    api: TestClient, owner_headers: dict[str, str], query: str
) -> None:
    response = api.get("/api/v1/endpoints?" + query, headers=owner_headers)

    assert response.status_code == 400


def test_deleting_an_endpoint_deletes_its_deliveries(
    api: TestClient, owner_headers: dict[str, str], owner: User, db_session: Session
) -> None:
    created = create_endpoint(api, owner_headers)
    event = Event(user_id=owner.id, event_type="order.created", payload={"id": 1})
    db_session.add(event)
    db_session.flush()
    db_session.add(
        Delivery(
            event_id=event.id,
            endpoint_id=uuid.UUID(created["id"]),
            status=DeliveryStatus.PENDING.value,
            next_attempt_at=FIXED_NOW,
        )
    )
    db_session.commit()

    response = api.delete(endpoint_url(created), headers=owner_headers)

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.scalars(select(Delivery)).all() == []
    assert db_session.get(Event, event.id) is not None


def test_secrets_and_urls_are_not_logged(
    api: TestClient, owner_headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    created = create_endpoint(api, owner_headers, url="https://hooks.example.com/private-token")
    rotated = api.post(endpoint_url(created) + "/rotate-secret", headers=owner_headers).json()

    assert created["secret"] not in caplog.text
    assert rotated["secret"] not in caplog.text
    assert "private-token" not in caplog.text
    assert created["id"] in caplog.text

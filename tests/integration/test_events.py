import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hookline.api_keys.service import create_api_key
from hookline.clock import get_now
from hookline.deliveries.models import Delivery, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events import service
from hookline.events.models import Event
from hookline.users.models import User, UserRole
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"
ADMIN_EMAIL = "admin@example.com"
EVENTS_PATH = "/api/v1/events"
START = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
ORDER_CREATED = {"event_type": "order.created", "payload": {"order_id": 42, "total": "9.99"}}


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def owner_key(db_session: Session, owner: User) -> dict[str, str]:
    return {"X-API-Key": create_api_key(db_session, owner, "shop").plaintext}


@pytest.fixture
def other(db_session: Session) -> User:
    return add_user(db_session, OTHER_EMAIL)


@pytest.fixture
def other_key(db_session: Session, other: User) -> dict[str, str]:
    return {"X-API-Key": create_api_key(db_session, other, "other shop").plaintext}


def add_endpoint(
    db_session: Session, user: User, event_types: list[str], is_active: bool = True
) -> Endpoint:
    endpoint = Endpoint(
        user_id=user.id,
        url="https://hooks.example.com/webhook",
        event_types=event_types,
        secret="whsec_test",
        is_active=is_active,
    )
    db_session.add(endpoint)
    db_session.commit()
    return endpoint


def submit(
    client: TestClient,
    headers: dict[str, str],
    body: dict[str, Any] = ORDER_CREATED,
    idempotency_key: str | None = None,
) -> Any:
    request_headers = dict(headers)
    if idempotency_key is not None:
        request_headers["Idempotency-Key"] = idempotency_key
    return client.post(EVENTS_PATH, json=body, headers=request_headers)


def count_rows(db_session: Session, model: type[Event] | type[Delivery]) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(model)) or 0


def deliveries_of(db_session: Session, event_id: str) -> list[Delivery]:
    db_session.expire_all()
    query = select(Delivery).where(Delivery.event_id == uuid.UUID(event_id))
    return list(db_session.scalars(query))


def test_event_without_endpoints_is_stored_with_no_deliveries(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    client.app.dependency_overrides[get_now] = lambda: START

    response = submit(client, owner_key)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "created_at", "delivery_count"}
    assert body["delivery_count"] == 0
    assert body["created_at"] == "2030-01-01T12:00:00Z"
    assert "idempotent-replayed" not in response.headers
    event = db_session.get(Event, uuid.UUID(body["id"]))
    assert event is not None
    assert event.user_id == owner.id
    assert event.api_key_id is not None
    assert event.event_type == "order.created"
    assert event.payload == {"order_id": 42, "total": "9.99"}
    assert event.idempotency_key is None
    assert event.request_hash is not None
    assert len(event.request_hash) == 64


def test_matching_endpoint_gets_one_pending_delivery_due_now(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    endpoint = add_endpoint(db_session, owner, ["order.created", "order.paid"])
    client.app.dependency_overrides[get_now] = lambda: START

    response = submit(client, owner_key)

    assert response.status_code == 201
    assert response.json()["delivery_count"] == 1
    deliveries = deliveries_of(db_session, response.json()["id"])
    assert len(deliveries) == 1
    assert deliveries[0].endpoint_id == endpoint.id
    assert deliveries[0].status == DeliveryStatus.PENDING
    assert deliveries[0].attempt_count == 0
    assert deliveries[0].next_attempt_at == START


def test_delivery_count_counts_only_matching_active_endpoints_of_the_owner(
    client: TestClient,
    owner_key: dict[str, str],
    owner: User,
    other: User,
    db_session: Session,
) -> None:
    matching = add_endpoint(db_session, owner, ["order.created"])
    wildcard = add_endpoint(db_session, owner, ["*"])
    add_endpoint(db_session, owner, ["order.created"], is_active=False)
    add_endpoint(db_session, owner, ["order.paid"])
    add_endpoint(db_session, other, ["order.created"])
    add_endpoint(db_session, other, ["*"])

    response = submit(client, owner_key)

    assert response.status_code == 201
    assert response.json()["delivery_count"] == 2
    deliveries = deliveries_of(db_session, response.json()["id"])
    assert {delivery.endpoint_id for delivery in deliveries} == {matching.id, wildcard.id}


@pytest.mark.parametrize(
    ("event_types", "is_active", "expected"),
    [
        (["order.created"], True, 1),
        (["*"], True, 1),
        (["order.created"], False, 0),
        (["order.paid", "order.refunded"], True, 0),
    ],
)
def test_delivery_count_for_each_kind_of_endpoint(
    client: TestClient,
    owner_key: dict[str, str],
    owner: User,
    db_session: Session,
    event_types: list[str],
    is_active: bool,
    expected: int,
) -> None:
    add_endpoint(db_session, owner, event_types, is_active)

    response = submit(client, owner_key)

    assert response.status_code == 201
    assert response.json()["delivery_count"] == expected
    assert count_rows(db_session, Delivery) == expected


def test_another_users_endpoint_is_ignored(
    client: TestClient, owner_key: dict[str, str], other: User, db_session: Session
) -> None:
    add_endpoint(db_session, other, ["*"])

    response = submit(client, owner_key)

    assert response.status_code == 201
    assert response.json()["delivery_count"] == 0


@pytest.mark.parametrize("key", [None, "", "hk_unknown-key"])
def test_missing_or_wrong_api_key_returns_401(client: TestClient, key: str | None) -> None:
    headers = {} if key is None else {"X-API-Key": key}

    response = submit(client, headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"
    assert response.headers["content-type"] == "application/problem+json"


def test_revoked_api_key_returns_401(client: TestClient, owner: User, db_session: Session) -> None:
    created = create_api_key(db_session, owner, "old")
    created.api_key.revoked_at = START
    db_session.commit()

    response = submit(client, {"X-API-Key": created.plaintext})

    assert response.status_code == 401
    assert count_rows(db_session, Event) == 0


def test_bearer_token_is_not_accepted_for_event_intake(client: TestClient, owner: User) -> None:
    response = submit(client, auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"


@pytest.mark.parametrize("payload", [[1, 2, 3], "text", 42, None, True])
def test_payload_that_is_not_an_object_returns_400(
    client: TestClient, owner_key: dict[str, str], payload: Any
) -> None:
    response = submit(client, owner_key, {"event_type": "order.created", "payload": payload})

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "payload"


@pytest.mark.parametrize("event_type", ["*", "Order.Created", "order created", "", "a" * 101])
def test_invalid_event_type_returns_400(
    client: TestClient, owner_key: dict[str, str], event_type: str
) -> None:
    response = submit(client, owner_key, {"event_type": event_type, "payload": {}})

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "event_type"


def test_missing_fields_return_400(client: TestClient, owner_key: dict[str, str]) -> None:
    response = client.post(EVENTS_PATH, json={}, headers=owner_key)

    assert response.status_code == 400
    fields = {error["field"] for error in response.json()["errors"]}
    assert fields == {"event_type", "payload"}


def test_payload_larger_than_the_limit_returns_413(
    client: TestClient, owner_key: dict[str, str], db_session: Session
) -> None:
    payload = {"data": "x" * 65536}

    response = submit(client, owner_key, {"event_type": "order.created", "payload": payload})

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "The payload must be at most 65536 bytes."
    assert count_rows(db_session, Event) == 0


def test_payload_at_the_limit_is_accepted(client: TestClient, owner_key: dict[str, str]) -> None:
    payload = {"data": "x" * (65536 - len('{"data":""}'))}

    response = submit(client, owner_key, {"event_type": "order.created", "payload": payload})

    assert response.status_code == 201


def test_declared_body_over_the_size_limit_returns_413(
    client: TestClient, owner_key: dict[str, str], db_session: Session
) -> None:
    body = b'{"event_type": "order.created", "payload": {"data": "' + b"x" * 262144 + b'"}}'
    headers = owner_key | {"Content-Type": "application/json"}

    response = client.post(EVENTS_PATH, content=body, headers=headers)

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "The request body is too large."
    assert count_rows(db_session, Event) == 0


def test_chunked_body_over_the_size_limit_returns_413(
    client: TestClient, owner_key: dict[str, str], db_session: Session
) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"event_type": "order.created", "payload": {"data": "'
        for _ in range(5):
            yield b"x" * 65536
        yield b'"}}'

    headers = owner_key | {"Content-Type": "application/json"}

    response = client.post(EVENTS_PATH, content=chunks(), headers=headers)

    assert response.status_code == 413
    assert response.json()["detail"] == "The request body is too large."
    assert count_rows(db_session, Event) == 0


def test_same_idempotency_key_and_body_replays_the_event(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    add_endpoint(db_session, owner, ["order.created"])
    first = submit(client, owner_key, idempotency_key="order-42")

    second = submit(client, owner_key, idempotency_key="order-42")

    assert first.status_code == 201
    assert "idempotent-replayed" not in first.headers
    assert second.status_code == 200
    assert second.headers["idempotent-replayed"] == "true"
    assert second.json() == first.json()
    assert count_rows(db_session, Event) == 1
    assert count_rows(db_session, Delivery) == 1


def test_replay_ignores_the_order_of_keys_in_the_body(
    client: TestClient, owner_key: dict[str, str]
) -> None:
    first = submit(client, owner_key, {"event_type": "a", "payload": {"x": 1, "y": 2}}, "k1")
    second = submit(client, owner_key, {"payload": {"y": 2, "x": 1}, "event_type": "a"}, "k1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.parametrize(
    "changed_body",
    [
        {"event_type": "order.paid", "payload": {"order_id": 42, "total": "9.99"}},
        {"event_type": "order.created", "payload": {"order_id": 43, "total": "9.99"}},
    ],
)
def test_same_idempotency_key_with_a_different_body_returns_409(
    client: TestClient,
    owner_key: dict[str, str],
    owner: User,
    db_session: Session,
    changed_body: dict[str, Any],
) -> None:
    add_endpoint(db_session, owner, ["*"])
    submit(client, owner_key, idempotency_key="order-42")

    response = submit(client, owner_key, changed_body, idempotency_key="order-42")

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert count_rows(db_session, Event) == 1
    assert count_rows(db_session, Delivery) == 1


def test_same_idempotency_key_from_two_users_creates_two_events(
    client: TestClient,
    owner_key: dict[str, str],
    other_key: dict[str, str],
    db_session: Session,
) -> None:
    first = submit(client, owner_key, idempotency_key="shared-key")
    second = submit(client, other_key, idempotency_key="shared-key")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert count_rows(db_session, Event) == 2


def test_two_keys_of_the_same_user_share_idempotency_keys(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    second_key = {"X-API-Key": create_api_key(db_session, owner, "second").plaintext}
    first = submit(client, owner_key, idempotency_key="order-42")

    second = submit(client, second_key, idempotency_key="order-42")

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.parametrize("key", ["", " ", "a" * 101, "has space", "slash/key", "at@sign"])
def test_invalid_idempotency_key_returns_400(
    client: TestClient, owner_key: dict[str, str], key: str, db_session: Session
) -> None:
    headers = owner_key | {"Idempotency-Key": key}

    response = client.post(EVENTS_PATH, json=ORDER_CREATED, headers=headers)

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "Idempotency-Key"
    assert count_rows(db_session, Event) == 0


@pytest.mark.parametrize("key", ["a", "A" * 100, "order_42.retry:1-b"])
def test_valid_idempotency_keys_are_accepted(
    client: TestClient, owner_key: dict[str, str], key: str, db_session: Session
) -> None:
    response = submit(client, owner_key, idempotency_key=key)

    assert response.status_code == 201
    event = db_session.get(Event, uuid.UUID(response.json()["id"]))
    assert event is not None
    assert event.idempotency_key == key


def test_concurrent_requests_with_the_same_idempotency_key_create_one_event(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    add_endpoint(db_session, owner, ["order.created"])
    add_endpoint(db_session, owner, ["*"])
    thread_count = 10
    barrier = threading.Barrier(thread_count)
    responses: list[Any] = []
    lock = threading.Lock()

    def send() -> None:
        barrier.wait()
        response = submit(client, owner_key, idempotency_key="race")
        with lock:
            responses.append(response)

    threads = [threading.Thread(target=send) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(responses) == thread_count
    assert sorted(response.status_code for response in responses).count(201) == 1
    assert {response.status_code for response in responses} <= {200, 201}
    assert len({response.json()["id"] for response in responses}) == 1
    assert {response.json()["delivery_count"] for response in responses} == {2}
    assert count_rows(db_session, Event) == 1
    assert count_rows(db_session, Delivery) == 2


def test_failed_delivery_creation_leaves_no_event(
    client: TestClient,
    owner_key: dict[str, str],
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_endpoint(db_session, owner, ["*"])

    def fail(*args: Any) -> int:
        raise RuntimeError("delivery insert failed")

    monkeypatch.setattr(service, "create_deliveries", fail)
    failing_client = TestClient(client.app, raise_server_exceptions=False)

    response = submit(failing_client, owner_key, idempotency_key="order-42")

    assert response.status_code == 500
    assert count_rows(db_session, Event) == 0
    assert count_rows(db_session, Delivery) == 0
    monkeypatch.undo()
    retried = submit(client, owner_key, idempotency_key="order-42")
    assert retried.status_code == 201
    assert retried.json()["delivery_count"] == 1


def test_payloads_and_api_keys_are_not_logged(
    client: TestClient, owner_key: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    body = {"event_type": "order.created", "payload": {"card": "secret-card-number"}}

    with caplog.at_level(logging.DEBUG):
        response = submit(client, owner_key, body)

    assert response.status_code == 201
    assert "secret-card-number" not in caplog.text
    assert owner_key["X-API-Key"] not in caplog.text
    assert response.json()["id"] in caplog.text


def fixed_clock(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


@pytest.fixture
def events_by_time(
    client: TestClient,
    owner_key: dict[str, str],
    other_key: dict[str, str],
) -> list[str]:
    ids = []
    for minutes, event_type, headers in [
        (0, "order.created", owner_key),
        (10, "order.paid", owner_key),
        (20, "order.created", owner_key),
        (30, "order.created", other_key),
    ]:
        moment = START + timedelta(minutes=minutes)
        client.app.dependency_overrides[get_now] = fixed_clock(moment)
        response = submit(client, headers, {"event_type": event_type, "payload": {"n": minutes}})
        assert response.status_code == 201
        ids.append(response.json()["id"])
    client.app.dependency_overrides.pop(get_now)
    return ids


def list_ids(client: TestClient, headers: dict[str, str], **params: Any) -> list[str]:
    response = client.get(EVENTS_PATH, params=params, headers=headers)
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


def test_members_list_only_their_own_events_newest_first(
    client: TestClient, events_by_time: list[str]
) -> None:
    headers = auth_headers(client, OWNER_EMAIL)

    response = client.get(EVENTS_PATH, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == events_by_time[2::-1]
    assert set(body["items"][0]) == {
        "id",
        "user_id",
        "api_key_id",
        "event_type",
        "idempotency_key",
        "created_at",
    }


def test_admins_list_all_events(
    client: TestClient, events_by_time: list[str], db_session: Session
) -> None:
    add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)

    ids = list_ids(client, auth_headers(client, ADMIN_EMAIL))

    assert ids == events_by_time[::-1]


def test_listing_is_paginated(client: TestClient, events_by_time: list[str]) -> None:
    headers = auth_headers(client, OWNER_EMAIL)

    response = client.get(EVENTS_PATH, params={"limit": 2, "offset": 1}, headers=headers)

    assert response.json()["total"] == 3
    assert [item["id"] for item in response.json()["items"]] == [
        events_by_time[1],
        events_by_time[0],
    ]


def test_listing_filters_by_event_type(client: TestClient, events_by_time: list[str]) -> None:
    headers = auth_headers(client, OWNER_EMAIL)

    assert list_ids(client, headers, event_type="order.paid") == [events_by_time[1]]
    assert list_ids(client, headers, event_type="order.unknown") == []


def test_listing_filters_by_creation_time(client: TestClient, events_by_time: list[str]) -> None:
    headers = auth_headers(client, OWNER_EMAIL)
    ten_past = (START + timedelta(minutes=10)).isoformat()
    twenty_past = (START + timedelta(minutes=20)).isoformat()

    assert list_ids(client, headers, created_after=ten_past) == events_by_time[2:0:-1]
    assert list_ids(client, headers, created_before=ten_past) == [events_by_time[0]]
    assert list_ids(client, headers, created_after=ten_past, created_before=twenty_past) == [
        events_by_time[1]
    ]


@pytest.mark.parametrize("minutes", [0, -1])
def test_created_before_must_be_after_created_after(
    client: TestClient, owner: User, minutes: int
) -> None:
    params = {
        "created_after": START.isoformat(),
        "created_before": (START + timedelta(minutes=minutes)).isoformat(),
    }

    response = client.get(EVENTS_PATH, params=params, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"field": "created_before", "message": "must be after created_after"}
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"created_after": "yesterday"},
        {"created_after": "2030-01-01T12:00:00"},
        {"limit": 0},
        {"offset": -1},
    ],
)
def test_listing_rejects_invalid_query_parameters(
    client: TestClient, owner: User, params: dict[str, Any]
) -> None:
    response = client.get(EVENTS_PATH, params=params, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 400


def test_event_details_include_payload_and_delivery_summary(
    client: TestClient, owner_key: dict[str, str], owner: User, db_session: Session
) -> None:
    first = add_endpoint(db_session, owner, ["order.created"])
    second = add_endpoint(db_session, owner, ["*"])
    created = submit(client, owner_key, idempotency_key="order-42").json()

    response = client.get(
        EVENTS_PATH + "/" + created["id"], headers=auth_headers(client, OWNER_EMAIL)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["user_id"] == str(owner.id)
    assert body["event_type"] == "order.created"
    assert body["idempotency_key"] == "order-42"
    assert body["payload"] == {"order_id": 42, "total": "9.99"}
    assert "request_hash" not in body
    assert {delivery["endpoint_id"] for delivery in body["deliveries"]} == {
        str(first.id),
        str(second.id),
    }
    for delivery in body["deliveries"]:
        assert set(delivery) == {"id", "endpoint_id", "status", "attempt_count"}
        assert delivery["status"] == "pending"
        assert delivery["attempt_count"] == 0


def test_members_get_404_for_events_of_other_users(
    client: TestClient, other_key: dict[str, str], owner: User
) -> None:
    created = submit(client, other_key).json()

    response = client.get(
        EVENTS_PATH + "/" + created["id"], headers=auth_headers(client, OWNER_EMAIL)
    )

    assert response.status_code == 404


def test_admins_can_read_events_of_other_users(
    client: TestClient, owner_key: dict[str, str], db_session: Session
) -> None:
    add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)
    created = submit(client, owner_key).json()

    response = client.get(
        EVENTS_PATH + "/" + created["id"], headers=auth_headers(client, ADMIN_EMAIL)
    )

    assert response.status_code == 200
    assert response.json()["deliveries"] == []


def test_unknown_event_returns_404(client: TestClient, owner: User) -> None:
    path = EVENTS_PATH + "/" + str(uuid.uuid4())

    response = client.get(path, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 404

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hookline.clock import get_now
from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events.models import Event
from hookline.users.models import User, UserRole
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"
ADMIN_EMAIL = "admin@example.com"
DELIVERIES_PATH = "/api/v1/deliveries"
START = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
RETRY_TIME = datetime(2030, 1, 2, 8, 30, tzinfo=UTC)


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def other(db_session: Session) -> User:
    return add_user(db_session, OTHER_EMAIL)


@pytest.fixture
def admin(db_session: Session) -> User:
    return add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)


def add_endpoint(
    db_session: Session,
    user: User,
    url: str = "https://hooks.example.com/webhook",
    is_active: bool = True,
) -> Endpoint:
    endpoint = Endpoint(
        user_id=user.id,
        url=url,
        event_types=["*"],
        secret="whsec_test",
        is_active=is_active,
    )
    db_session.add(endpoint)
    db_session.commit()
    return endpoint


def add_event(db_session: Session, user: User, event_type: str = "order.created") -> Event:
    event = Event(user_id=user.id, event_type=event_type, payload={}, created_at=START)
    db_session.add(event)
    db_session.commit()
    return event


def add_delivery(
    db_session: Session,
    endpoint: Endpoint,
    event: Event | None = None,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    created_at: datetime = START,
) -> Delivery:
    if event is None:
        event = add_event(db_session, db_session.get_one(User, endpoint.user_id))
    delivery = Delivery(
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=status,
        attempt_count=3 if status in [DeliveryStatus.DEAD, DeliveryStatus.FAILED] else 0,
        next_attempt_at=created_at + timedelta(hours=1),
        locked_until=created_at + timedelta(minutes=1)
        if status == DeliveryStatus.IN_PROGRESS
        else None,
        last_status_code=500 if status == DeliveryStatus.DEAD else None,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(delivery)
    db_session.commit()
    return delivery


def add_attempt(db_session: Session, delivery: Delivery, attempt_number: int) -> None:
    db_session.add(
        DeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            status_code=500,
            error=None,
            duration_ms=10 * attempt_number,
            response_excerpt="error " + str(attempt_number),
            attempted_at=START + timedelta(minutes=attempt_number),
        )
    )
    db_session.commit()


def list_ids(client: TestClient, headers: dict[str, str], **params: Any) -> list[str]:
    response = client.get(DELIVERIES_PATH, params=params, headers=headers)
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


def retry(client: TestClient, delivery_id: uuid.UUID, headers: dict[str, str]) -> Any:
    return client.post(DELIVERIES_PATH + "/" + str(delivery_id) + "/retry", headers=headers)


def load(db_session: Session, delivery_id: uuid.UUID) -> Delivery:
    db_session.expire_all()
    return db_session.get_one(Delivery, delivery_id)


@pytest.fixture
def deliveries_by_time(db_session: Session, owner: User, other: User) -> list[Delivery]:
    first_endpoint = add_endpoint(db_session, owner)
    second_endpoint = add_endpoint(db_session, owner, url="https://hooks.example.com/second")
    other_endpoint = add_endpoint(db_session, other)
    shared_event = add_event(db_session, owner)
    return [
        add_delivery(db_session, first_endpoint, shared_event, DeliveryStatus.SUCCEEDED, START),
        add_delivery(
            db_session,
            second_endpoint,
            shared_event,
            DeliveryStatus.DEAD,
            START + timedelta(minutes=10),
        ),
        add_delivery(
            db_session,
            first_endpoint,
            status=DeliveryStatus.FAILED,
            created_at=START + timedelta(minutes=20),
        ),
        add_delivery(
            db_session,
            other_endpoint,
            status=DeliveryStatus.DEAD,
            created_at=START + timedelta(minutes=30),
        ),
    ]


def ids_of(deliveries: list[Delivery]) -> list[str]:
    return [str(delivery.id) for delivery in deliveries]


def test_members_list_only_deliveries_of_their_own_endpoints_newest_first(
    client: TestClient, deliveries_by_time: list[Delivery]
) -> None:
    response = client.get(DELIVERIES_PATH, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == ids_of(deliveries_by_time[2::-1])
    newest = body["items"][0]
    assert set(newest) == {
        "id",
        "event_id",
        "endpoint_id",
        "status",
        "attempt_count",
        "next_attempt_at",
        "locked_until",
        "last_status_code",
        "last_error",
        "created_at",
        "updated_at",
    }
    assert newest["status"] == "failed"
    assert newest["attempt_count"] == 3
    assert newest["created_at"] == "2030-01-01T12:20:00Z"


def test_admins_list_deliveries_of_all_users(
    client: TestClient, deliveries_by_time: list[Delivery], admin: User
) -> None:
    ids = list_ids(client, auth_headers(client, ADMIN_EMAIL))

    assert ids == ids_of(deliveries_by_time[::-1])


def test_listing_is_paginated(client: TestClient, deliveries_by_time: list[Delivery]) -> None:
    headers = auth_headers(client, OWNER_EMAIL)

    response = client.get(DELIVERIES_PATH, params={"limit": 2, "offset": 1}, headers=headers)

    assert response.json()["total"] == 3
    assert response.json()["limit"] == 2
    assert response.json()["offset"] == 1
    assert [item["id"] for item in response.json()["items"]] == ids_of(
        [deliveries_by_time[1], deliveries_by_time[0]]
    )


def test_deliveries_created_at_the_same_time_are_ordered_by_id(
    client: TestClient, db_session: Session, owner: User
) -> None:
    endpoint = add_endpoint(db_session, owner)
    deliveries = [add_delivery(db_session, endpoint) for _ in range(5)]

    ids = list_ids(client, auth_headers(client, OWNER_EMAIL))

    assert ids == sorted(ids_of(deliveries))


def test_listing_filters_by_status(client: TestClient, deliveries_by_time: list[Delivery]) -> None:
    headers = auth_headers(client, OWNER_EMAIL)

    assert list_ids(client, headers, status="dead") == ids_of([deliveries_by_time[1]])
    assert list_ids(client, headers, status="succeeded") == ids_of([deliveries_by_time[0]])
    assert list_ids(client, headers, status="pending") == []


def test_listing_filters_by_endpoint_and_event(
    client: TestClient, deliveries_by_time: list[Delivery]
) -> None:
    headers = auth_headers(client, OWNER_EMAIL)
    first, second, third, _ = deliveries_by_time

    by_endpoint = list_ids(client, headers, endpoint_id=str(first.endpoint_id))
    by_event = list_ids(client, headers, event_id=str(first.event_id))
    both = list_ids(
        client, headers, endpoint_id=str(first.endpoint_id), event_id=str(first.event_id)
    )

    assert by_endpoint == ids_of([third, first])
    assert by_event == ids_of([second, first])
    assert both == ids_of([first])


def test_members_cannot_list_another_users_deliveries_by_filter(
    client: TestClient, deliveries_by_time: list[Delivery]
) -> None:
    others = deliveries_by_time[3]
    headers = auth_headers(client, OWNER_EMAIL)

    assert list_ids(client, headers, endpoint_id=str(others.endpoint_id)) == []
    assert list_ids(client, headers, event_id=str(others.event_id)) == []


def test_listing_filters_by_creation_time(
    client: TestClient, deliveries_by_time: list[Delivery]
) -> None:
    headers = auth_headers(client, OWNER_EMAIL)
    ten_past = (START + timedelta(minutes=10)).isoformat()
    twenty_past = (START + timedelta(minutes=20)).isoformat()

    assert list_ids(client, headers, created_after=ten_past) == ids_of(deliveries_by_time[2:0:-1])
    assert list_ids(client, headers, created_before=ten_past) == ids_of([deliveries_by_time[0]])
    assert list_ids(client, headers, created_after=ten_past, created_before=twenty_past) == ids_of(
        [deliveries_by_time[1]]
    )


@pytest.mark.parametrize("minutes", [0, -1])
def test_created_before_must_be_after_created_after(
    client: TestClient, owner: User, minutes: int
) -> None:
    params = {
        "created_after": START.isoformat(),
        "created_before": (START + timedelta(minutes=minutes)).isoformat(),
    }

    response = client.get(DELIVERIES_PATH, params=params, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"field": "created_before", "message": "must be after created_after"}
    ]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"status": "unknown"}, "status"),
        ({"status": "PENDING"}, "status"),
        ({"endpoint_id": "not-a-uuid"}, "endpoint_id"),
        ({"event_id": "42"}, "event_id"),
        ({"created_after": "yesterday"}, "created_after"),
        ({"created_before": "2030-01-01T12:00:00"}, "created_before"),
        ({"limit": 101}, "limit"),
        ({"offset": -1}, "offset"),
    ],
)
def test_listing_rejects_invalid_query_parameters(
    client: TestClient, owner: User, params: dict[str, Any], field: str
) -> None:
    response = client.get(DELIVERIES_PATH, params=params, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    assert [error["field"] for error in response.json()["errors"]] == [field]


def test_delivery_details_include_endpoint_url_event_type_and_ordered_attempts(
    client: TestClient, db_session: Session, owner: User
) -> None:
    endpoint = add_endpoint(db_session, owner, url="https://hooks.example.com/orders")
    event = add_event(db_session, owner, "order.paid")
    delivery = add_delivery(db_session, endpoint, event, DeliveryStatus.DEAD)
    for attempt_number in [2, 3, 1]:
        add_attempt(db_session, delivery, attempt_number)

    response = client.get(
        DELIVERIES_PATH + "/" + str(delivery.id), headers=auth_headers(client, OWNER_EMAIL)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(delivery.id)
    assert body["event_id"] == str(event.id)
    assert body["endpoint_id"] == str(endpoint.id)
    assert body["endpoint_url"] == "https://hooks.example.com/orders"
    assert body["event_type"] == "order.paid"
    assert body["status"] == "dead"
    assert body["last_status_code"] == 500
    assert [attempt["attempt_number"] for attempt in body["attempts"]] == [1, 2, 3]
    assert body["attempts"][0] == {
        "attempt_number": 1,
        "status_code": 500,
        "error": None,
        "duration_ms": 10,
        "response_excerpt": "error 1",
        "attempted_at": "2030-01-01T12:01:00Z",
    }
    assert "secret" not in body
    assert "payload" not in body


def test_delivery_without_attempts_has_an_empty_attempt_list(
    client: TestClient, db_session: Session, owner: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner))

    response = client.get(
        DELIVERIES_PATH + "/" + str(delivery.id), headers=auth_headers(client, OWNER_EMAIL)
    )

    assert response.status_code == 200
    assert response.json()["attempts"] == []


def test_members_get_404_for_deliveries_of_other_users(
    client: TestClient, db_session: Session, owner: User, other: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, other))

    response = client.get(
        DELIVERIES_PATH + "/" + str(delivery.id), headers=auth_headers(client, OWNER_EMAIL)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Delivery not found."


def test_admins_can_read_deliveries_of_other_users(
    client: TestClient, db_session: Session, other: User, admin: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, other))

    response = client.get(
        DELIVERIES_PATH + "/" + str(delivery.id), headers=auth_headers(client, ADMIN_EMAIL)
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(delivery.id)


def test_unknown_delivery_returns_404(client: TestClient, owner: User) -> None:
    path = DELIVERIES_PATH + "/" + str(uuid.uuid4())

    response = client.get(path, headers=auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 404


@pytest.mark.parametrize("status", [DeliveryStatus.DEAD, DeliveryStatus.FAILED])
def test_retry_requeues_dead_and_failed_deliveries_and_keeps_attempts(
    client: TestClient, db_session: Session, owner: User, status: DeliveryStatus
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner), status=status)
    for attempt_number in [1, 2, 3]:
        add_attempt(db_session, delivery, attempt_number)
    headers = auth_headers(client, OWNER_EMAIL)
    client.app.dependency_overrides[get_now] = lambda: RETRY_TIME

    response = retry(client, delivery.id, headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(delivery.id)
    assert body["status"] == "pending"
    assert body["attempt_count"] == 0
    assert body["next_attempt_at"] == "2030-01-02T08:30:00Z"
    assert body["locked_until"] is None
    assert body["updated_at"] == "2030-01-02T08:30:00Z"
    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.PENDING
    assert stored.attempt_count == 0
    assert stored.next_attempt_at == RETRY_TIME
    assert stored.locked_until is None
    attempts = db_session.scalars(
        select(DeliveryAttempt.attempt_number).where(DeliveryAttempt.delivery_id == delivery.id)
    ).all()
    assert sorted(attempts) == [1, 2, 3]


@pytest.mark.parametrize(
    "status", [DeliveryStatus.PENDING, DeliveryStatus.IN_PROGRESS, DeliveryStatus.SUCCEEDED]
)
def test_retry_of_other_statuses_returns_409_and_changes_nothing(
    client: TestClient, db_session: Session, owner: User, status: DeliveryStatus
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner), status=status)

    response = retry(client, delivery.id, auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["detail"] == "Only failed or dead deliveries can be retried."
    stored = load(db_session, delivery.id)
    assert stored.status == status
    assert stored.next_attempt_at == delivery.next_attempt_at
    assert stored.locked_until == delivery.locked_until


def test_retry_on_a_disabled_endpoint_returns_409(
    client: TestClient, db_session: Session, owner: User
) -> None:
    endpoint = add_endpoint(db_session, owner, is_active=False)
    delivery = add_delivery(db_session, endpoint, status=DeliveryStatus.DEAD)

    response = retry(client, delivery.id, auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 409
    assert response.json()["detail"] == "The endpoint is disabled."
    assert load(db_session, delivery.id).status == DeliveryStatus.DEAD


def test_retry_of_another_users_delivery_returns_404(
    client: TestClient, db_session: Session, owner: User, other: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, other), status=DeliveryStatus.DEAD)

    response = retry(client, delivery.id, auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 404
    assert load(db_session, delivery.id).status == DeliveryStatus.DEAD


def test_retry_of_an_unknown_delivery_returns_404(client: TestClient, owner: User) -> None:
    response = retry(client, uuid.uuid4(), auth_headers(client, OWNER_EMAIL))

    assert response.status_code == 404


def test_admins_can_retry_deliveries_of_other_users(
    client: TestClient, db_session: Session, other: User, admin: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, other), status=DeliveryStatus.DEAD)

    response = retry(client, delivery.id, auth_headers(client, ADMIN_EMAIL))

    assert response.status_code == 200
    assert load(db_session, delivery.id).status == DeliveryStatus.PENDING


def test_second_retry_after_a_successful_one_returns_409(
    client: TestClient, db_session: Session, owner: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner), status=DeliveryStatus.DEAD)
    headers = auth_headers(client, OWNER_EMAIL)

    assert retry(client, delivery.id, headers).status_code == 200
    assert retry(client, delivery.id, headers).status_code == 409


def test_two_simultaneous_retries_give_one_200_and_one_409(
    client: TestClient, db_session: Session, owner: User
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner), status=DeliveryStatus.DEAD)
    headers = auth_headers(client, OWNER_EMAIL)
    barrier = threading.Barrier(2)
    status_codes: list[int] = []
    lock = threading.Lock()

    def send() -> None:
        barrier.wait()
        response = retry(client, delivery.id, headers)
        with lock:
            status_codes.append(response.status_code)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(status_codes) == [200, 409]
    assert load(db_session, delivery.id).status == DeliveryStatus.PENDING

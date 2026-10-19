import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hookline.clock import get_now
from hookline.deliveries.models import Delivery, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events.models import Event
from hookline.users.models import User, UserRole
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "other@example.com"
ADMIN_EMAIL = "admin@example.com"
STATS_PATH = "/api/v1/stats"
NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
EMPTY_STATS = {
    "deliveries_by_status": {
        "pending": 0,
        "in_progress": 0,
        "succeeded": 0,
        "failed": 0,
        "dead": 0,
    },
    "last_24_hours": {
        "events_received": 0,
        "deliveries_succeeded": 0,
        "deliveries_dead": 0,
        "success_rate": None,
    },
    "average_attempts_to_success": None,
    "endpoints": [],
}


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def other(db_session: Session) -> User:
    return add_user(db_session, OTHER_EMAIL)


@pytest.fixture
def admin(db_session: Session) -> User:
    return add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)


@pytest.fixture
def stats_client(client: TestClient) -> Iterator[TestClient]:
    yield client
    client.app.dependency_overrides.clear()


def add_endpoint(db_session: Session, user: User, url: str) -> Endpoint:
    endpoint = Endpoint(user_id=user.id, url=url, event_types=["*"], secret="whsec_test")
    db_session.add(endpoint)
    db_session.commit()
    return endpoint


def add_event(db_session: Session, user: User, created_at: datetime) -> Event:
    event = Event(user_id=user.id, event_type="order.created", payload={}, created_at=created_at)
    db_session.add(event)
    db_session.commit()
    return event


def add_delivery(
    db_session: Session,
    endpoint: Endpoint,
    event: Event,
    status: DeliveryStatus,
    updated_at: datetime,
    attempt_count: int = 1,
) -> Delivery:
    delivery = Delivery(
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=status,
        attempt_count=attempt_count,
        next_attempt_at=updated_at,
        created_at=updated_at - timedelta(minutes=5),
        updated_at=updated_at,
    )
    db_session.add(delivery)
    db_session.commit()
    return delivery


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def get_stats(client: TestClient, email: str, **params: Any) -> Any:
    headers = auth_headers(client, email)
    client.app.dependency_overrides[get_now] = lambda: NOW
    response = client.get(STATS_PATH, params=params, headers=headers)
    client.app.dependency_overrides.pop(get_now)
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def owner_data(db_session: Session, owner: User) -> dict[str, Endpoint]:
    first = add_endpoint(db_session, owner, "https://hooks.example.com/first")
    second = add_endpoint(db_session, owner, "https://hooks.example.com/second")
    recent_event = add_event(db_session, owner, hours_ago(1))
    second_recent_event = add_event(db_session, owner, hours_ago(4))
    old_event = add_event(db_session, owner, hours_ago(30))
    add_event(db_session, owner, hours_ago(2))
    add_delivery(db_session, first, recent_event, DeliveryStatus.SUCCEEDED, hours_ago(0.5), 1)
    add_delivery(db_session, first, second_recent_event, DeliveryStatus.SUCCEEDED, hours_ago(2), 2)
    add_delivery(db_session, first, old_event, DeliveryStatus.DEAD, hours_ago(3), 8)
    add_delivery(db_session, second, old_event, DeliveryStatus.SUCCEEDED, hours_ago(29), 5)
    add_delivery(db_session, second, recent_event, DeliveryStatus.DEAD, hours_ago(5), 8)
    add_delivery(db_session, second, second_recent_event, DeliveryStatus.DEAD, hours_ago(24), 8)
    pending_event = add_event(db_session, owner, hours_ago(30))
    add_delivery(db_session, first, pending_event, DeliveryStatus.FAILED, hours_ago(1), 2)
    add_delivery(db_session, second, pending_event, DeliveryStatus.PENDING, hours_ago(30), 0)
    in_progress_event = add_event(db_session, owner, hours_ago(40))
    add_delivery(db_session, first, in_progress_event, DeliveryStatus.IN_PROGRESS, hours_ago(1), 0)
    return {"first": first, "second": second}


@pytest.fixture
def other_data(db_session: Session, other: User) -> Endpoint:
    endpoint = add_endpoint(db_session, other, "https://other.example.com/hook")
    event = add_event(db_session, other, hours_ago(1))
    add_delivery(db_session, endpoint, event, DeliveryStatus.DEAD, hours_ago(1), 8)
    second_event = add_event(db_session, other, hours_ago(2))
    add_delivery(db_session, endpoint, second_event, DeliveryStatus.SUCCEEDED, hours_ago(2), 4)
    return endpoint


def test_empty_database_returns_zeros_and_nulls(stats_client: TestClient, owner: User) -> None:
    assert get_stats(stats_client, OWNER_EMAIL) == EMPTY_STATS


def test_endpoint_without_deliveries_is_listed_with_zero_counts(
    stats_client: TestClient, db_session: Session, owner: User
) -> None:
    endpoint = add_endpoint(db_session, owner, "https://hooks.example.com/quiet")

    stats = get_stats(stats_client, OWNER_EMAIL)

    assert stats["endpoints"] == [
        {"id": str(endpoint.id), "url": endpoint.url, "succeeded": 0, "dead": 0}
    ]
    assert stats["last_24_hours"]["success_rate"] is None
    assert stats["average_attempts_to_success"] is None


def test_known_fixtures_give_the_expected_numbers(
    stats_client: TestClient, owner_data: dict[str, Endpoint], other_data: Endpoint
) -> None:
    first = owner_data["first"]
    second = owner_data["second"]

    stats = get_stats(stats_client, OWNER_EMAIL)

    assert stats == {
        "deliveries_by_status": {
            "pending": 1,
            "in_progress": 1,
            "succeeded": 3,
            "failed": 1,
            "dead": 3,
        },
        "last_24_hours": {
            "events_received": 3,
            "deliveries_succeeded": 2,
            "deliveries_dead": 3,
            "success_rate": 0.4,
        },
        "average_attempts_to_success": 1.5,
        "endpoints": [
            {"id": str(second.id), "url": second.url, "succeeded": 0, "dead": 2},
            {"id": str(first.id), "url": first.url, "succeeded": 2, "dead": 1},
        ],
    }


def test_members_see_only_their_own_data(
    stats_client: TestClient, owner_data: dict[str, Endpoint], other_data: Endpoint
) -> None:
    stats = get_stats(stats_client, OTHER_EMAIL)

    assert stats == {
        "deliveries_by_status": {
            "pending": 0,
            "in_progress": 0,
            "succeeded": 1,
            "failed": 0,
            "dead": 1,
        },
        "last_24_hours": {
            "events_received": 2,
            "deliveries_succeeded": 1,
            "deliveries_dead": 1,
            "success_rate": 0.5,
        },
        "average_attempts_to_success": 4.0,
        "endpoints": [
            {"id": str(other_data.id), "url": other_data.url, "succeeded": 1, "dead": 1},
        ],
    }


def test_admins_see_data_of_all_users(
    stats_client: TestClient,
    admin: User,
    owner_data: dict[str, Endpoint],
    other_data: Endpoint,
) -> None:
    stats = get_stats(stats_client, ADMIN_EMAIL)

    assert stats["deliveries_by_status"] == {
        "pending": 1,
        "in_progress": 1,
        "succeeded": 4,
        "failed": 1,
        "dead": 4,
    }
    assert stats["last_24_hours"] == {
        "events_received": 5,
        "deliveries_succeeded": 3,
        "deliveries_dead": 4,
        "success_rate": 0.4286,
    }
    assert stats["average_attempts_to_success"] == 2.33
    assert [endpoint["id"] for endpoint in stats["endpoints"]] == [
        str(owner_data["second"].id),
        *sorted([str(owner_data["first"].id), str(other_data.id)]),
    ]


def test_endpoint_filter_limits_every_number_to_that_endpoint(
    stats_client: TestClient, owner_data: dict[str, Endpoint], other_data: Endpoint
) -> None:
    first = owner_data["first"]

    stats = get_stats(stats_client, OWNER_EMAIL, endpoint_id=str(first.id))

    assert stats == {
        "deliveries_by_status": {
            "pending": 0,
            "in_progress": 1,
            "succeeded": 2,
            "failed": 1,
            "dead": 1,
        },
        "last_24_hours": {
            "events_received": 2,
            "deliveries_succeeded": 2,
            "deliveries_dead": 1,
            "success_rate": 0.6667,
        },
        "average_attempts_to_success": 1.5,
        "endpoints": [{"id": str(first.id), "url": first.url, "succeeded": 2, "dead": 1}],
    }


def test_admins_can_filter_by_any_endpoint(
    stats_client: TestClient,
    admin: User,
    owner_data: dict[str, Endpoint],
    other_data: Endpoint,
) -> None:
    stats = get_stats(stats_client, ADMIN_EMAIL, endpoint_id=str(other_data.id))

    assert stats["last_24_hours"]["deliveries_dead"] == 1
    assert stats["endpoints"] == [
        {"id": str(other_data.id), "url": other_data.url, "succeeded": 1, "dead": 1}
    ]


def test_members_get_empty_stats_for_another_users_endpoint(
    stats_client: TestClient, owner_data: dict[str, Endpoint], other_data: Endpoint
) -> None:
    stats = get_stats(stats_client, OWNER_EMAIL, endpoint_id=str(other_data.id))

    assert stats == EMPTY_STATS


def test_unknown_endpoint_filter_gives_empty_stats(stats_client: TestClient, owner: User) -> None:
    assert get_stats(stats_client, OWNER_EMAIL, endpoint_id=str(uuid.uuid4())) == EMPTY_STATS


def test_endpoint_list_is_limited_to_50_ordered_by_dead_count_then_id(
    stats_client: TestClient, db_session: Session, owner: User
) -> None:
    endpoints = [
        add_endpoint(db_session, owner, "https://hooks.example.com/" + str(number))
        for number in range(52)
    ]
    event = add_event(db_session, owner, hours_ago(1))
    add_delivery(db_session, endpoints[10], event, DeliveryStatus.DEAD, hours_ago(1), 8)
    add_delivery(db_session, endpoints[20], event, DeliveryStatus.DEAD, hours_ago(2), 8)
    second_event = add_event(db_session, owner, hours_ago(1))
    add_delivery(db_session, endpoints[20], second_event, DeliveryStatus.DEAD, hours_ago(2), 8)

    listed = get_stats(stats_client, OWNER_EMAIL)["endpoints"]

    without_dead = sorted(
        str(endpoint.id) for index, endpoint in enumerate(endpoints) if index not in (10, 20)
    )
    assert len(listed) == 50
    assert [item["id"] for item in listed] == [
        str(endpoints[20].id),
        str(endpoints[10].id),
        *without_dead[:48],
    ]
    assert [item["dead"] for item in listed[:3]] == [2, 1, 0]


def test_invalid_endpoint_filter_returns_400(stats_client: TestClient, owner: User) -> None:
    response = stats_client.get(
        STATS_PATH, params={"endpoint_id": "abc"}, headers=auth_headers(stats_client, OWNER_EMAIL)
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "endpoint_id"

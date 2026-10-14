import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events.models import Event
from hookline.users.models import RefreshToken, User, UserRole

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def add_user(session: Session, email: str = "member@example.com", role: str = "member") -> User:
    user = User(email=email, password_hash="hash", role=role)
    session.add(user)
    session.flush()
    return user


def add_api_key(session: Session, user: User, key_hash: str = "a" * 64) -> ApiKey:
    api_key = ApiKey(user_id=user.id, name="producer", prefix="hk_abcdefgh", key_hash=key_hash)
    session.add(api_key)
    session.flush()
    return api_key


def add_endpoint(session: Session, user: User, event_types: list[str] | None = None) -> Endpoint:
    if event_types is None:
        event_types = ["order.created"]
    endpoint = Endpoint(
        user_id=user.id,
        url="https://receiver.example.com/hooks",
        event_types=event_types,
        secret="s" * 64,
    )
    session.add(endpoint)
    session.flush()
    return endpoint


def add_event(
    session: Session,
    user: User,
    api_key: ApiKey | None = None,
    idempotency_key: str | None = None,
    payload: Any = None,
) -> Event:
    if payload is None:
        payload = {"order_id": 1}
    event = Event(
        user_id=user.id,
        api_key_id=api_key.id if api_key else None,
        event_type="order.created",
        payload=payload,
        idempotency_key=idempotency_key,
    )
    session.add(event)
    session.flush()
    return event


def add_delivery(
    session: Session,
    event: Event,
    endpoint: Endpoint,
    status: str = "pending",
    attempt_count: int = 0,
) -> Delivery:
    delivery = Delivery(
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=status,
        attempt_count=attempt_count,
        next_attempt_at=NOW,
    )
    session.add(delivery)
    session.flush()
    return delivery


def add_attempt(
    session: Session, delivery: Delivery, attempt_number: int = 1, duration_ms: int = 25
) -> DeliveryAttempt:
    attempt = DeliveryAttempt(
        delivery_id=delivery.id,
        attempt_number=attempt_number,
        status_code=200,
        duration_ms=duration_ms,
        attempted_at=NOW,
    )
    session.add(attempt)
    session.flush()
    return attempt


def add_delivery_for_new_event(session: Session, status: str = "pending") -> Delivery:
    user = add_user(session)
    return add_delivery(session, add_event(session, user), add_endpoint(session, user), status)


def violated_constraint(error: IntegrityError) -> str | None:
    return error.orig.diag.constraint_name if error.orig is not None else None


def count_rows(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_each_table_accepts_a_valid_row(db_session: Session) -> None:
    user = add_user(db_session)
    token = RefreshToken(user_id=user.id, token_hash="t" * 64, expires_at=NOW)
    db_session.add(token)
    api_key = add_api_key(db_session, user)
    endpoint = add_endpoint(db_session, user)
    event = add_event(db_session, user, api_key)
    delivery = add_delivery(db_session, event, endpoint)
    attempt = add_attempt(db_session, delivery)
    db_session.commit()

    for row in (user, token, api_key, endpoint, event, delivery, attempt):
        db_session.refresh(row)
        assert isinstance(row.id, uuid.UUID)
    assert user.is_active is True
    assert user.created_at.tzinfo is not None
    assert endpoint.is_active is True
    assert endpoint.event_types == ["order.created"]
    assert event.payload == {"order_id": 1}
    assert delivery.attempt_count == 0
    assert delivery.updated_at is not None


@pytest.mark.parametrize("role", list(UserRole))
def test_users_accept_every_known_role(db_session: Session, role: UserRole) -> None:
    user = add_user(db_session, role=role)

    assert user.role == role.value


def test_users_reject_unknown_role(db_session: Session) -> None:
    with pytest.raises(IntegrityError) as error:
        add_user(db_session, role="owner")

    assert violated_constraint(error.value) == "ck_users_role"


def test_user_email_uniqueness_ignores_case(db_session: Session) -> None:
    add_user(db_session, email="A@x.com")

    with pytest.raises(IntegrityError) as error:
        add_user(db_session, email="a@x.com")

    assert violated_constraint(error.value) == "uq_users_email_lower"


@pytest.mark.parametrize("status", list(DeliveryStatus))
def test_deliveries_accept_every_known_status(db_session: Session, status: DeliveryStatus) -> None:
    delivery = add_delivery_for_new_event(db_session, status=status)

    assert delivery.status == status.value


def test_deliveries_reject_unknown_status(db_session: Session) -> None:
    with pytest.raises(IntegrityError) as error:
        add_delivery_for_new_event(db_session, status="cancelled")

    assert violated_constraint(error.value) == "ck_deliveries_status"


def test_deliveries_reject_negative_attempt_count(db_session: Session) -> None:
    user = add_user(db_session)
    event = add_event(db_session, user)
    endpoint = add_endpoint(db_session, user)

    with pytest.raises(IntegrityError) as error:
        add_delivery(db_session, event, endpoint, attempt_count=-1)

    assert violated_constraint(error.value) == "ck_deliveries_attempt_count_not_negative"


def test_deliveries_reject_a_second_delivery_for_the_same_event_and_endpoint(
    db_session: Session,
) -> None:
    user = add_user(db_session)
    event = add_event(db_session, user)
    endpoint = add_endpoint(db_session, user)
    add_delivery(db_session, event, endpoint)

    with pytest.raises(IntegrityError) as error:
        add_delivery(db_session, event, endpoint)

    assert violated_constraint(error.value) == "uq_deliveries_event_id_endpoint_id"


@pytest.mark.parametrize("event_types", [[], [f"type.{number}" for number in range(51)]])
def test_endpoints_reject_event_type_count_outside_one_to_fifty(
    db_session: Session, event_types: list[str]
) -> None:
    user = add_user(db_session)

    with pytest.raises(IntegrityError) as error:
        add_endpoint(db_session, user, event_types=event_types)

    assert violated_constraint(error.value) == "ck_endpoints_event_types_count"


def test_endpoints_accept_fifty_event_types(db_session: Session) -> None:
    user = add_user(db_session)
    event_types = [f"type.{number}" for number in range(50)]

    endpoint = add_endpoint(db_session, user, event_types=event_types)

    assert len(endpoint.event_types) == 50


@pytest.mark.parametrize("payload", [[1, 2], "text", 5, True])
def test_events_reject_payload_that_is_not_an_object(db_session: Session, payload: Any) -> None:
    user = add_user(db_session)

    with pytest.raises(IntegrityError) as error:
        add_event(db_session, user, payload=payload)

    assert violated_constraint(error.value) == "ck_events_payload_is_object"


def test_events_reject_a_reused_idempotency_key_for_the_same_user(db_session: Session) -> None:
    user = add_user(db_session)
    add_event(db_session, user, idempotency_key="order-1")

    with pytest.raises(IntegrityError) as error:
        add_event(db_session, user, idempotency_key="order-1")

    assert violated_constraint(error.value) == "events_idempotency_uk"


def test_events_allow_the_same_idempotency_key_for_different_users(db_session: Session) -> None:
    first_user = add_user(db_session, email="first@example.com")
    second_user = add_user(db_session, email="second@example.com")

    add_event(db_session, first_user, idempotency_key="order-1")
    add_event(db_session, second_user, idempotency_key="order-1")

    assert count_rows(db_session, Event) == 2


def test_events_allow_many_events_without_idempotency_key(db_session: Session) -> None:
    user = add_user(db_session)

    add_event(db_session, user)
    add_event(db_session, user)

    assert count_rows(db_session, Event) == 2


def test_delivery_attempts_reject_attempt_number_zero(db_session: Session) -> None:
    delivery = add_delivery_for_new_event(db_session)

    with pytest.raises(IntegrityError) as error:
        add_attempt(db_session, delivery, attempt_number=0)

    assert violated_constraint(error.value) == "ck_delivery_attempts_attempt_number_positive"


def test_delivery_attempts_reject_negative_duration(db_session: Session) -> None:
    delivery = add_delivery_for_new_event(db_session)

    with pytest.raises(IntegrityError) as error:
        add_attempt(db_session, delivery, duration_ms=-1)

    assert violated_constraint(error.value) == "ck_delivery_attempts_duration_ms_not_negative"


def test_delivery_attempts_reject_a_repeated_attempt_number(db_session: Session) -> None:
    delivery = add_delivery_for_new_event(db_session)
    add_attempt(db_session, delivery, attempt_number=1)

    with pytest.raises(IntegrityError) as error:
        add_attempt(db_session, delivery, attempt_number=1)

    assert violated_constraint(error.value) == "uq_delivery_attempts_delivery_id_attempt_number"


def test_delivery_attempts_are_loaded_in_attempt_number_order(db_session: Session) -> None:
    delivery = add_delivery_for_new_event(db_session)
    for attempt_number in (3, 1, 2):
        add_attempt(db_session, delivery, attempt_number=attempt_number)
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.get_one(Delivery, delivery.id)

    assert [attempt.attempt_number for attempt in loaded.attempts] == [1, 2, 3]


def test_deleting_a_user_cascades_to_their_rows(db_session: Session) -> None:
    user = add_user(db_session)
    db_session.add(RefreshToken(user_id=user.id, token_hash="t" * 64, expires_at=NOW))
    api_key = add_api_key(db_session, user)
    endpoint = add_endpoint(db_session, user)
    event = add_event(db_session, user, api_key)
    add_attempt(db_session, add_delivery(db_session, event, endpoint))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    for model in (RefreshToken, ApiKey, Endpoint, Event, Delivery, DeliveryAttempt):
        assert count_rows(db_session, model) == 0


def test_deleting_an_api_key_keeps_its_events_without_the_key(db_session: Session) -> None:
    user = add_user(db_session)
    api_key = add_api_key(db_session, user)
    event = add_event(db_session, user, api_key)
    db_session.commit()

    db_session.delete(api_key)
    db_session.commit()
    db_session.refresh(event)

    assert event.api_key_id is None
    assert count_rows(db_session, Event) == 1

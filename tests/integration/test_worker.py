import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from hookline.config import Settings
from hookline.database import create_session_factory
from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.deliveries.signing import verify_signature
from hookline.endpoints.models import Endpoint
from hookline.endpoints.url_safety import get_resolver
from hookline.events.models import Event
from hookline.users.models import User
from hookline.worker.claims import ClaimedDelivery, claim_due_deliveries
from hookline.worker.runner import process_claimed, run_once, run_worker
from tests.helpers import add_user, auth_headers

pytestmark = pytest.mark.integration

OWNER_EMAIL = "owner@example.com"
NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
TARGET_URL = "https://hooks.example.com/webhook"
UNSAFE_URL = "https://internal.example.com/webhook"
SECRET = "whsec_worker-test-secret"
PAYLOAD = {"order_id": 42, "card_number": "4111-1111-1111-1111"}
LEASE_SECONDS = 60

FAKE_DNS = {
    "hooks.example.com": "93.184.215.14",
    "internal.example.com": "10.0.0.7",
}

Handler = Callable[[httpx2.Request], httpx2.Response]


def fake_resolver(host: str, port: int | None) -> Sequence[tuple[Any, ...]]:
    if host not in FAKE_DNS:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (FAKE_DNS[host], 0))]


@pytest.fixture
def worker_settings(database_url: str) -> Settings:
    return Settings(database_url=database_url, max_attempts=3)


@pytest.fixture
def session_factory(db_engine: Engine, clean_database: None) -> sessionmaker[Session]:
    return create_session_factory(db_engine)


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, OWNER_EMAIL)


@pytest.fixture
def endpoint(db_session: Session, owner: User) -> Endpoint:
    return add_endpoint(db_session, owner)


def add_endpoint(
    db_session: Session, user: User, url: str = TARGET_URL, is_active: bool = True
) -> Endpoint:
    endpoint = Endpoint(
        user_id=user.id,
        url=url,
        event_types=["order.created"],
        secret=SECRET,
        is_active=is_active,
    )
    db_session.add(endpoint)
    db_session.commit()
    return endpoint


def add_delivery(
    db_session: Session,
    endpoint: Endpoint,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    next_attempt_at: datetime = NOW,
    locked_until: datetime | None = None,
) -> Delivery:
    event = Event(
        user_id=endpoint.user_id,
        event_type="order.created",
        payload=PAYLOAD,
        created_at=NOW - timedelta(minutes=1),
    )
    db_session.add(event)
    db_session.flush()
    delivery = Delivery(
        event_id=event.id,
        endpoint_id=endpoint.id,
        status=status,
        next_attempt_at=next_attempt_at,
        locked_until=locked_until,
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
            duration_ms=5,
            attempted_at=NOW - timedelta(hours=1),
        )
    )
    db_session.commit()


def receiver(handler: Handler, received: list[httpx2.Request]) -> httpx2.Client:
    def recording_handler(request: httpx2.Request) -> httpx2.Response:
        received.append(request)
        return handler(request)

    return httpx2.Client(transport=httpx2.MockTransport(recording_handler))


def answer(status_code: int) -> Handler:
    return lambda request: httpx2.Response(status_code, text="answer " + str(status_code))


def claim(
    session_factory: sessionmaker[Session], now: datetime, batch_size: int = 10
) -> list[ClaimedDelivery]:
    with session_factory() as session:
        return claim_due_deliveries(session, now, batch_size, LEASE_SECONDS)


def process(
    session_factory: sessionmaker[Session],
    client: httpx2.Client,
    claimed: ClaimedDelivery,
    settings: Settings,
    now: datetime,
) -> None:
    process_claimed(
        session_factory, client, claimed, settings, lambda: now, lambda: 0.5, fake_resolver
    )


def load(db_session: Session, delivery_id: uuid.UUID) -> Delivery:
    db_session.expire_all()
    delivery = db_session.get(Delivery, delivery_id)
    assert delivery is not None
    return delivery


def attempts_of(db_session: Session, delivery_id: uuid.UUID) -> list[DeliveryAttempt]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.delivery_id == delivery_id)
            .order_by(DeliveryAttempt.attempt_number)
        )
    )


def test_claim_returns_plain_data_and_starts_a_lease(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    delivery = add_delivery(db_session, endpoint)

    claimed = claim(session_factory, NOW)

    assert claimed == [
        ClaimedDelivery(
            delivery_id=delivery.id,
            attempt_number=1,
            attempt_count=0,
            locked_until=NOW + timedelta(seconds=LEASE_SECONDS),
            url=TARGET_URL,
            secret=SECRET,
            event_id=delivery.event_id,
            event_type="order.created",
            event_created_at=NOW - timedelta(minutes=1),
            payload=PAYLOAD,
        )
    ]
    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.IN_PROGRESS
    assert stored.locked_until == NOW + timedelta(seconds=LEASE_SECONDS)
    assert stored.attempt_count == 0


def test_pending_delivery_to_a_2xx_receiver_succeeds_with_one_attempt(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)
    received: list[httpx2.Request] = []

    [claimed] = claim(session_factory, NOW)
    process(session_factory, receiver(answer(200), received), claimed, worker_settings, NOW)

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.SUCCEEDED
    assert stored.attempt_count == 1
    assert stored.last_status_code == 200
    assert stored.last_error is None
    assert stored.locked_until is None
    [attempt] = attempts_of(db_session, delivery.id)
    assert attempt.attempt_number == 1
    assert attempt.status_code == 200
    assert attempt.error is None
    assert attempt.response_excerpt == "answer 200"
    assert attempt.duration_ms >= 0
    assert attempt.attempted_at == NOW
    assert len(received) == 1


def test_5xx_receiver_makes_the_delivery_failed_with_a_backoff(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)

    [claimed] = claim(session_factory, NOW)
    process(session_factory, receiver(answer(500), []), claimed, worker_settings, NOW)

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.FAILED
    assert stored.next_attempt_at == NOW + timedelta(seconds=7.5)
    assert stored.attempt_count == 1
    assert stored.last_status_code == 500
    assert stored.locked_until is None
    [attempt] = attempts_of(db_session, delivery.id)
    assert attempt.status_code == 500


def test_connection_error_is_recorded_as_a_failed_attempt(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    [claimed] = claim(session_factory, NOW)
    process(session_factory, receiver(refuse, []), claimed, worker_settings, NOW)

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.FAILED
    assert stored.last_status_code is None
    assert stored.last_error == "connection error"
    [attempt] = attempts_of(db_session, delivery.id)
    assert attempt.error == "connection error"


def test_delivery_becomes_dead_after_max_attempts_failures(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)
    received: list[httpx2.Request] = []
    client = receiver(answer(503), received)
    now = NOW

    for _ in range(worker_settings.max_attempts):
        [claimed] = claim(session_factory, now)
        process(session_factory, client, claimed, worker_settings, now)
        now = load(db_session, delivery.id).next_attempt_at

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.DEAD
    assert stored.attempt_count == 3
    assert stored.last_status_code == 503
    assert stored.locked_until is None
    assert [attempt.attempt_number for attempt in attempts_of(db_session, delivery.id)] == [1, 2, 3]
    assert [request.headers["Hookline-Attempt"] for request in received] == ["1", "2", "3"]
    assert claim(session_factory, NOW + timedelta(days=1)) == []


def test_failed_attempts_wait_longer_each_time(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    database_url: str,
) -> None:
    settings = Settings(database_url=database_url, max_attempts=5)
    delivery = add_delivery(db_session, endpoint)
    client = receiver(answer(500), [])
    now = NOW
    delays = []

    for _ in range(3):
        [claimed] = claim(session_factory, now)
        process(session_factory, client, claimed, settings, now)
        next_attempt_at = load(db_session, delivery.id).next_attempt_at
        delays.append((next_attempt_at - now).total_seconds())
        now = next_attempt_at

    assert delays == [7.5, 15, 30]


def test_attempt_number_follows_the_highest_existing_attempt(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    delivery = add_delivery(db_session, endpoint, status=DeliveryStatus.FAILED)
    add_attempt(db_session, delivery, 1)
    add_attempt(db_session, delivery, 2)

    [claimed] = claim(session_factory, NOW)

    assert claimed.attempt_number == 3


def test_delivery_due_in_the_future_is_not_claimed(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    delivery = add_delivery(db_session, endpoint, next_attempt_at=NOW + timedelta(seconds=1))

    assert claim(session_factory, NOW) == []
    assert load(db_session, delivery.id).status == DeliveryStatus.PENDING
    assert [item.delivery_id for item in claim(session_factory, NOW + timedelta(seconds=1))] == [
        delivery.id
    ]


@pytest.mark.parametrize("status", [DeliveryStatus.SUCCEEDED, DeliveryStatus.DEAD])
def test_finished_deliveries_are_not_claimed(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    status: DeliveryStatus,
) -> None:
    add_delivery(db_session, endpoint, status=status, next_attempt_at=NOW - timedelta(hours=1))

    assert claim(session_factory, NOW) == []


def test_in_progress_delivery_with_an_expired_lease_is_claimed_again(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    delivery = add_delivery(
        db_session,
        endpoint,
        status=DeliveryStatus.IN_PROGRESS,
        next_attempt_at=NOW - timedelta(minutes=5),
        locked_until=NOW - timedelta(seconds=1),
    )

    [claimed] = claim(session_factory, NOW)

    assert claimed.delivery_id == delivery.id
    assert claimed.attempt_number == 1
    assert load(db_session, delivery.id).locked_until == NOW + timedelta(seconds=LEASE_SECONDS)


def test_in_progress_delivery_with_a_valid_lease_is_not_claimed(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    add_delivery(
        db_session,
        endpoint,
        status=DeliveryStatus.IN_PROGRESS,
        next_attempt_at=NOW - timedelta(minutes=5),
        locked_until=NOW,
    )

    assert claim(session_factory, NOW) == []


def test_claim_takes_the_oldest_due_deliveries_up_to_the_batch_size(
    db_session: Session, endpoint: Endpoint, session_factory: sessionmaker[Session]
) -> None:
    deliveries = [
        add_delivery(db_session, endpoint, next_attempt_at=NOW - timedelta(seconds=seconds))
        for seconds in [10, 30, 20]
    ]

    claimed = claim(session_factory, NOW, batch_size=2)

    assert [item.delivery_id for item in claimed] == [deliveries[1].id, deliveries[2].id]
    assert load(db_session, deliveries[0].id).status == DeliveryStatus.PENDING


def test_stale_worker_cannot_overwrite_a_newer_result(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    delivery = add_delivery(db_session, endpoint)
    [stale_claim] = claim(session_factory, NOW)
    later = NOW + timedelta(seconds=LEASE_SECONDS + 1)
    [new_claim] = claim(session_factory, later)
    assert new_claim.attempt_number == stale_claim.attempt_number

    process(session_factory, receiver(answer(200), []), new_claim, worker_settings, later)
    with caplog.at_level(logging.WARNING, logger="hookline.worker.runner"):
        process(session_factory, receiver(answer(500), []), stale_claim, worker_settings, later)

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.SUCCEEDED
    assert stored.attempt_count == 1
    assert stored.last_status_code == 200
    [attempt] = attempts_of(db_session, delivery.id)
    assert attempt.status_code == 200
    assert "lease was taken over" in caplog.text


def test_stale_worker_cannot_record_while_the_new_lease_is_active(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)
    [stale_claim] = claim(session_factory, NOW)
    later = NOW + timedelta(seconds=LEASE_SECONDS + 1)
    [new_claim] = claim(session_factory, later)

    process(session_factory, receiver(answer(200), []), stale_claim, worker_settings, later)

    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.IN_PROGRESS
    assert stored.locked_until == new_claim.locked_until
    assert stored.attempt_count == 0
    assert attempts_of(db_session, delivery.id) == []


def test_delivery_to_an_inactive_endpoint_becomes_dead(
    db_session: Session, owner: User, session_factory: sessionmaker[Session]
) -> None:
    inactive = add_endpoint(db_session, owner, is_active=False)
    active = add_endpoint(db_session, owner)
    disabled_delivery = add_delivery(db_session, inactive)
    active_delivery = add_delivery(db_session, active)

    claimed = claim(session_factory, NOW)

    assert [item.delivery_id for item in claimed] == [active_delivery.id]
    stored = load(db_session, disabled_delivery.id)
    assert stored.status == DeliveryStatus.DEAD
    assert stored.last_error == "endpoint disabled"
    assert stored.locked_until is None
    assert stored.attempt_count == 0
    assert attempts_of(db_session, disabled_delivery.id) == []


def test_unsafe_target_fails_without_sending_a_request(
    db_session: Session,
    owner: User,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, add_endpoint(db_session, owner, url=UNSAFE_URL))
    received: list[httpx2.Request] = []

    [claimed] = claim(session_factory, NOW)
    process(session_factory, receiver(answer(200), received), claimed, worker_settings, NOW)

    assert received == []
    stored = load(db_session, delivery.id)
    assert stored.status == DeliveryStatus.FAILED
    assert stored.last_error == "target address not allowed"
    [attempt] = attempts_of(db_session, delivery.id)
    assert attempt.error == "target address not allowed"
    assert attempt.status_code is None


def test_attempt_log_line_has_no_payload_or_secret(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    delivery = add_delivery(db_session, endpoint)

    [claimed] = claim(session_factory, NOW)
    with caplog.at_level(logging.INFO, logger="hookline"):
        process(session_factory, receiver(answer(204), []), claimed, worker_settings, NOW)

    assert f"Delivery {delivery.id} attempt 1 succeeded status_code=204 duration_ms=" in caplog.text
    assert SECRET not in caplog.text
    assert "4111" not in caplog.text
    assert "order_id" not in caplog.text


def test_concurrent_workers_claim_each_delivery_exactly_once(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery_ids = {add_delivery(db_session, endpoint).id for _ in range(50)}
    claimed_ids: list[uuid.UUID] = []
    errors: list[Exception] = []
    start = threading.Barrier(4)

    def work() -> None:
        client = receiver(answer(200), [])
        start.wait()
        try:
            while True:
                batch = claim(session_factory, NOW, batch_size=3)
                if not batch:
                    return
                for item in batch:
                    claimed_ids.append(item.delivery_id)
                    process(session_factory, client, item, worker_settings, NOW)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert len(claimed_ids) == 50
    assert set(claimed_ids) == delivery_ids
    attempt_counts = db_session.execute(
        select(DeliveryAttempt.delivery_id, func.count()).group_by(DeliveryAttempt.delivery_id)
    ).all()
    assert len(attempt_counts) == 50
    assert {count for _, count in attempt_counts} == {1}
    statuses = db_session.scalars(select(Delivery.status).distinct()).all()
    assert statuses == [DeliveryStatus.SUCCEEDED]


def test_run_worker_delivers_and_stops_when_the_stop_event_is_set(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    delivery = add_delivery(db_session, endpoint)
    stop_event = threading.Event()

    def answer_and_stop(request: httpx2.Request) -> httpx2.Response:
        stop_event.set()
        return httpx2.Response(200)

    run_worker(
        worker_settings,
        session_factory,
        receiver(answer_and_stop, []),
        stop_event,
        lambda: NOW,
        lambda: 0.5,
        fake_resolver,
    )

    assert load(db_session, delivery.id).status == DeliveryStatus.SUCCEEDED


def test_run_worker_waits_while_nothing_is_due_and_stops_on_request(
    session_factory: sessionmaker[Session], worker_settings: Settings
) -> None:
    stop_event = threading.Event()
    worker = threading.Thread(
        target=run_worker,
        args=(worker_settings, session_factory, receiver(answer(200), []), stop_event),
    )

    worker.start()
    stop_event.set()
    worker.join(timeout=10)

    assert not worker.is_alive()


def test_stop_request_finishes_the_current_delivery_and_leaves_the_rest_leased(
    db_session: Session,
    endpoint: Endpoint,
    session_factory: sessionmaker[Session],
    worker_settings: Settings,
) -> None:
    first = add_delivery(db_session, endpoint, next_attempt_at=NOW - timedelta(seconds=2))
    second = add_delivery(db_session, endpoint, next_attempt_at=NOW - timedelta(seconds=1))
    stop_event = threading.Event()

    def answer_and_stop(request: httpx2.Request) -> httpx2.Response:
        stop_event.set()
        return httpx2.Response(200)

    claimed_count = run_once(
        session_factory,
        receiver(answer_and_stop, []),
        worker_settings,
        stop_event,
        lambda: NOW,
        lambda: 0.5,
        fake_resolver,
    )

    assert claimed_count == 2
    assert load(db_session, first.id).status == DeliveryStatus.SUCCEEDED
    assert load(db_session, second.id).status == DeliveryStatus.IN_PROGRESS
    assert claim(session_factory, NOW + timedelta(seconds=LEASE_SECONDS + 1)) != []


def test_event_posted_through_the_api_is_delivered_with_a_valid_signature(
    client: TestClient, db_session: Session, settings: Settings
) -> None:
    client.app.dependency_overrides[get_resolver] = lambda: fake_resolver
    add_user(db_session, OWNER_EMAIL)
    headers = auth_headers(client, OWNER_EMAIL)
    api_key = client.post("/api/v1/api-keys", json={"name": "shop"}, headers=headers).json()["key"]
    endpoint = client.post(
        "/api/v1/endpoints",
        json={"url": TARGET_URL, "event_types": ["order.created"]},
        headers=headers,
    ).json()
    event = client.post(
        "/api/v1/events",
        json={"event_type": "order.created", "payload": {"order_id": 7}},
        headers={"X-API-Key": api_key},
    ).json()
    received: list[httpx2.Request] = []

    claimed_count = run_once(
        client.app.state.session_factory,
        receiver(answer(200), received),
        settings,
        threading.Event(),
        lambda: NOW,
        lambda: 0.5,
        fake_resolver,
    )

    assert claimed_count == 1
    [request] = received
    assert str(request.url) == TARGET_URL
    assert verify_signature(
        endpoint["secret"], request.headers["Hookline-Signature"], request.content, NOW
    )
    assert request.headers["Hookline-Event-Id"] == event["id"]
    assert request.headers["Hookline-Event-Type"] == "order.created"
    assert request.headers["Hookline-Attempt"] == "1"
    body = json.loads(request.content)
    assert body["id"] == event["id"]
    assert body["data"] == {"order_id": 7}
    details = client.get("/api/v1/events/" + event["id"], headers=headers).json()
    assert [delivery["status"] for delivery in details["deliveries"]] == ["succeeded"]
    assert details["deliveries"][0]["attempt_count"] == 1


def test_worker_process_starts_and_stops_on_sigterm(database_url: str) -> None:
    environment = dict(os.environ, HOOKLINE_DATABASE_URL=database_url, HOOKLINE_LOG_LEVEL="INFO")
    process = subprocess.Popen(
        [sys.executable, "-m", "hookline.worker"],
        env=environment,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    output = []
    for line in process.stderr:
        output.append(line)
        if "Worker started" in line:
            break

    process.send_signal(signal.SIGTERM)
    remaining_output = process.communicate(timeout=20)[1]

    assert process.returncode == 0
    assert "Worker started" in "".join(output)
    assert "Worker stopped" in remaining_output

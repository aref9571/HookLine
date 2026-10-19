import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.api_keys.service import create_api_key
from hookline.clock import get_now
from hookline.config import Settings
from hookline.database import create_session_factory
from hookline.events.models import Event
from hookline.rate_limit.models import RateLimitWindow
from hookline.rate_limit.service import check_and_count, delete_old_windows
from hookline.users.models import User
from hookline.worker.runner import clean_up_if_due, run_worker
from tests.helpers import add_user

pytestmark = pytest.mark.integration

LIMIT = 3
EVENTS_PATH = "/api/v1/events"
NOW = datetime(2030, 1, 1, 12, 0, 15, tzinfo=UTC)
ORDER_CREATED = {"event_type": "order.created", "payload": {"order_id": 42}}


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, "owner@example.com")


@pytest.fixture
def first_key(db_session: Session, owner: User) -> str:
    return create_api_key(db_session, owner, "first").plaintext


@pytest.fixture
def second_key(db_session: Session, owner: User) -> str:
    return create_api_key(db_session, owner, "second").plaintext


def make_limited_client(database_url: str, limit: int) -> TestClient:
    from hookline.main import create_app

    return TestClient(create_app(Settings(database_url=database_url, rate_limit_per_minute=limit)))


@pytest.fixture
def limited_client(database_url: str, clean_database: None) -> Iterator[TestClient]:
    with make_limited_client(database_url, LIMIT) as client:
        set_clock(client, NOW)
        yield client
    client.app.state.engine.dispose()


def set_clock(client: TestClient, moment: datetime) -> None:
    client.app.dependency_overrides[get_now] = lambda: moment


def submit(client: TestClient, api_key: str, body: dict[str, Any] = ORDER_CREATED) -> Any:
    return client.post(EVENTS_PATH, json=body, headers={"X-API-Key": api_key})


def key_record(db_session: Session, plaintext_prefix: str) -> ApiKey:
    return db_session.scalars(select(ApiKey).where(ApiKey.prefix == plaintext_prefix[:12])).one()


def window_starts(db_session: Session) -> list[datetime]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(RateLimitWindow.window_start).order_by(RateLimitWindow.window_start)
        )
    )


def count_events(db_session: Session) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(Event)) or 0


def test_requests_up_to_the_limit_succeed_with_rate_limit_headers(
    limited_client: TestClient, first_key: str
) -> None:
    responses = [submit(limited_client, first_key) for _ in range(LIMIT)]

    assert [response.status_code for response in responses] == [201, 201, 201]
    assert {response.headers["x-ratelimit-limit"] for response in responses} == {"3"}
    assert [response.headers["x-ratelimit-remaining"] for response in responses] == ["2", "1", "0"]


def test_request_over_the_limit_returns_429_with_retry_after(
    limited_client: TestClient, first_key: str, db_session: Session
) -> None:
    for _ in range(LIMIT):
        submit(limited_client, first_key)

    response = submit(limited_client, first_key)

    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Too Many Requests"
    assert response.headers["retry-after"] == "45"
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert response.headers["x-ratelimit-limit"] == "3"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert count_events(db_session) == LIMIT


def test_rejected_requests_are_counted_too(
    limited_client: TestClient, first_key: str, db_session: Session
) -> None:
    for _ in range(LIMIT + 2):
        submit(limited_client, first_key)

    db_session.expire_all()
    assert db_session.scalars(select(RateLimitWindow.request_count)).one() == LIMIT + 2


def test_a_new_minute_resets_the_limit(limited_client: TestClient, first_key: str) -> None:
    for _ in range(LIMIT):
        submit(limited_client, first_key)
    set_clock(limited_client, NOW + timedelta(seconds=44))
    assert submit(limited_client, first_key).status_code == 429

    set_clock(limited_client, NOW + timedelta(seconds=45))
    response = submit(limited_client, first_key)

    assert response.status_code == 201
    assert response.headers["x-ratelimit-remaining"] == "2"


def test_different_keys_have_separate_limits(
    limited_client: TestClient, first_key: str, second_key: str
) -> None:
    for _ in range(LIMIT):
        submit(limited_client, first_key)

    assert submit(limited_client, first_key).status_code == 429
    assert submit(limited_client, second_key).status_code == 201


def test_count_is_kept_when_the_event_is_rejected(
    limited_client: TestClient, first_key: str, db_session: Session
) -> None:
    too_large = {"event_type": "order.created", "payload": {"text": "x" * 70000}}

    assert submit(limited_client, first_key, too_large).status_code == 413
    assert submit(limited_client, first_key).status_code == 201
    assert submit(limited_client, first_key).status_code == 201
    assert submit(limited_client, first_key).status_code == 429
    assert count_events(db_session) == 2


def test_requests_without_a_valid_key_are_not_counted(
    limited_client: TestClient, first_key: str, db_session: Session
) -> None:
    response = submit(limited_client, "hk_unknown")

    assert response.status_code == 401
    assert window_starts(db_session) == []


def test_concurrent_requests_give_exactly_the_limit_of_successes(
    database_url: str, clean_database: None, first_key: str, db_session: Session
) -> None:
    thread_count = 20
    barrier = threading.Barrier(thread_count)
    status_codes: list[int] = []
    lock = threading.Lock()

    with make_limited_client(database_url, 10) as client:
        set_clock(client, NOW)

        def send() -> None:
            barrier.wait()
            response = submit(client, first_key)
            with lock:
                status_codes.append(response.status_code)

        threads = [threading.Thread(target=send) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    client.app.state.engine.dispose()

    assert sorted(status_codes) == [201] * 10 + [429] * 10
    assert count_events(db_session) == 10


def test_check_and_count_uses_one_row_per_key_and_minute(
    db_session: Session, first_key: str, second_key: str
) -> None:
    first = key_record(db_session, first_key)
    second = key_record(db_session, second_key)

    results = [check_and_count(db_session, first.id, NOW, 2) for _ in range(3)]
    other = check_and_count(db_session, second.id, NOW, 2)
    next_minute = check_and_count(db_session, first.id, NOW + timedelta(minutes=1), 2)

    assert [result.allowed for result in results] == [True, True, False]
    assert [result.remaining for result in results] == [1, 0, 0]
    assert other.allowed
    assert next_minute.allowed
    assert window_starts(db_session) == [
        datetime(2030, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2030, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2030, 1, 1, 12, 1, tzinfo=UTC),
    ]


def add_window(db_session: Session, api_key_id: uuid.UUID, window_start: datetime) -> None:
    db_session.add(
        RateLimitWindow(api_key_id=api_key_id, window_start=window_start, request_count=5)
    )
    db_session.commit()


def test_cleanup_removes_only_windows_older_than_one_hour(
    db_session: Session, first_key: str
) -> None:
    api_key_id = key_record(db_session, first_key).id
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    for minutes_ago in [120, 61, 60, 59, 0]:
        add_window(db_session, api_key_id, now - timedelta(minutes=minutes_ago))

    delete_old_windows(db_session, now)

    assert window_starts(db_session) == [
        now - timedelta(minutes=60),
        now - timedelta(minutes=59),
        now,
    ]


def test_worker_cleans_up_at_most_once_a_minute(
    db_engine: Engine, db_session: Session, first_key: str
) -> None:
    session_factory = create_session_factory(db_engine)
    api_key_id = key_record(db_session, first_key).id
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    add_window(db_session, api_key_id, now - timedelta(hours=2))

    first_cleanup = clean_up_if_due(session_factory, now, None)
    assert first_cleanup == now
    assert window_starts(db_session) == []

    add_window(db_session, api_key_id, now - timedelta(hours=2))
    soon_after = now + timedelta(seconds=59)
    assert clean_up_if_due(session_factory, soon_after, first_cleanup) == now
    assert len(window_starts(db_session)) == 1

    a_minute_later = now + timedelta(minutes=1)
    assert clean_up_if_due(session_factory, a_minute_later, now) == a_minute_later
    assert window_starts(db_session) == []


def test_worker_loop_deletes_old_windows(
    database_url: str, db_engine: Engine, db_session: Session, first_key: str
) -> None:
    api_key_id = key_record(db_session, first_key).id
    now = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    add_window(db_session, api_key_id, now - timedelta(hours=2))
    add_window(db_session, api_key_id, now)
    stop_event = threading.Event()

    def now_and_stop() -> datetime:
        stop_event.set()
        return now

    client = httpx2.Client(transport=httpx2.MockTransport(lambda request: httpx2.Response(200)))
    run_worker(
        Settings(database_url=database_url),
        create_session_factory(db_engine),
        client,
        stop_event,
        now_and_stop,
    )

    assert window_starts(db_session) == [now]

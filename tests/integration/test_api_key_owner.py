from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.api_keys.service import create_api_key
from hookline.auth.dependencies import ApiKeyOwner
from hookline.clock import get_now
from hookline.config import Settings
from hookline.users.models import User
from tests.helpers import add_user

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


producer_router = APIRouter()


@producer_router.get("/producer-only")
def read_api_key_owner(owner: ApiKeyOwner) -> dict[str, str]:
    return {"user_id": str(owner.id)}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def producer_client(
    settings: Settings, clean_database: None, clock: FakeClock
) -> Iterator[TestClient]:
    from hookline.main import create_app

    app = create_app(settings)
    app.include_router(producer_router)
    app.dependency_overrides[get_now] = clock
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


@pytest.fixture
def owner(db_session: Session) -> User:
    return add_user(db_session, "producer@example.com")


@pytest.fixture
def api_key(db_session: Session, owner: User) -> tuple[ApiKey, str]:
    created = create_api_key(db_session, owner, "producer")
    return created.api_key, created.plaintext


def call(client: TestClient, key: str | None) -> tuple[int, dict[str, str], str]:
    headers = {} if key is None else {"X-API-Key": key}
    response = client.get("/producer-only", headers=headers)
    return response.status_code, dict(response.headers), response.text


def test_valid_key_returns_its_owner(
    producer_client: TestClient, api_key: tuple[ApiKey, str], owner: User
) -> None:
    response = producer_client.get("/producer-only", headers={"X-API-Key": api_key[1]})

    assert response.status_code == 200
    assert response.json() == {"user_id": str(owner.id)}


@pytest.mark.parametrize("key", [None, "", "hk_unknown-key", "Bearer something"])
def test_missing_or_unknown_key_returns_401(
    producer_client: TestClient, api_key: tuple[ApiKey, str], key: str | None
) -> None:
    status, headers, _ = call(producer_client, key)

    assert status == 401
    assert headers["www-authenticate"] == "ApiKey"
    assert headers["content-type"] == "application/problem+json"


def test_revoked_key_returns_401(
    producer_client: TestClient, api_key: tuple[ApiKey, str], db_session: Session
) -> None:
    stored, plaintext = api_key
    stored.revoked_at = START
    db_session.commit()

    status, _, text = call(producer_client, plaintext)

    assert status == 401
    assert "Invalid API key." in text


def test_key_of_inactive_owner_returns_401(
    producer_client: TestClient, api_key: tuple[ApiKey, str], owner: User, db_session: Session
) -> None:
    owner.is_active = False
    db_session.commit()

    status, _, _ = call(producer_client, api_key[1])

    assert status == 401


def test_bearer_token_is_not_accepted_as_api_key(
    producer_client: TestClient, api_key: tuple[ApiKey, str]
) -> None:
    response = producer_client.get(
        "/producer-only", headers={"Authorization": "Bearer " + api_key[1]}
    )

    assert response.status_code == 401


def test_last_used_at_is_updated_at_most_once_a_minute(
    producer_client: TestClient,
    api_key: tuple[ApiKey, str],
    clock: FakeClock,
    db_session: Session,
) -> None:
    stored, plaintext = api_key
    assert stored.last_used_at is None

    call(producer_client, plaintext)
    db_session.refresh(stored)
    assert stored.last_used_at == START

    clock.now = START + timedelta(seconds=59)
    call(producer_client, plaintext)
    db_session.refresh(stored)
    assert stored.last_used_at == START

    clock.now = START + timedelta(minutes=1)
    call(producer_client, plaintext)
    db_session.refresh(stored)
    assert stored.last_used_at == START + timedelta(minutes=1)

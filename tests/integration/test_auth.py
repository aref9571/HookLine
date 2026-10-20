import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hookline.auth.tokens import hash_token
from hookline.clock import get_now
from hookline.users.models import RefreshToken, User, UserRole
from hookline.users.service import create_user

pytestmark = pytest.mark.integration

EMAIL = "member@example.com"
PASSWORD = "a-long-member-password"
INVALID_LOGIN_BODY = {
    "type": "about:blank",
    "title": "Unauthorized",
    "status": 401,
    "detail": "Invalid email or password.",
}


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(client: TestClient) -> Iterator[FakeClock]:
    fake_clock = FakeClock(datetime.now(UTC))
    client.app.dependency_overrides[get_now] = fake_clock
    yield fake_clock
    client.app.dependency_overrides.clear()


def add_user(db_session: Session, email: str = EMAIL, is_active: bool = True) -> User:
    user = create_user(db_session, email, PASSWORD, UserRole.MEMBER)
    user.is_active = is_active
    db_session.commit()
    return user


def log_in(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    tokens: dict[str, str] = response.json()
    return tokens


def refresh(client: TestClient, refresh_token: str) -> int:
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    return response.status_code


def test_login_returns_access_and_refresh_tokens(client: TestClient, db_session: Session) -> None:
    add_user(db_session)

    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "token_type"}
    assert body["token_type"] == "bearer"
    me = client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + body["access_token"]})
    assert me.json()["email"] == EMAIL


def test_auth_responses_are_not_cached(client: TestClient, db_session: Session) -> None:
    add_user(db_session)

    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    logout = client.post(
        "/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}
    )
    failed = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong"})

    for response in (login, refreshed, logout, failed):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert [login.status_code, refreshed.status_code, logout.status_code] == [200, 200, 204]
    assert failed.status_code == 401


def test_other_api_responses_have_nosniff_but_no_cache_control(
    client: TestClient, db_session: Session
) -> None:
    add_user(db_session)
    tokens = log_in(client)

    response = client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer " + tokens["access_token"]}
    )

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "cache-control" not in response.headers


def test_login_ignores_email_case_and_whitespace(client: TestClient, db_session: Session) -> None:
    add_user(db_session)

    log_in(client, email="  Member@Example.COM ")


def test_login_stores_only_the_hash_of_the_refresh_token(
    client: TestClient, db_session: Session
) -> None:
    add_user(db_session)

    tokens = log_in(client)

    stored = db_session.scalars(select(RefreshToken)).all()
    assert len(stored) == 1
    assert stored[0].token_hash == hash_token(tokens["refresh_token"])
    assert stored[0].revoked_at is None


@pytest.mark.parametrize(
    ("email", "password", "is_active"),
    [
        (EMAIL, "a-wrong-password-here", True),
        ("nobody@example.com", PASSWORD, True),
        (EMAIL, PASSWORD, False),
    ],
    ids=["wrong-password", "unknown-email", "inactive-user"],
)
def test_login_failures_return_the_same_401_body(
    client: TestClient, db_session: Session, email: str, password: str, is_active: bool
) -> None:
    add_user(db_session, is_active=is_active)

    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == INVALID_LOGIN_BODY


def test_refresh_returns_a_new_pair_and_the_old_token_stops_working(
    client: TestClient, db_session: Session
) -> None:
    add_user(db_session)
    tokens = log_in(client)

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]
    me = client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer " + new_tokens["access_token"]}
    )
    assert me.status_code == 200
    assert refresh(client, new_tokens["refresh_token"]) == 200
    assert refresh(client, tokens["refresh_token"]) == 401


def test_reusing_a_revoked_refresh_token_revokes_all_tokens_of_the_user(
    client: TestClient, db_session: Session
) -> None:
    add_user(db_session)
    first_login = log_in(client)
    second_login = log_in(client)
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first_login["refresh_token"]}
    )
    rotated = response.json()

    reuse = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first_login["refresh_token"]}
    )

    assert reuse.status_code == 401
    assert reuse.json()["detail"] == "Invalid refresh token."
    assert refresh(client, rotated["refresh_token"]) == 401
    assert refresh(client, second_login["refresh_token"]) == 401
    db_session.expire_all()
    active = db_session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert active.all() == []


def test_reuse_detection_does_not_touch_other_users(
    client: TestClient, db_session: Session
) -> None:
    add_user(db_session)
    add_user(db_session, email="other@example.com")
    member_tokens = log_in(client)
    other_tokens = log_in(client, email="other@example.com")
    refresh(client, member_tokens["refresh_token"])

    refresh(client, member_tokens["refresh_token"])

    assert refresh(client, other_tokens["refresh_token"]) == 200


def test_expired_refresh_token_is_rejected(
    client: TestClient, db_session: Session, clock: FakeClock
) -> None:
    add_user(db_session)
    tokens = log_in(client)

    clock.now += timedelta(days=7)

    assert refresh(client, tokens["refresh_token"]) == 401


def test_refresh_token_works_until_it_expires(
    client: TestClient, db_session: Session, clock: FakeClock
) -> None:
    add_user(db_session)
    tokens = log_in(client)

    clock.now += timedelta(days=7) - timedelta(seconds=1)

    assert refresh(client, tokens["refresh_token"]) == 200


def test_unknown_refresh_token_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": "unknown-token"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_refresh_is_rejected_for_a_deactivated_user(
    client: TestClient, db_session: Session
) -> None:
    user = add_user(db_session)
    tokens = log_in(client)
    user.is_active = False
    db_session.commit()

    assert refresh(client, tokens["refresh_token"]) == 401


def test_logout_revokes_the_refresh_token(client: TestClient, db_session: Session) -> None:
    add_user(db_session)
    tokens = log_in(client)

    response = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 204
    assert response.content == b""
    stored = db_session.scalars(select(RefreshToken)).one()
    assert stored.revoked_at is not None


def test_logging_out_twice_is_fine(client: TestClient, db_session: Session) -> None:
    add_user(db_session)
    tokens = log_in(client)
    body = {"refresh_token": tokens["refresh_token"]}

    first = client.post("/api/v1/auth/logout", json=body)
    second = client.post("/api/v1/auth/logout", json=body)

    assert first.status_code == 204
    assert second.status_code == 204


def test_logout_with_an_unknown_token_is_fine(client: TestClient) -> None:
    response = client.post("/api/v1/auth/logout", json={"refresh_token": "unknown-token"})

    assert response.status_code == 204


def test_passwords_and_tokens_never_appear_in_logs(
    client: TestClient, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    user = add_user(db_session)
    caplog.set_level(logging.DEBUG)

    client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "a-wrong-password-here"})
    tokens = log_in(client)
    refresh(client, tokens["refresh_token"])
    refresh(client, tokens["refresh_token"])
    client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    logged = caplog.text
    assert str(user.id) in logged
    for secret in [
        PASSWORD,
        "a-wrong-password-here",
        user.password_hash,
        tokens["access_token"],
        tokens["refresh_token"],
        hash_token(tokens["refresh_token"]),
    ]:
        assert secret not in logged

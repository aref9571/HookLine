import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hookline.users.models import RefreshToken, User, UserRole
from tests.helpers import PASSWORD, add_user, auth_headers, log_in

pytestmark = pytest.mark.integration

ADMIN_EMAIL = "admin@example.com"
MEMBER_EMAIL = "member@example.com"
NEW_PASSWORD = "another-long-password"


@pytest.fixture
def admin(db_session: Session) -> User:
    return add_user(db_session, ADMIN_EMAIL, UserRole.ADMIN)


@pytest.fixture
def member(db_session: Session) -> User:
    return add_user(db_session, MEMBER_EMAIL)


@pytest.fixture
def admin_headers(client: TestClient, admin: User) -> dict[str, str]:
    return auth_headers(client, ADMIN_EMAIL)


def create_user_request(
    client: TestClient, headers: dict[str, str], email: str, role: str = "member"
) -> dict[str, object]:
    response = client.post(
        "/api/v1/users",
        json={"email": email, "password": NEW_PASSWORD, "role": role},
        headers=headers,
    )
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "POST",
            "/api/v1/users",
            {"email": "x@example.com", "password": NEW_PASSWORD, "role": "member"},
        ),
        ("GET", "/api/v1/users", None),
        ("PATCH", "/api/v1/users/{id}", {"role": "admin"}),
    ],
)
def test_members_get_403_on_admin_user_routes(
    client: TestClient, member: User, method: str, path: str, body: dict[str, str] | None
) -> None:
    headers = auth_headers(client, MEMBER_EMAIL)

    response = client.request(method, path.format(id=member.id), json=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["title"] == "Forbidden"


def test_admin_creates_a_user_who_can_log_in(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    body = create_user_request(client, admin_headers, "New.User@Example.com")

    assert set(body) == {"id", "email", "role", "is_active", "created_at"}
    assert body["email"] == "new.user@example.com"
    assert body["role"] == "member"
    assert body["is_active"] is True
    log_in(client, "new.user@example.com", NEW_PASSWORD)


def test_admin_can_create_another_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    body = create_user_request(client, admin_headers, "second.admin@example.com", "admin")

    assert body["role"] == "admin"


def test_creating_a_user_with_an_existing_email_in_different_case_returns_409(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    response = client.post(
        "/api/v1/users",
        json={"email": MEMBER_EMAIL.upper(), "password": NEW_PASSWORD, "role": "member"},
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A user with this email already exists."


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "not-an-email", "password": NEW_PASSWORD, "role": "member"}, "email"),
        ({"email": "a@example.com", "password": "short", "role": "member"}, "password"),
        ({"email": "a@example.com", "password": NEW_PASSWORD, "role": "owner"}, "role"),
    ],
)
def test_create_user_validates_the_body(
    client: TestClient, admin_headers: dict[str, str], body: dict[str, str], field: str
) -> None:
    response = client.post("/api/v1/users", json=body, headers=admin_headers)

    assert response.status_code == 400
    assert [error["field"] for error in response.json()["errors"]] == [field]


def test_list_users_is_paginated_newest_first(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    for number in range(3):
        create_user_request(client, admin_headers, f"user{number}@example.com")

    first_page = client.get("/api/v1/users", params={"limit": 2}, headers=admin_headers).json()
    second_page = client.get(
        "/api/v1/users", params={"limit": 2, "offset": 2}, headers=admin_headers
    ).json()

    assert first_page["total"] == 4
    assert first_page["limit"] == 2
    assert first_page["offset"] == 0
    assert [user["email"] for user in first_page["items"]] == [
        "user2@example.com",
        "user1@example.com",
    ]
    assert [user["email"] for user in second_page["items"]] == [
        "user0@example.com",
        ADMIN_EMAIL,
    ]
    assert second_page["total"] == 4
    assert "password_hash" not in str(first_page)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_users_rejects_invalid_page_parameters(
    client: TestClient, admin_headers: dict[str, str], params: dict[str, int]
) -> None:
    response = client.get("/api/v1/users", params=params, headers=admin_headers)

    assert response.status_code == 400


def test_admin_changes_the_role_of_a_user(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    response = client.patch(
        f"/api/v1/users/{member.id}", json={"role": "admin"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    promoted_headers = auth_headers(client, MEMBER_EMAIL)
    assert client.get("/api/v1/users", headers=promoted_headers).status_code == 200


def test_demoted_admin_loses_admin_access_at_once(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    add_user(db_session, "other.admin@example.com", UserRole.ADMIN)
    other_headers = auth_headers(client, "other.admin@example.com")
    other = db_session.scalar(select(User).where(User.email == "other.admin@example.com"))
    assert other is not None

    client.patch(f"/api/v1/users/{other.id}", json={"role": "member"}, headers=admin_headers)

    assert client.get("/api/v1/users", headers=other_headers).status_code == 403


def test_deactivating_a_user_revokes_refresh_tokens_and_blocks_login(
    client: TestClient, admin_headers: dict[str, str], member: User, db_session: Session
) -> None:
    tokens = log_in(client, MEMBER_EMAIL)

    response = client.patch(
        f"/api/v1/users/{member.id}", json={"is_active": False}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    stored_tokens = db_session.scalars(
        select(RefreshToken).where(RefreshToken.user_id == member.id)
    ).all()
    assert len(stored_tokens) == 1
    assert all(token.revoked_at is not None for token in stored_tokens)
    login = client.post("/api/v1/auth/login", json={"email": MEMBER_EMAIL, "password": PASSWORD})
    assert login.status_code == 401
    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


def test_reactivated_user_can_log_in_again(
    client: TestClient, admin_headers: dict[str, str], member: User
) -> None:
    client.patch(f"/api/v1/users/{member.id}", json={"is_active": False}, headers=admin_headers)

    response = client.patch(
        f"/api/v1/users/{member.id}", json={"is_active": True}, headers=admin_headers
    )

    assert response.json()["is_active"] is True
    log_in(client, MEMBER_EMAIL)


def test_admin_cannot_deactivate_themselves(
    client: TestClient, admin_headers: dict[str, str], admin: User
) -> None:
    response = client.patch(
        f"/api/v1/users/{admin.id}", json={"is_active": False}, headers=admin_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "You cannot deactivate your own account."


def test_admin_cannot_remove_their_own_admin_role(
    client: TestClient, admin_headers: dict[str, str], admin: User
) -> None:
    response = client.patch(
        f"/api/v1/users/{admin.id}", json={"role": "member"}, headers=admin_headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "You cannot remove your own admin role."


def test_admin_self_update_without_changes_is_allowed(
    client: TestClient, admin_headers: dict[str, str], admin: User
) -> None:
    response = client.patch(
        f"/api/v1/users/{admin.id}",
        json={"role": "admin", "is_active": True},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_updating_an_unknown_user_returns_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.patch(
        f"/api/v1/users/{uuid.uuid4()}", json={"role": "admin"}, headers=admin_headers
    )

    assert response.status_code == 404


def test_updating_with_an_invalid_id_returns_400(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.patch("/api/v1/users/not-a-uuid", json={}, headers=admin_headers)

    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "user_id"

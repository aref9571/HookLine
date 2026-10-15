import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hookline.users.models import UserRole
from hookline.users.service import create_user

pytestmark = pytest.mark.integration

EMAIL = "admin@example.com"
PASSWORD = "a-long-admin-password"


def log_in(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    access_token: str = response.json()["access_token"]
    return access_token


def test_users_me_returns_the_current_user_without_password_hash(
    client: TestClient, db_session: Session
) -> None:
    user = create_user(db_session, EMAIL, PASSWORD, UserRole.ADMIN)

    response = client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + log_in(client)})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "email", "role", "is_active", "created_at"}
    assert body["id"] == str(user.id)
    assert body["email"] == EMAIL
    assert body["role"] == "admin"
    assert body["is_active"] is True
    assert user.password_hash not in response.text


def test_users_me_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_users_me_rejects_a_deactivated_user(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, EMAIL, PASSWORD, UserRole.ADMIN)
    access_token = log_in(client)
    user.is_active = False
    db_session.commit()

    response = client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + access_token})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_users_me_rejects_a_deleted_user(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, EMAIL, PASSWORD, UserRole.ADMIN)
    access_token = log_in(client)
    db_session.delete(user)
    db_session.commit()

    response = client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + access_token})

    assert response.status_code == 401

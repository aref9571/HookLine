from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hookline.users.models import User, UserRole
from hookline.users.service import create_user

PASSWORD = "a-long-test-password"


def add_user(db_session: Session, email: str, role: UserRole = UserRole.MEMBER) -> User:
    return create_user(db_session, email, PASSWORD, role)


def log_in(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    tokens: dict[str, str] = response.json()
    return tokens


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + log_in(client, email)["access_token"]}

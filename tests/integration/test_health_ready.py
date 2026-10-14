import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_ready_returns_ok_with_database(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

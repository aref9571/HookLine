import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hookline.errors import register_error_handlers
from hookline.pagination import Page, PageQuery


@pytest.fixture
def pagination_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/numbers")
    def list_numbers(page: PageQuery) -> Page[int]:
        numbers = list(range(250))
        items = numbers[page.offset : page.offset + page.limit]
        return Page[int](items=items, total=len(numbers), limit=page.limit, offset=page.offset)

    return TestClient(app)


def test_page_defaults_to_limit_20_and_offset_0(pagination_client: TestClient) -> None:
    body = pagination_client.get("/numbers").json()

    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["total"] == 250
    assert body["items"] == list(range(20))


def test_page_uses_the_given_limit_and_offset(pagination_client: TestClient) -> None:
    body = pagination_client.get("/numbers", params={"limit": 100, "offset": 240}).json()

    assert body == {"items": list(range(240, 250)), "total": 250, "limit": 100, "offset": 240}


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
        ({"offset": -1}, "offset"),
        ({"limit": "many"}, "limit"),
    ],
)
def test_invalid_page_parameters_return_400(
    pagination_client: TestClient, params: dict[str, object], field: str
) -> None:
    response = pagination_client.get("/numbers", params=params)

    assert response.status_code == 400
    assert [error["field"] for error in response.json()["errors"]] == [field]

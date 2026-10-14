from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from hookline.config import Settings
from hookline.errors import PROBLEM_JSON, NotFoundError, UnauthorizedError, field_name
from hookline.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL


def raise_runtime_error() -> None:
    raise RuntimeError("internal detail that must stay hidden")


def raise_not_found() -> None:
    raise NotFoundError("Endpoint not found.")


def raise_unauthorized() -> None:
    raise UnauthorizedError("Missing access token.")


def raise_http_exception_with_object_detail() -> None:
    raise HTTPException(status_code=418, detail={"reason": "teapot"})


def read_items(limit: int) -> dict[str, int]:
    return {"limit": limit}


def build_test_app() -> FastAPI:
    app = create_app(Settings(database_url=UNREACHABLE_DATABASE_URL))
    app.add_api_route("/test/runtime-error", raise_runtime_error)
    app.add_api_route("/test/not-found", raise_not_found)
    app.add_api_route("/test/unauthorized", raise_unauthorized)
    app.add_api_route("/test/teapot", raise_http_exception_with_object_detail)
    app.add_api_route("/test/items", read_items)
    return app


def make_client() -> TestClient:
    return TestClient(build_test_app(), raise_server_exceptions=False)


def test_unknown_path_returns_404_problem_details() -> None:
    response = make_client().get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
    }


def test_wrong_method_returns_405_problem_details() -> None:
    response = make_client().post("/health/live")

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.headers["allow"] == "GET"
    body = response.json()
    assert body["status"] == 405
    assert body["title"] == "Method Not Allowed"


def test_unhandled_exception_returns_500_without_exception_text() -> None:
    response = make_client().get("/test/runtime-error")

    assert response.status_code == 500
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal server error",
        "status": 500,
        "detail": "An unexpected error occurred.",
    }
    assert "internal detail" not in response.text
    assert "RuntimeError" not in response.text


def test_validation_error_returns_400_with_field_errors() -> None:
    response = make_client().get("/test/items", params={"limit": "many"})

    assert response.status_code == 400
    assert response.headers["content-type"] == PROBLEM_JSON
    body = response.json()
    assert body["title"] == "Invalid request"
    assert body["detail"] == "One or more fields are invalid."
    assert body["errors"] == [
        {
            "field": "limit",
            "message": "Input should be a valid integer, unable to parse string as an integer",
        }
    ]


def test_app_error_returns_its_status_title_and_detail() -> None:
    response = make_client().get("/test/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_JSON
    assert response.json() == {
        "type": "about:blank",
        "title": "Not found",
        "status": 404,
        "detail": "Endpoint not found.",
    }


def test_unauthorized_error_sends_www_authenticate_header() -> None:
    response = make_client().get("/test/unauthorized")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"] == "Missing access token."


def test_http_exception_with_non_string_detail_uses_status_phrase() -> None:
    response = make_client().get("/test/teapot")

    assert response.status_code == 418
    assert response.json()["detail"] == "I'm a Teapot"


def test_field_name_skips_the_location_prefix() -> None:
    assert field_name(("body", "url")) == "url"
    assert field_name(("body", "items", 0, "name")) == "items.0.name"
    assert field_name(("body",)) == "body"

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status: int = 500
    title: str = "Internal server error"
    headers: dict[str, str] | None = None

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(AppError):
    status = 404
    title = "Not found"


class ConflictError(AppError):
    status = 409
    title = "Conflict"


class UnauthorizedError(AppError):
    status = 401
    title = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}


class InvalidApiKeyError(UnauthorizedError):
    headers = {"WWW-Authenticate": "ApiKey"}


class ForbiddenError(AppError):
    status = 403
    title = "Forbidden"


def problem_response(
    status: int,
    title: str,
    detail: str,
    errors: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if errors is not None:
        content["errors"] = errors
    return JSONResponse(content, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def field_name(location: tuple[int | str, ...]) -> str:
    if len(location) <= 1:
        return ".".join(str(part) for part in location)
    return ".".join(str(part) for part in location[1:])


def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return problem_response(exc.status, exc.title, exc.detail, headers=exc.headers)


def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": field_name(tuple(error["loc"])), "message": error["msg"]}
        for error in exc.errors()
    ]
    return problem_response(400, "Invalid request", "One or more fields are invalid.", errors)


def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    title = HTTPStatus(exc.status_code).phrase
    detail = exc.detail if isinstance(exc.detail, str) else title
    return problem_response(exc.status_code, title, detail, headers=exc.headers)


def handle_database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    logger.warning("Database is unavailable")
    return problem_response(503, "Service unavailable", "The database is not available.")


def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error", exc_info=exc)
    return problem_response(500, "Internal server error", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(handle_app_error)
    app.exception_handler(RequestValidationError)(handle_validation_error)
    app.exception_handler(StarletteHTTPException)(handle_http_exception)
    app.exception_handler(OperationalError)(handle_database_unavailable)
    app.exception_handler(Exception)(handle_unexpected_error)

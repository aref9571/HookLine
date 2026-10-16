from http import HTTPStatus

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hookline.errors import problem_response

BODY_TOO_LARGE_DETAIL = "The request body is too large."


def declared_body_size(scope: Scope) -> int:
    for name, value in scope["headers"]:
        if name == b"content-length" and value.isdigit():
            return int(value)
    return 0


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if declared_body_size(scope) > self.max_body_bytes:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            response = problem_response(status, status.phrase, BODY_TOO_LARGE_DETAIL)
            await response(scope, receive, send)
            return

        received_bytes = 0

        async def receive_with_limit() -> Message:
            nonlocal received_bytes
            message = await receive()
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                raise HTTPException(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, BODY_TOO_LARGE_DETAIL)
            return message

        await self.app(scope, receive_with_limit, send)

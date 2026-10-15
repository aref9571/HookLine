from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hookline.auth.tokens import decode_access_token
from hookline.config import AppSettings
from hookline.database import DbSession
from hookline.errors import ForbiddenError, UnauthorizedError
from hookline.users.models import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token.")
    claims = decode_access_token(credentials.credentials, settings)
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid access token.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("This action requires the admin role.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]

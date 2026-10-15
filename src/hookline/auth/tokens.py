import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from hookline.config import Settings
from hookline.errors import UnauthorizedError

ALGORITHM = "HS256"
ISSUER = "hookline"
ACCESS_TOKEN_TYPE = "access"
REQUIRED_CLAIMS = ["sub", "role", "type", "iat", "exp", "iss"]


@dataclass
class AccessTokenClaims:
    user_id: uuid.UUID
    role: str


def create_access_token(user_id: uuid.UUID, role: str, now: datetime, settings: Settings) -> str:
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": expires_at,
        "iss": ISSUER,
    }
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": REQUIRED_CLAIMS},
        )
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as error:
        raise UnauthorizedError("Invalid access token.") from error
    if claims["type"] != ACCESS_TOKEN_TYPE or not isinstance(claims["role"], str):
        raise UnauthorizedError("Invalid access token.")
    return AccessTokenClaims(user_id=user_id, role=claims["role"])


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

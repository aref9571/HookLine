import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from hookline.auth.passwords import verify_password
from hookline.auth.tokens import create_access_token, hash_token, new_refresh_token
from hookline.config import Settings
from hookline.errors import UnauthorizedError
from hookline.users.models import RefreshToken, User

logger = logging.getLogger(__name__)

DUMMY_PASSWORD_HASH = "$2b$12$S9HwwZvYdGtzqjkdlfMISumwymWHJ1ESXuNdKkfQDI3Wrv913A.ge"
INVALID_LOGIN_DETAIL = "Invalid email or password."
INVALID_REFRESH_TOKEN_DETAIL = "Invalid refresh token."


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def issue_tokens(session: Session, user: User, now: datetime, settings: Settings) -> TokenPair:
    access_token = create_access_token(user.id, user.role, now, settings)
    refresh_token = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=now + timedelta(days=settings.refresh_token_days),
        )
    )
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


def login(
    session: Session, email: str, password: str, now: datetime, settings: Settings
) -> TokenPair:
    user = authenticate(session, email, password)
    if user is None:
        logger.info("Login failed")
        raise UnauthorizedError(INVALID_LOGIN_DETAIL)
    tokens = issue_tokens(session, user, now, settings)
    session.commit()
    logger.info("User %s logged in", user.id)
    return tokens


def revoke_all_refresh_tokens(session: Session, user_id: uuid.UUID, now: datetime) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def rotate_refresh_token(
    session: Session, token: str, now: datetime, settings: Settings
) -> TokenPair:
    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)).with_for_update()
    )
    if stored is None:
        raise UnauthorizedError(INVALID_REFRESH_TOKEN_DETAIL)
    if stored.revoked_at is not None:
        revoke_all_refresh_tokens(session, stored.user_id, now)
        session.commit()
        logger.warning(
            "Revoked refresh token reused, all tokens of user %s revoked", stored.user_id
        )
        raise UnauthorizedError(INVALID_REFRESH_TOKEN_DETAIL)
    if stored.expires_at <= now:
        raise UnauthorizedError(INVALID_REFRESH_TOKEN_DETAIL)
    user = session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(INVALID_REFRESH_TOKEN_DETAIL)
    stored.revoked_at = now
    tokens = issue_tokens(session, user, now, settings)
    session.commit()
    return tokens


def revoke_refresh_token(session: Session, token: str, now: datetime) -> None:
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    session.commit()

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.auth.tokens import hash_token
from hookline.errors import InvalidApiKeyError, NotFoundError
from hookline.pagination import PageParams
from hookline.users.models import User

logger = logging.getLogger(__name__)

KEY_PREFIX = "hk_"
PREFIX_LENGTH = 12
LAST_USED_UPDATE_INTERVAL = timedelta(minutes=1)
INVALID_API_KEY_DETAIL = "Invalid API key."


@dataclass
class CreatedApiKey:
    api_key: ApiKey
    plaintext: str = field(repr=False)


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def create_api_key(session: Session, user: User, name: str) -> CreatedApiKey:
    plaintext = new_api_key()
    api_key = ApiKey(
        user_id=user.id,
        name=name,
        prefix=plaintext[:PREFIX_LENGTH],
        key_hash=hash_token(plaintext),
    )
    session.add(api_key)
    session.commit()
    logger.info("API key %s created for user %s", api_key.id, user.id)
    return CreatedApiKey(api_key=api_key, plaintext=plaintext)


def list_api_keys(session: Session, user: User, page: PageParams) -> tuple[list[ApiKey], int]:
    total = session.scalar(select(func.count()).where(ApiKey.user_id == user.id)) or 0
    api_keys = session.scalars(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc(), ApiKey.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(api_keys), total


def revoke_api_key(session: Session, user: User, api_key_id: uuid.UUID, now: datetime) -> None:
    api_key = session.get(ApiKey, api_key_id)
    if api_key is None or api_key.user_id != user.id:
        raise NotFoundError("API key not found.")
    if api_key.revoked_at is None:
        api_key.revoked_at = now
        session.commit()
        logger.info("API key %s revoked", api_key.id)


def should_update_last_used(api_key: ApiKey, now: datetime) -> bool:
    if api_key.last_used_at is None:
        return True
    return now - api_key.last_used_at >= LAST_USED_UPDATE_INTERVAL


def authenticate_api_key(session: Session, plaintext: str, now: datetime) -> ApiKey:
    row = session.execute(
        select(ApiKey, User)
        .join(User, ApiKey.user_id == User.id)
        .where(ApiKey.key_hash == hash_token(plaintext))
    ).first()
    if row is None:
        raise InvalidApiKeyError(INVALID_API_KEY_DETAIL)
    api_key, owner = row
    if api_key.revoked_at is not None or not owner.is_active:
        raise InvalidApiKeyError(INVALID_API_KEY_DETAIL)
    if should_update_last_used(api_key, now):
        api_key.last_used_at = now
        session.commit()
    return api_key

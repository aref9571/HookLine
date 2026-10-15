import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hookline.auth.passwords import hash_password
from hookline.auth.service import revoke_all_refresh_tokens
from hookline.errors import ConflictError, NotFoundError
from hookline.pagination import PageParams
from hookline.users.models import User, UserRole

logger = logging.getLogger(__name__)


def create_user(session: Session, email: str, password: str, role: UserRole) -> User:
    user = User(email=email, password_hash=hash_password(password), role=role.value)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ConflictError("A user with this email already exists.") from error
    logger.info("User %s created with role %s", user.id, user.role)
    return user


def list_users(session: Session, page: PageParams) -> tuple[list[User], int]:
    total = session.scalar(select(func.count()).select_from(User)) or 0
    users = session.scalars(
        select(User).order_by(User.created_at.desc(), User.id).limit(page.limit).offset(page.offset)
    )
    return list(users), total


def update_user(
    session: Session,
    admin: User,
    user_id: uuid.UUID,
    role: UserRole | None,
    is_active: bool | None,
    now: datetime,
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    if user.id == admin.id and is_active is False:
        raise ConflictError("You cannot deactivate your own account.")
    if user.id == admin.id and role == UserRole.MEMBER:
        raise ConflictError("You cannot remove your own admin role.")
    if role is not None:
        user.role = role.value
    if is_active is False:
        revoke_all_refresh_tokens(session, user.id, now)
    if is_active is not None:
        user.is_active = is_active
    session.commit()
    logger.info("User %s updated by admin %s", user.id, admin.id)
    return user

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hookline.auth.passwords import hash_password
from hookline.errors import ConflictError
from hookline.users.models import User, UserRole


def create_user(session: Session, email: str, password: str, role: UserRole) -> User:
    existing = session.scalar(select(User.id).where(func.lower(User.email) == email.lower()))
    if existing is not None:
        raise ConflictError("A user with this email already exists.")
    user = User(email=email, password_hash=hash_password(password), role=role.value)
    session.add(user)
    session.commit()
    return user

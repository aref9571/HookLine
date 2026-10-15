import uuid

from fastapi import APIRouter

from hookline.auth.dependencies import AdminUser, CurrentUser
from hookline.clock import Now
from hookline.database import DbSession
from hookline.pagination import Page, PageQuery
from hookline.users import service
from hookline.users.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("", status_code=201)
def create_user(body: UserCreate, db: DbSession, admin: AdminUser) -> UserRead:
    user = service.create_user(db, body.email, body.password, body.role)
    return UserRead.model_validate(user)


@router.get("")
def list_users(db: DbSession, admin: AdminUser, page: PageQuery) -> Page[UserRead]:
    users, total = service.list_users(db, page)
    return Page[UserRead](
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/{user_id}")
def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: DbSession, admin: AdminUser, now: Now
) -> UserRead:
    user = service.update_user(db, admin, user_id, body.role, body.is_active, now)
    return UserRead.model_validate(user)

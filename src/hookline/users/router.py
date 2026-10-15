from fastapi import APIRouter

from hookline.auth.dependencies import CurrentUser
from hookline.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)

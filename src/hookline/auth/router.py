from fastapi import APIRouter, Response

from hookline.auth import service
from hookline.auth.schemas import LoginRequest, RefreshRequest, TokenResponse
from hookline.clock import Now
from hookline.config import AppSettings
from hookline.database import DbSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginRequest, db: DbSession, settings: AppSettings, now: Now) -> TokenResponse:
    tokens = service.login(db, body.email, body.password, now, settings)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh")
def refresh(body: RefreshRequest, db: DbSession, settings: AppSettings, now: Now) -> TokenResponse:
    tokens = service.rotate_refresh_token(db, body.refresh_token, now, settings)
    return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest, db: DbSession, now: Now) -> Response:
    service.revoke_refresh_token(db, body.refresh_token, now)
    return Response(status_code=204)

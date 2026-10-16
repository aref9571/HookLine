import logging

from fastapi import FastAPI

from hookline.api_keys.router import router as api_keys_router
from hookline.auth.router import router as auth_router
from hookline.body_limit import BodySizeLimitMiddleware
from hookline.config import Settings, get_settings
from hookline.database import create_engine_from_settings, create_session_factory
from hookline.endpoints.router import router as endpoints_router
from hookline.errors import register_error_handlers
from hookline.health.router import router as health_router
from hookline.users.router import router as users_router

APP_VERSION = "0.1.0"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=APP_VERSION, docs_url="/docs")
    app.state.settings = settings
    app.state.engine = create_engine_from_settings(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(api_keys_router)
    app.include_router(endpoints_router)
    return app


app = create_app()

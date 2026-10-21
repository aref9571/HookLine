from fastapi import FastAPI

from hookline.api_keys.router import router as api_keys_router
from hookline.auth.router import router as auth_router
from hookline.body_limit import BodySizeLimitMiddleware
from hookline.config import APP_VERSION, Settings, configure_logging, get_settings
from hookline.database import create_engine_from_settings, create_session_factory
from hookline.deliveries.router import router as deliveries_router
from hookline.endpoints.router import router as endpoints_router
from hookline.errors import PROBLEM_RESPONSES, register_error_handlers
from hookline.events.router import router as events_router
from hookline.health.router import router as health_router
from hookline.request_logging import RequestLoggingMiddleware
from hookline.security_headers import SecurityHeadersMiddleware
from hookline.stats.router import router as stats_router
from hookline.users.router import router as users_router


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=APP_VERSION,
        docs_url="/docs",
        responses=PROBLEM_RESPONSES,
    )
    app.state.settings = settings
    app.state.engine = create_engine_from_settings(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(api_keys_router)
    app.include_router(endpoints_router)
    app.include_router(events_router)
    app.include_router(deliveries_router)
    app.include_router(stats_router)
    return app


app = create_app()

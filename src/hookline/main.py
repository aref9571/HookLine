import logging

from fastapi import FastAPI

from hookline.config import Settings, get_settings
from hookline.health.router import router as health_router

APP_VERSION = "0.1.0"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=APP_VERSION, docs_url="/docs")
    app.include_router(health_router)
    return app


app = create_app()

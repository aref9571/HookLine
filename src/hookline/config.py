from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, Request
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HOOKLINE_", hide_input_in_errors=True)

    app_name: str = "Hookline"
    log_level: LogLevel = "INFO"
    database_url: str
    jwt_secret: SecretStr = Field(min_length=32)
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=7, ge=1)
    require_https_targets: bool = True
    allow_private_targets: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(get_app_settings)]

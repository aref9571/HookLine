import pytest
from pydantic import ValidationError

from hookline.config import Settings, get_settings
from hookline.main import create_app


def test_settings_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKLINE_APP_NAME", raising=False)
    monkeypatch.delenv("HOOKLINE_LOG_LEVEL", raising=False)

    settings = Settings()

    assert settings.app_name == "Hookline"
    assert settings.log_level == "INFO"


def test_settings_read_log_level_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.log_level == "DEBUG"


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOKLINE_LOG_LEVEL", "VERBOSE")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_returns_cached_instance() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()


def test_create_app_uses_given_settings() -> None:
    app = create_app(Settings(app_name="Hookline Test"))

    assert app.title == "Hookline Test"
